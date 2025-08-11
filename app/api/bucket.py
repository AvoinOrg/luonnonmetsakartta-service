import os
from uuid import UUID
from urllib.parse import unquote

import httpx
from fastapi import UploadFile

from app import config
from app.utils.logger import get_logger

settings = config.get_settings()
logger = get_logger(__name__)


class StorageClient:
    def __init__(self):
        self.base_url = settings.storage_url
        self.auth_headers = {"Authorization": f"Bearer {settings.storage_auth_key}"}
        # Use generous defaults to accommodate slower networks/storage backends
        self.timeout = httpx.Timeout(connect=10.0, read=300.0, write=300.0, pool=10.0)
        # Disable keep-alives to avoid stale connections on flaky gateways
        self.client_limits = httpx.Limits(max_keepalive_connections=0, max_connections=20)
        self.client_args = {"timeout": self.timeout, "limits": self.client_limits, "http2": False}
        # Cache buckets we've attempted to create to avoid redundant requests
        self._created_buckets: set[str] = set()

    async def create_bucket_if_not_exists(self, bucket_name: str):
        """Creates a new storage bucket if it doesn't already exist and makes it public."""
        check_url = f"{self.base_url}/bucket/{bucket_name}"
        async with httpx.AsyncClient(**self.client_args) as client:
            try:
                # Check if the bucket already exists
                response = await client.get(check_url, headers=self.auth_headers)
                if response.status_code == 200:
                    logger.info(f"Bucket '{bucket_name}' already exists.")
                    return

                # If the bucket does not exist, Supabase API returns a 4xx error.
                # We proceed to create it.
                logger.info(
                    f"Bucket '{bucket_name}' not found. Attempting to create it."
                )
                create_url = f"{self.base_url}/bucket"
                headers = {**self.auth_headers, "Content-Type": "application/json"}
                payload = {"name": bucket_name, "public": True}

                create_response = await client.post(
                    create_url, headers=headers, json=payload
                )
                create_response.raise_for_status()
                logger.info(f"Successfully created bucket '{bucket_name}'.")

            except httpx.HTTPStatusError as e:
                # Log the response body for better debugging
                error_details = e.response.text
                logger.error(
                    f"Failed to check or create bucket '{bucket_name}': {e.response.status_code} - {error_details}"
                )
                # Re-raise the exception to be handled by the caller
                raise

    async def _ensure_bucket_created(self, bucket_name: str, client: httpx.AsyncClient) -> None:
        """Create bucket without pre-check; treat 200/201/409 as success. Caches the result."""
        if bucket_name in self._created_buckets:
            return
        create_url = f"{self.base_url}/bucket"
        headers = {**self.auth_headers, "Content-Type": "application/json"}
        payload = {"name": bucket_name, "public": True}
        response = await client.post(create_url, headers=headers, json=payload)
        if response.status_code in (200, 201, 409):
            # 409 means already exists
            self._created_buckets.add(bucket_name)
            if response.status_code == 409:
                logger.info(f"Bucket '{bucket_name}' already exists (409).")
            else:
                logger.info(f"Successfully created bucket '{bucket_name}'.")
            return
        response.raise_for_status()

    async def empty_bucket(self, bucket_name: str):
        """Empties a bucket using Supabase's empty endpoint, if available."""
        empty_url = f"{self.base_url}/bucket/{bucket_name}/empty"
        async with httpx.AsyncClient(**self.client_args) as client:
            try:
                # Some gateways require a JSON body; send an empty object to be safe
                headers = {**self.auth_headers, "Content-Type": "application/json"}
                response = await client.post(empty_url, headers=headers, json={})
                if response.status_code in (200, 204):
                    logger.info(f"Emptied bucket '{bucket_name}'.")
                    return
                # If the endpoint is not supported, fall back to best-effort (no-op)
                if response.status_code == 404:
                    logger.warning(
                        f"Empty endpoint not found for bucket '{bucket_name}'. Skipping empty."
                    )
                    return
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"Failed to empty bucket '{bucket_name}': {e.response.status_code} - {e.response.text}"
                )
                raise

    async def delete_bucket(self, bucket_name: str):
        """Empties and deletes a bucket. Best-effort empty first, then delete."""
        async with httpx.AsyncClient(**self.client_args) as client:
            # Empty first (ignore failures during empty to still attempt delete)
            try:
                await self.empty_bucket(bucket_name)
            except Exception as e:
                logger.warning(f"Proceeding to delete bucket '{bucket_name}' despite empty failure: {e}")

            delete_url = f"{self.base_url}/bucket/{bucket_name}"
            try:
                response = await client.delete(delete_url, headers=self.auth_headers)
                if response.status_code in (200, 204):
                    logger.info(f"Deleted bucket '{bucket_name}'.")
                    return
                if response.status_code == 404:
                    logger.info(f"Bucket '{bucket_name}' not found. Nothing to delete.")
                    return
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"Failed to delete bucket '{bucket_name}': {e.response.status_code} - {e.response.text}"
                )
                raise

    async def upload_file_object(
        self, file: UploadFile, bucket_name: str, object_path: str, content_type: str
    ):
        """Uploads a file-like object, creating the bucket if it doesn't exist."""
        upload_url = f"{self.base_url}/object/{bucket_name}/{object_path}"
        headers = {**self.auth_headers, "Content-Type": content_type, "Connection": "close"}

        # Reading the content into memory once is simpler and safer for retries.
        await file.seek(0)
        content = await file.read()
        await file.close()  # Explicitly close the file to release resources

        async with httpx.AsyncClient(**self.client_args) as client:
            try:
                # First attempt to upload
                response = await client.post(upload_url, headers=headers, content=content)
                response.raise_for_status()
                logger.info(f"Successfully uploaded to {bucket_name}/{object_path}")
                return
            except (httpx.HTTPStatusError, httpx.ReadError) as e:
                # If it fails with 400/404, the bucket might not exist.
                # If it fails with ReadError, it's a transient network issue.
                # In either case, we try to ensure the bucket exists and retry once.
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code not in (400, 404):
                    raise

                logger.warning(
                    f"Upload failed with {type(e).__name__}, attempting to create bucket '{bucket_name}' and retry."
                )
                try:
                    # Create the bucket. This handles cases where it already exists.
                    await self._ensure_bucket_created(bucket_name, client)
                    # Retry the upload once. The content is already in memory.
                    response = await client.post(
                        upload_url, headers=headers, content=content
                    )
                    response.raise_for_status()
                    logger.info(
                        f"Successfully uploaded to {bucket_name}/{object_path} on second attempt."
                    )
                    return
                except Exception as retry_e:
                    logger.error(f"Upload retry failed for '{object_path}': {retry_e}")
                    raise retry_e from e
            except Exception as e:
                logger.error(f"An unexpected error occurred during upload: {e}")
                raise

    async def delete_file_object(self, bucket_name: str, object_path: str) -> None:
        """Deletes a single file object from a storage bucket."""
        delete_url = f"{self.base_url}/object/{bucket_name}/{object_path}"
        async with httpx.AsyncClient(**self.client_args) as client:
            try:
                response = await client.delete(delete_url, headers=self.auth_headers)
                if response.status_code in (200, 204):
                    logger.info(f"Deleted object {bucket_name}/{object_path}")
                    return
                if response.status_code == 404:
                    logger.info(
                        f"Object not found (already deleted): {bucket_name}/{object_path}"
                    )
                    return
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"Failed to delete object {bucket_name}/{object_path}: {e.response.status_code} - {e.response.text}"
                )
                raise


