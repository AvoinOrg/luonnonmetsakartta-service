from math import isnan
from geopandas import read_file
import numpy as np
from shapely.ops import transform
from shapely.geometry import Polygon, MultiPolygon
from geoalchemy2.shape import from_shape
from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.forest_layer import get_index_name_for_id
from app.db.models.forest_area import ForestArea
from app.db.models.forest_layer import ForestLayer

from app.utils.logger import get_logger

logger = get_logger(__name__)


def to_2d(geom):
    """Convert any geometry to 2D by dropping Z coordinates"""
    return transform(lambda x, y, z=None: (x, y), geom)


def clean_properties(props: dict) -> dict:
    cleaned = {}
    for key, value in props.items():
        if isinstance(value, float) and (isnan(value) or np.isnan(value)):
            cleaned[key] = None
        else:
            cleaned[key] = value
    return cleaned


async def import_shapefile_to_layer(
    db_session: AsyncSession,
    zip_path: str,
    layer_name: str,
    description: str | None = None,
) -> ForestLayer:
    """
    Import shapefile geometries into a new ForestLayer and ForestAreas.

    Args:
        db_session: Database session
        shapefile_path: Path to .shp file
        layer_name: Name for the new layer
        description: Optional layer description
    """
    try:
        # Read shapefile using geopandas
        gdf = read_file(zip_path)
        # Create new layer
        layer = ForestLayer(
            name=layer_name,
            description=description,
            original_properties={
                "crs": str(object=gdf.crs),
                "columns": list(gdf.columns),
            },
        )

        gdf = gdf.to_crs(epsg=3067)

        srid = gdf.crs.to_epsg()
        if not srid:
            raise ValueError(f"Could not extract EPSG code from CRS: {gdf.crs}")

        # Add and commit layer to get ID
        db_session.add(instance=layer)
        await db_session.commit()
        await db_session.refresh(instance=layer)

        # Create spatial index
        index_name: str = get_index_name_for_id(id=layer.id)
        create_index_sql: TextClause = text(
            text=f"""
            CREATE INDEX {index_name} 
            ON forest_area 
            USING GIST (geometry) 
            WHERE layer_id = '{layer.id}';
        """
        )
        await db_session.execute(statement=create_index_sql)

        # Process each geometry
        areas = []
        for idx, row in gdf.iterrows():
            geom = to_2d(row.geometry)
            props = row.to_dict()
            props.pop("geometry", None)

            name = props.pop("nimi", f"Area {idx + 1}")
            municipality = props.pop("kunta", "Unknown")
            region = props.pop("maakunta", "Unknown")
            area_ha = props.pop("ala_ha", 0)
            date = props.pop("paiva", None)

            area = ForestArea(
                layer_id=layer.id,
                name=name,
                municipality=municipality,
                region=region,
                area_ha=area_ha,
                date=date,
                geometry=from_shape(shape=geom, srid=srid),  # Handle any geometry type
                original_properties=props,
            )
            areas.append(area)

        # Bulk insert areas
        db_session.add_all(instances=areas)
        await db_session.commit()

        return layer

    except Exception as e:
        logger.error(e)
        await db_session.rollback()
        raise RuntimeError(f"Failed to import shapefile: {str(object=e)}") from e
