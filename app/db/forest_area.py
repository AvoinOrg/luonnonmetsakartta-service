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