storage_client = StorageClient()


def _parse_bucket_and_path_from_public_url(public_url: str) -> tuple[str, str] | None:
    """Parses bucket name and object path from a public URL created by this service.
    Expected format: {base}/object/public/{bucket}/{object_path}
    Falls back to {base}/object/{bucket}/{object_path} if 'public' segment is missing.
    """
    try:
        if "/object/public/" in public_url:
            tail = public_url.split("/object/public/", 1)[1]
        elif "/object/" in public_url:
            tail = public_url.split("/object/", 1)[1]
        else:
            return None
        bucket, rest = tail.split("/", 1)
        return unquote(bucket), unquote(rest)
    except Exception:
        return None


async def delete_file_by_public_url(public_url: str) -> None:
    parsed = _parse_bucket_and_path_from_public_url(public_url)
    if not parsed:
        logger.warning(f"Could not parse bucket/path from URL: {public_url}")
        return
    bucket, path = parsed
    await storage_client.delete_file_object(bucket, path)


async def upload_picture_to_bucket(
    file: UploadFile, layer_id: str, forest_area_id: str, picture_id: UUID
) -> str:
    """
    Uploads a picture to a layer-specific S3 bucket and returns the public URL.
    """
    if not file.filename:
        raise ValueError("File must have a filename")

    bucket_name = f"{settings.storage_bucket_prefix}-{layer_id}".lower()
    _, extension = os.path.splitext(file.filename)
    object_path = f"{forest_area_id}/{picture_id}{extension}"

    # Proceed with the upload
    await storage_client.upload_file_object(
        file,
        bucket_name,
        object_path,
        file.content_type or "application/octet-stream",
    )

    # Construct the public URL for accessing the object
    public_url = f"{settings.storage_url}/object/public/{bucket_name}/{object_path}"
    return public_url


async def delete_layer_bucket(layer_id: str) -> None:
    """Deletes the storage bucket associated with a layer (best-effort)."""
    bucket_name = f"{settings.storage_bucket_prefix}-{layer_id}".lower()
    try:
        await storage_client.delete_bucket(bucket_name)
    except Exception as e:
        # Log and swallow to avoid failing layer deletion due to storage issues
        logger.error(f"Error deleting bucket for layer {layer_id}: {e}")
