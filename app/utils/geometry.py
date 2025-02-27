from math import isnan
import geopandas as gpd
import numpy as np
from shapely.ops import transform
from shapely.geometry import Polygon, MultiPolygon
from geoalchemy2.shape import from_shape
from sqlalchemy import TextClause, select, text
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


async def update_layer_areas(
    db_session: AsyncSession,
    layer_id: str,
    shapefile_id_col: str | None = None,
    zip_path: str | None = None,
    overwrite_existing: bool = False,
) -> None:
    """
    Read a shapefile (zip) and either update or insert ForestArea rows for the given forest layer.
    If overwrite_existing is True, any matching areas (by shapefile_id_col in original_properties)
    get overwritten. Non-matching areas get inserted.
    """
    # Verify the layer exists
    layer_stmt = select(ForestLayer).filter_by(id=layer_id)
    layer_result = await db_session.execute(layer_stmt)
    layer_obj = layer_result.scalar_one_or_none()
    if not layer_obj:
        raise ValueError(f"Layer {layer_id} not found.")

    # If no shapefile provided, nothing to update
    if not zip_path:
        return

    try:
        # Read the shapefile
        gdf = gpd.read_file(zip_path)
        if gdf is None:
            raise ValueError(f"Failed to read shapefile: {zip_path}")

        # Reproject to EPSG:3067
        gdf = gdf.to_crs(epsg=3067)
        srid = gdf.crs.to_epsg()
        if not srid:
            raise ValueError(f"Could not extract EPSG code from CRS: {gdf.crs}")

        # Fetch existing areas in this layer
        existing_areas_stmt = select(ForestArea).filter_by(layer_id=layer_id)
        existing_areas_result = await db_session.execute(existing_areas_stmt)
        existing_areas = existing_areas_result.scalars().all()

        # Build a dict keyed by shapefile ID
        existing_dict = {}
        for area in existing_areas:
            props = area.original_properties or {}
            existing_sf_id = props.get(shapefile_id_col)
            if existing_sf_id is not None:
                existing_dict[existing_sf_id] = area

        # Iterate over all features in the shapefile
        for idx, row in gdf.iterrows():
            geom = to_2d(row.geometry)
            attributes = row.to_dict()
            attributes.pop("geometry", None)  # geometry handled separately

            # Attempt to match existing forest_area by shapefile_id_col
            sf_id_val = attributes.get(shapefile_id_col)
            name = attributes.pop("nimi", f"UpdatedArea {idx + 1}")
            municipality = attributes.pop("kunta", "Unknown")
            region = attributes.pop("maakunta", "Unknown")
            area_ha = attributes.pop("ala_ha", 0)
            date = attributes.pop("paiva", None)

            merged_props = clean_properties(attributes)
            if sf_id_val:
                merged_props[shapefile_id_col] = sf_id_val

            # Overwrite existing or insert new
            if sf_id_val in existing_dict and overwrite_existing:
                # Update existing area
                area_obj = existing_dict[sf_id_val]
                area_obj.name = name
                area_obj.municipality = municipality
                area_obj.region = region
                area_obj.area_ha = area_ha
                area_obj.date = date
                area_obj.geometry = f"SRID={srid};{geom.wkt}"  # GeoAlchemy2-compatible
                area_obj.original_properties = {
                    **(area_obj.original_properties or {}),
                    **merged_props,
                }
            elif sf_id_val not in existing_dict:
                # Create new area
                new_area = ForestArea(
                    layer_id=layer_id,
                    name=name,
                    municipality=municipality,
                    region=region,
                    area_ha=area_ha,
                    date=date,
                    geometry=f"SRID={srid};{geom.wkt}",
                    original_properties=merged_props,
                )
                db_session.add(new_area)

        await db_session.commit()

    except Exception as e:
        logger.error(f"Error updating areas for layer {layer_id}: {e}")
        await db_session.rollback()
        raise


async def import_shapefile_to_layer(
    db_session: AsyncSession,
    zip_path: str,
    layer_name: str,
    description: str | None = None,
    is_hidden: bool = True,
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
        gdf = gpd.read_file(zip_path)
        if gdf is None:
            raise ValueError(f"Failed to read shapefile: {zip_path}")

        # Create new layer
        layer = ForestLayer(
            name=layer_name,
            description=description,
            is_hidden=is_hidden,
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
