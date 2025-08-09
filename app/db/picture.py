from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.picture import Picture


async def add_picture_to_db(
    session: AsyncSession,
    forest_area_id: str,
    bucket_url: str,
    name: str,
) -> Picture:
    """
    Creates and adds a new Picture object to the session.
    """
    new_picture = Picture(
        forest_area_id=forest_area_id,
        bucket_url=bucket_url,
        name=name,
    )
    session.add(new_picture)
    return new_picture


async def delete_picture_from_db(
    session: AsyncSession,
    picture_id: str,
) -> None:
    """
    Deletes a Picture object from the session by its ID.
    """
    await session.execute(delete(Picture).where(Picture.id == picture_id))
    await session.commit()
