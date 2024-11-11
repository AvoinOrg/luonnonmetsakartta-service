from http.client import HTTPException

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from contextlib import asynccontextmanager
from sqlalchemy.pool import NullPool
from typing import Callable, AsyncGenerator

from app import config
from app.utils.logger import get_logger

logger = get_logger(__name__)

global_settings = config.get_settings()
pg_url = global_settings.pg_url


engine = create_async_engine(
    pg_url,
    future=True,
    echo=False,
    poolclass=NullPool,
)


AsyncSessionLocal = async_sessionmaker(engine, autoflush=False, expire_on_commit=False)


@asynccontextmanager
async def base_async_db_context(
    session_generator: Callable[[], AsyncSession], logger_msg: str
) -> AsyncGenerator:
    try:
        session: AsyncSession = session_generator()
        yield session
    except SQLAlchemyError as sql_ex:
        # await session.rollback()
        raise sql_ex
    except HTTPException as http_ex:
        # await session.rollback()
        raise http_ex
    else:
        await session.commit()
    finally:
        await session.close()


async def get_async_db() -> AsyncGenerator:
    async with base_async_db_context(
        AsyncSessionLocal, f"ASYNC Pool: {engine.pool.status()}"
    ) as session:
        yield session


@asynccontextmanager
async def get_async_context_db() -> AsyncGenerator:
    async with base_async_db_context(
        AsyncSessionLocal, f"ASYNC Pool: {engine.pool.status()}"
    ) as session:
        yield session
