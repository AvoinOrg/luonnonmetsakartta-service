from typing import List, Optional, Union

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.models.layer import Layer

async def get_layer_by_id(db_session: AsyncSession, id: str) -> Optional[Layer]:
    result = await db_session.execute(select(Layer).filter_by(id=id))
    layer = result.scalars().first()
    return layer if layer else None

async def get_all_layers(db_session: AsyncSession) -> List[Layer]:
    result = await db_session.execute(select(Layer))
    return list(result.scalars().all())

async def create_layer(db_session: AsyncSession, layer: Layer) -> Layer:
    try:
        db_session.add(layer)
        await db_session.commit()
        await db_session.refresh(layer)
        
        # Create spatial index for this layer
        create_index_sql = text(f"""
            CREATE INDEX idx_area_geom_layer_{layer.id} 
            ON area 
            USING GIST (geometry) 
            WHERE layer_id = :layer_id;
        """)
        await db_session.execute(create_index_sql, {"layer_id": layer.id})
        await db_session.commit()
        
        return layer
    except SQLAlchemyError:
        await db_session.rollback()
        raise

async def update_layer(db_session: AsyncSession, layer: Layer) -> Union[Layer, None]:
    if not layer:
        return None
        
    await db_session.merge(layer)
    await db_session.commit()
    await db_session.refresh(layer)
    return layer

async def delete_layer(db_session: AsyncSession, layer: Layer) -> bool:
    if not layer:
        return False
    
    try:
        # Drop the spatial index for this layer
        drop_index_sql = text(f"""
            DROP INDEX IF EXISTS idx_area_geom_layer_{layer.id};
        """)
        await db_session.execute(drop_index_sql)
        
        # Delete the layer
        await db_session.execute(delete(Layer).filter_by(id=layer.id))
        await db_session.commit()
        return True
    except SQLAlchemyError:
        await db_session.rollback()
        return False

async def delete_layer_by_id(db_session: AsyncSession, id: str) -> bool:
    if not id:
        return False
    
    try:
        # Drop the spatial index for this layer
        drop_index_sql = text(f"""
            DROP INDEX IF EXISTS idx_area_geom_layer_{id};
        """)
        await db_session.execute(drop_index_sql)
        
        # Delete the layer
        await db_session.execute(delete(Layer).filter_by(id=id))
        await db_session.commit()
        return True
    except SQLAlchemyError:
        await db_session.rollback()
        return False

async def get_layer_by_name(db_session: AsyncSession, name: str) -> Optional[Layer]:
    result = await db_session.execute(select(Layer).filter(Layer.name.ilike(name)))
    layer = result.scalars().first()
    return layer if layer else None

async def get_layers_by_symbol(db_session: AsyncSession, symbol: str) -> List[Layer]:
    result = await db_session.execute(
        select(Layer).filter(Layer.symbol.ilike(symbol))
    )
    return list(result.scalars().all())