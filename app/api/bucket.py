import os
from uuid import UUID

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

    async def create_bucket_if_not_exists(self, bucket_name: str):
        """Creates a new storage bucket if it doesn't already exist and makes it public."""
        check_url = f"{self.base_url}/bucket/{bucket_name}"
        async with httpx.AsyncClient() as client:
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

    async def upload_file_object(
        self, file: UploadFile, bucket_name: str, object_path: str, content_type: str
    ):
        """Uploads a file-like object to the specified storage bucket."""
        # Note: Supabase upload URL does not include '/public'
        upload_url = f"{self.base_url}/object/{bucket_name}/{object_path}"
        headers = {**self.auth_headers, "Content-Type": content_type}

        async with httpx.AsyncClient() as client:
            try:
                content = await file.read()
                response = await client.post(upload_url, headers=headers, content=content)
                response.raise_for_status()
                logger.info(f"Successfully uploaded to {bucket_name}/{object_path}")
            except httpx.HTTPStatusError as e:
                error_details = e.response.text
                logger.error(
                    f"Failed to upload to storage: {e.response.status_code} - {error_details}"
                )
                raise


storage_client = StorageClient()


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

    # Ensure the bucket exists before attempting to upload
    await storage_client.create_bucket_if_not_exists(bucket_name)

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
