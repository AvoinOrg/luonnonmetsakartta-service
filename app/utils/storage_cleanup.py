import asyncio
from datetime import timedelta, datetime, timezone

from sqlalchemy import text

from app import config
from app.db import connection
from app.utils.logger import get_logger
from app.api.bucket import storage_client

logger = get_logger(__name__)
settings = config.get_settings()


TABLE_SQL = """
CREATE TABLE IF NOT EXISTS storage_deletion_job (
  bucket_name TEXT PRIMARY KEY,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT NULL,
  next_attempt_ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_ts TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


async def init_storage_cleanup() -> None:
    async with connection.get_async_context_db() as session:
        await session.execute(text(TABLE_SQL))


def _backoff_minutes(attempts: int) -> int:
    # Exponential backoff up to 60 minutes
    return min(2 ** attempts, 60)


async def enqueue_bucket_deletion(bucket_name: str) -> None:
    """Insert or update a deletion job for the given bucket."""
    now = datetime.now(timezone.utc)
    sql = text(
        """
        INSERT INTO storage_deletion_job (bucket_name, attempts, last_error, next_attempt_ts, created_ts, updated_ts)
        VALUES (:bucket_name, 0, NULL, :next_attempt_ts, :now, :now)
        ON CONFLICT (bucket_name) DO UPDATE SET
          next_attempt_ts = EXCLUDED.next_attempt_ts,
          updated_ts = EXCLUDED.updated_ts
        """
    )
    async with connection.get_async_context_db() as session:
        await session.execute(sql, {"bucket_name": bucket_name, "next_attempt_ts": now, "now": now})


async def process_storage_deletion_jobs(max_jobs: int = 20) -> None:
    """Process due storage deletion jobs."""
    async with connection.get_async_context_db() as session:
        # Select due jobs
        rows = await session.execute(
            text(
                "SELECT bucket_name, attempts FROM storage_deletion_job WHERE next_attempt_ts <= now() ORDER BY next_attempt_ts ASC LIMIT :limit"
            ),
            {"limit": max_jobs},
        )
        jobs = rows.all()

    for bucket_name, attempts in jobs:
        try:
            await storage_client.delete_bucket(bucket_name)
            # Success: remove job
            async with connection.get_async_context_db() as session:
                await session.execute(
                    text("DELETE FROM storage_deletion_job WHERE bucket_name = :bucket_name"),
                    {"bucket_name": bucket_name},
                )
            logger.info(f"Deleted bucket '{bucket_name}' via cleanup job.")
        except Exception as e:
            # Schedule next attempt with backoff
            next_minutes = _backoff_minutes(attempts + 1)
            next_ts = datetime.now(timezone.utc) + timedelta(minutes=next_minutes)
            async with connection.get_async_context_db() as session:
                await session.execute(
                    text(
                        """
                        UPDATE storage_deletion_job
                        SET attempts = attempts + 1,
                            last_error = :err,
                            next_attempt_ts = :next_ts,
                            updated_ts = :now
                        WHERE bucket_name = :bucket_name
                        """
                    ),
                    {
                        "bucket_name": bucket_name,
                        "err": str(e)[:1000],
                        "next_ts": next_ts,
                        "now": datetime.now(timezone.utc),
                    },
                )
            logger.warning(
                f"Rescheduled deletion for bucket '{bucket_name}' in {next_minutes} min (attempt {attempts+1}). Error: {e}"
            )


async def start_storage_cleanup_worker(stop_event: asyncio.Event, interval_seconds: int = 300) -> None:
    """Background worker that periodically processes deletion jobs until stop_event is set."""
    await init_storage_cleanup()
    while not stop_event.is_set():
        try:
            await process_storage_deletion_jobs()
        except Exception:
            logger.exception("Storage cleanup worker cycle failed")
        
        # Wait for the interval or until the stop event is set
        try:
            # Wait for the stop_event to be set, with a timeout of interval_seconds.
            # This makes the worker responsive to shutdown signals.
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            # This is the normal case; the timeout is reached, and we loop again.
            continue
        except asyncio.CancelledError:
            # The task was cancelled, likely during shutdown.
            logger.info("Storage cleanup worker cancelled.")
            break
