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
from app.utils.general import fix_encoding
from app.types.general import ColOptions

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
            attr_lower_map = {k.lower(): k for k in attributes.keys()}
            shapefile_id_col_lower = (
                shapefile_id_col.lower() if shapefile_id_col else None
            )

            # --- Extract attributes case-insensitively ---
            def pop_case_insensitive(key_lower, default=None):
                original_key = attr_lower_map.get(key_lower)
                if original_key:
                    return attributes.pop(original_key, default)
                return default

            # Attempt to match existing forest_area by shapefile_id_col
            sf_id_val = (
                pop_case_insensitive(shapefile_id_col_lower)
                if shapefile_id_col_lower
                else None
            )
            name = pop_case_insensitive("nimi", f"UpdatedArea {idx + 1}")
            municipality = pop_case_insensitive("kunta", "Unknown")
            region = pop_case_insensitive("maakunta", "Unknown")
            area_ha = pop_case_insensitive("ala_ha", 0)
            owner = pop_case_insensitive("omistus")  # Assuming 'Omistus' might vary
            person_responsible = pop_case_insensitive("vastuuhkl")  # Assuming 'Omistus' might vary
            date = pop_case_insensitive("paiva")

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
                area_obj.owner = owner
                area_obj.person_responsible = person_responsible
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
    col_options: ColOptions,
    color_code: str,
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
            color_code=color_code,
            col_options=col_options.model_dump(),
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

        # Create attribute indexes based on indexing strategy
        strategy = col_options.indexing_strategy
        if strategy == "name_municipality":
            index_name_attr: str = f"idx_forest_area_name_municipality_layer_{layer.id.hex}"[:63]
            create_attr_index_sql: TextClause = text(
                f"""
                CREATE UNIQUE INDEX {index_name_attr}
                ON forest_area (name, municipality)
                WHERE layer_id = '{layer.id}';
                """
            )
            await db_session.execute(statement=create_attr_index_sql)
        elif strategy == "id" and col_options.id_col:
            index_name_attr: str = f"idx_forest_area_original_id_layer_{layer.id.hex}"[:63]
            create_attr_index_sql: TextClause = text(
                f"""
                CREATE INDEX {index_name_attr}
                ON forest_area (original_id)
                WHERE layer_id = '{layer.id}';
                """
            )
            await db_session.execute(statement=create_attr_index_sql)

        # Process each geometry
        areas = []
        for idx, row in gdf.iterrows():
            geom = to_2d(row.geometry)
            props = row.to_dict()
            props.pop("geometry", None)

            name = fix_encoding(props.pop(col_options.name_col, f"Area {idx + 1}"))
            municipality = fix_encoding(
                props.pop(col_options.municipality_col, "Unknown")
            )
            region = (
                fix_encoding(props.pop(col_options.region_col, "Unknown"))
                if col_options.region_col
                else "Unknown"
            )
            
            area_ha = None
            if col_options.area_col:
                area_ha = props.pop(col_options.area_col, None)

            if area_ha is None:
                area_ha = geom.area / 10000
            
            description_val = (
                fix_encoding(props.pop(col_options.description_col))
                if col_options.description_col
                else None
            )
            original_id_val = (
                props.pop(col_options.id_col) if col_options.id_col else None
            )

            area = ForestArea(
                layer_id=layer.id,
                name=name,
                description=description_val,
                municipality=municipality,
                region=region,
                area_ha=area_ha,
                original_id=original_id_val,
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
