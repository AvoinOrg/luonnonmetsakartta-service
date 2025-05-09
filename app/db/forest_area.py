from typing import List, Optional, Union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError

from app.db.models.forest_area import ForestArea


async def get_forest_area_by_id(
    db_session: AsyncSession, id: str
) -> Optional[ForestArea]:
    result = await db_session.execute(select(ForestArea).filter_by(id=id))
    area = result.scalars().first()
    return area if area else None


async def get_all_forest_areas(db_session: AsyncSession) -> List[ForestArea]:
    result = await db_session.execute(select(ForestArea))
    return list(result.scalars().all())


async def get_forest_areas_by_layer_id(
    db_session: AsyncSession, layer_id: str
) -> List[ForestArea]:
    result = await db_session.execute(
        select(ForestArea).filter(ForestArea.layer_id == layer_id)
    )
    return list(result.scalars().all())


async def get_forest_areas_centroids_by_layer_id(  # Consider renaming if not strictly for centroids
    db_session: AsyncSession, layer_id: str
) -> List[ForestArea]:
    """
    Dynamically fetches all columns for ForestArea except 'geometry',
    for a given layer_id, and returns a list of ForestArea objects.
    The 'geometry' attribute on the returned objects will be uninitialized (None or default).
    """

    # Dynamically get all ForestArea model attributes except 'geometry'
    # This list will contain things like ForestArea.id, ForestArea.name, ForestArea.centroid, etc.
    model_attributes_to_select = [
        getattr(ForestArea, col.name)
        for col in ForestArea.__table__.columns
        if col.name != "geometry"
    ]

    stmt = select(*model_attributes_to_select).filter(ForestArea.layer_id == layer_id)

    result = await db_session.execute(stmt)
    rows = result.all()

    forest_areas_list: List[ForestArea] = []

    attribute_keys = [attr.key for attr in model_attributes_to_select]

    for row_data in rows:
        area = ForestArea()
        for i, key in enumerate(attribute_keys):
            setattr(area, key, row_data[i])

        forest_areas_list.append(area)

    return forest_areas_list


async def create_forest_area(db_session: AsyncSession, area: ForestArea) -> ForestArea:
    try:
        db_session.add(area)
        await db_session.commit()
        await db_session.refresh(area)
        return area
    except SQLAlchemyError:
        await db_session.rollback()
        raise


async def update_forest_area(
    db_session: AsyncSession, area: ForestArea
) -> Union[ForestArea, None]:
    if not area:
        return None

    await db_session.merge(area)
    await db_session.commit()
    await db_session.refresh(area)
    return area


async def delete_forest_area(db_session: AsyncSession, area: ForestArea) -> bool:
    if not area:
        return False

    try:
        await db_session.execute(delete(ForestArea).filter_by(id=area.id))
        await db_session.commit()
        return True
    except SQLAlchemyError:
        await db_session.rollback()
        return False


async def delete_forest_area_by_id(db_session: AsyncSession, id: str) -> bool:
    if not id:
        return False

    try:
        await db_session.execute(delete(ForestArea).filter_by(id=id))
        await db_session.commit()
        return True
    except SQLAlchemyError:
        await db_session.rollback()
        return False


async def delete_forest_area_by_layer_id(
    db_session: AsyncSession, layer_id: str
) -> bool:
    if not id:
        return False

    try:
        await db_session.execute(delete(ForestArea).filter_by(layer_id=layer_id))
        await db_session.commit()
        return True
    except SQLAlchemyError:
        await db_session.rollback()
        return False


async def get_forest_area_by_name(
    db_session: AsyncSession, name: str
) -> Optional[ForestArea]:
    result = await db_session.execute(
        select(ForestArea).filter(ForestArea.name.ilike(name))
    )
    area = result.scalars().first()
    return area if area else None


async def get_forest_areas_by_municipality(
    db_session: AsyncSession, municipality: str
) -> List[ForestArea]:
    result = await db_session.execute(
        select(ForestArea).filter(ForestArea.municipality.ilike(municipality))
    )
    return list(result.scalars().all())
