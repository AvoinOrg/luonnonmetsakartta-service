from typing import List, Optional, Union
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import UUID, delete
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.models.forest_layer import ForestLayer


def get_index_name_for_id(id: str) -> str:
    layer_uuid = id
    if isinstance(id, str):
        layer_uuid = uuid.UUID(id)

    index_suffix = layer_uuid.hex
    
    index_name = f"idx_area_geom_layer_{index_suffix}"[:63]

    return index_name

async def get_forest_layer_by_id(
    db_session: AsyncSession, id: str
) -> Optional[ForestLayer]:
    result = await db_session.execute(select(ForestLayer).filter_by(id=id))
    layer = result.scalars().first()
    return layer if layer else None


async def get_all_forest_layers(db_session: AsyncSession) -> List[ForestLayer]:
    result = await db_session.execute(select(ForestLayer))
    return list(result.scalars().all())


async def create_forest_layer(
    db_session: AsyncSession, layer: ForestLayer
) -> ForestLayer:
    try:
        db_session.add(layer)
        await db_session.commit()
        await db_session.refresh(layer)

        index_name = get_index_name_for_id(layer.id)
        # Create spatial index for this layer
        create_index_sql = text(f"""
            CREATE INDEX {index_name} 
            ON area 
            USING GIST (geometry) 
            WHERE layer_id = '{layer.id}';
        """)
        await db_session.execute(create_index_sql)
        await db_session.commit()

        return layer
    except SQLAlchemyError:
        await db_session.rollback()
        raise


async def update_forest_layer(
    db_session: AsyncSession, layer: ForestLayer
) -> Union[ForestLayer, None]:
    if not layer:
        return None

    await db_session.merge(layer)
    await db_session.commit()
    await db_session.refresh(layer)
    return layer


async def delete_forest_layer(db_session: AsyncSession, layer: ForestLayer) -> bool:
    if not layer:
        return False

    try:
        index_name = get_index_name_for_id(layer.id)
        # Drop the spatial index for this layer
        drop_index_sql = text(f"""
            DROP INDEX IF EXISTS {index_name};
        """)
        await db_session.execute(drop_index_sql)

        # Delete the layer
        await db_session.execute(delete(ForestLayer).filter_by(id=layer.id))
        await db_session.commit()
        return True
    except SQLAlchemyError:
        await db_session.rollback()
        return False


async def delete_forest_layer_by_id(db_session: AsyncSession, id: str) -> bool:
    if not id:
        return False

    try:
        index_name = get_index_name_for_id(id)
        # Drop the spatial index for this layer
        drop_index_sql = text(f"""
            DROP INDEX IF EXISTS {index_name};
        """)
        await db_session.execute(drop_index_sql)

        # Delete the layer
        await db_session.execute(delete(ForestLayer).filter_by(id=id))
        await db_session.commit()
        return True
    except SQLAlchemyError:
        await db_session.rollback()
        return False


async def get_forest_layer_by_name(
    db_session: AsyncSession, name: str
) -> Optional[ForestLayer]:
    result = await db_session.execute(
        select(ForestLayer).filter(ForestLayer.name.ilike(name))
    )
    layer = result.scalars().first()
    return layer if layer else None


async def get_forest_layers_by_symbol(
    db_session: AsyncSession, symbol: str
) -> List[ForestLayer]:
    result = await db_session.execute(
        select(ForestLayer).filter(ForestLayer.symbol.ilike(symbol))
    )
    return list(result.scalars().all())
