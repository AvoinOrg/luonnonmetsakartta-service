from math import isnan
import geopandas as gpd
import numpy as np
from shapely.ops import transform
from shapely.geometry import Polygon, MultiPolygon
from geoalchemy2.shape import from_shape
from sqlalchemy import TextClause, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.forest_area import (
    get_forest_areas_by_layer_id,
)
from app.db.forest_layer import get_forest_layer_by_id, get_index_name_for_id
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
    col_options: ColOptions,
    zip_path: str | None = None,
    delete_areas_not_updated: bool = False,
) -> None:
    """
    Read a shapefile (zip) and either update or insert ForestArea rows for the given forest layer.
    - The matching logic depends on the layer's indexing_strategy.
    - Existing records are updated.
    - New records are inserted.
    - If delete_areas_not_updated is True, any existing areas in the layer that are not
      found in the shapefile will be deleted.
    """
    # Verify the layer exists
    layer = await get_forest_layer_by_id(db_session, layer_id)
    if not layer or not layer.col_options:
        raise ValueError(f"Layer {layer_id} not found or is missing column options.")

    if not zip_path:
        return

    try:
        gdf = gpd.read_file(zip_path)
        if gdf is None:
            raise ValueError(f"Failed to read shapefile: {zip_path}")

        gdf = gdf.to_crs(epsg=3067)
        srid = gdf.crs.to_epsg() if gdf.crs else None
        if not srid:
            raise ValueError(f"Could not extract EPSG code from CRS: {gdf.crs}")

        existing_areas = await get_forest_areas_by_layer_id(db_session, layer_id)
        processed_area_ids = set()

        # Build a lookup dictionary from existing areas for faster matching
        existing_areas_dict = {}
        strategy = layer.col_options["indexing_strategy"]
        if strategy == "id":
            for area in existing_areas:
                if area.original_id:
                    existing_areas_dict[area.original_id] = area
        elif strategy == "name_municipality":
            for area in existing_areas:
                if area.name and area.municipality:
                    existing_areas_dict[(area.name, area.municipality)] = area

        for idx, row in gdf.iterrows():
            geom = to_2d(row.geometry)
            props = row.to_dict()
            props.pop("geometry", None)

            # Extract values based on provided column names
            name = (
                fix_encoding(props.pop(col_options.name_col, None))
                if col_options.name_col
                else None
            )
            municipality = (
                fix_encoding(props.pop(col_options.municipality_col, None))
                if col_options.municipality_col
                else None
            )
            original_id = (
                str(props.pop(col_options.id_col, None)) if col_options.id_col else None
            )

            # Find existing area based on strategy using the lookup dictionary
            existing_area = None
            if strategy == "id" and original_id:
                existing_area = existing_areas_dict.get(original_id)
            elif strategy == "name_municipality" and name and municipality:
                existing_area = existing_areas_dict.get((name, municipality))

            # Extract other optional values
            region = (
                fix_encoding(props.pop(col_options.region_col, None))
                if col_options.region_col
                else None
            )
            description_val = (
                fix_encoding(props.pop(col_options.description_col, None))
                if col_options.description_col
                else None
            )
            area_ha = (
                props.pop(col_options.area_col, None) if col_options.area_col else None
            )
            if area_ha is not None and isinstance(area_ha, float) and isnan(area_ha):
                area_ha = None
            if area_ha is None:
                area_ha = geom.area / 10000

            cleaned_props = clean_properties(props)

            if existing_area:
                # Update existing area, only if new value is not null
                if name is not None:
                    existing_area.name = name
                if description_val is not None:
                    existing_area.description = description_val
                if municipality is not None:
                    existing_area.municipality = municipality
                if region is not None:
                    existing_area.region = region
                if area_ha is not None:
                    existing_area.area_ha = area_ha
                existing_area.geometry = from_shape(geom, srid=srid)

                if existing_area.original_properties:
                    existing_area.original_properties.update(cleaned_props)
                else:
                    existing_area.original_properties = cleaned_props

                processed_area_ids.add(existing_area.id)
            else:
                # Create new area
                new_area = ForestArea(
                    layer_id=layer_id,
                    name=name or f"Area {idx}",
                    description=description_val,
                    municipality=municipality or "Unknown",
                    region=region or "Unknown",
                    area_ha=area_ha,
                    original_id=original_id,
                    geometry=from_shape(geom, srid=srid),
                    original_properties=cleaned_props,
                )
                db_session.add(new_area)

        if delete_areas_not_updated:
            id_to_area_map = {area.id: area for area in existing_areas}
            all_existing_ids = set(id_to_area_map.keys())
            ids_to_delete = all_existing_ids - processed_area_ids
            for area_id in ids_to_delete:
                await db_session.delete(id_to_area_map[area_id])

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

        # If the specified ID column is the index, reset it to be a regular column
        if (
            col_options.id_col
            and col_options.id_col not in gdf.columns
            and gdf.index.name
            and isinstance(gdf.index.name, str)
            and col_options.id_col.lower() == gdf.index.name.lower()
        ):
            gdf = gdf.reset_index()

        # Create new layer
        layer = ForestLayer(
            name=layer_name,
            description=description,
            is_hidden=is_hidden,
            color_code=color_code,
            col_options=col_options.model_dump(),
            original_properties={
                "crs": str(object=gdf.crs) if gdf.crs else None,
                "columns": list(gdf.columns),
            },
        )

        gdf = gdf.to_crs(epsg=3067)

        srid = gdf.crs.to_epsg() if gdf.crs else None
        if not srid:
            raise ValueError(f"Could not extract EPSG code from CRS: {gdf.crs}")

        # Add and commit layer to get ID
        db_session.add(instance=layer)
        await db_session.commit()
        await db_session.refresh(instance=layer)

        layer_id_str = str(layer.id).replace("-", "_")

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
            index_name_attr: str = (
                f"idx_forest_area_name_municipality_layer_{layer_id_str}"[:63]
            )
            create_attr_index_sql: TextClause = text(
                f"""
                CREATE UNIQUE INDEX {index_name_attr}
                ON forest_area (name, municipality)
                WHERE layer_id = '{layer.id}';
                """
            )
            await db_session.execute(statement=create_attr_index_sql)
        elif strategy == "id" and col_options.id_col:
            index_name_attr: str = f"idx_forest_area_original_id_layer_{layer_id_str}"[
                :63
            ]
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

            name = fix_encoding(props.pop(col_options.name_col, f"Area {str(idx)}"))
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
                if (
                    area_ha is not None
                    and isinstance(area_ha, float)
                    and isnan(area_ha)
                ):
                    area_ha = None

            if area_ha is None:
                area_ha = geom.area / 10000

            description_val = (
                fix_encoding(props.pop(col_options.description_col, None))
                if col_options.description_col
                else None
            )
            original_id_val = None
            if col_options.id_col:
                id_val = props.pop(col_options.id_col, None)
                if id_val is not None:
                    original_id_val = str(id_val)

            cleaned_props = clean_properties(props)

            area = ForestArea(
                layer_id=layer.id,
                name=name,
                description=description_val,
                municipality=municipality,
                region=region,
                area_ha=area_ha,
                original_id=original_id_val,
                geometry=from_shape(shape=geom, srid=srid),  # Handle any geometry type
                original_properties=cleaned_props,
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
