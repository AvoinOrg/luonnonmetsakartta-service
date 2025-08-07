import httpx
from fastapi import UploadFile
from uuid import UUID
import os

from app import config

settings = config.get_settings()


async def upload_picture_to_bucket(
    file: UploadFile, layer_id: str, forest_area_id: str, picture_id: UUID
) -> str:
    """
    Uploads a picture to the S3 bucket and returns the public URL.
    """
    if not file.filename:
        raise ValueError("File must have a filename")

    _, extension = os.path.splitext(file.filename)
    object_path = f"{layer_id}/{forest_area_id}/{picture_id}{extension}"
    upload_url = (
        f"https://{settings.storage_url}/object/{settings.storage_bucket}/{object_path}"
    )

    headers = {
        "Authorization": f"Bearer {settings.storage_auth_key}",
        "Content-Type": file.content_type or "application/octet-stream",
    }

    async with httpx.AsyncClient() as client:
        file_content = await file.read()
        response = await client.post(upload_url, content=file_content, headers=headers)

    response.raise_for_status()

    public_url = f"https://{settings.storage_url}/object/public/{settings.storage_bucket}/{object_path}"
    return public_url
