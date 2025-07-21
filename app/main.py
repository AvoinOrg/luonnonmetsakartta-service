from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import shutil
import tempfile
from typing import Any, Literal
from fastapi import Depends, UploadFile, File, Form, HTTPException
from uuid import UUID

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import geoalchemy2
from pydantic import BaseModel
import geopandas as gpd

from app import config
from app.auth.utils import get_editor_status_optional, get_editor_status
from app.utils.logger import get_logger
from app.db import connection
from app.utils.geometry import (
    import_shapefile_to_layer,
    update_layer_areas,
)
from app.db.forest_layer import (
    delete_forest_layer_by_id,
    get_all_forest_layers,
    get_forest_layer_by_id,
    update_forest_layer,
)
from app.api.geoserver import (
    create_geoserver_layers,
    delete_geoserver_layer,
    invalidate_geoserver_cache_for_feature,
    set_layer_visibility,
)
from app.db.forest_area import (
    get_forest_area_by_id,
    get_forest_areas_centroids_by_layer_id,
    get_forest_areas_by_layer_id,
    update_forest_area,
)
from app.types.general import ColOptions, IndexingStrategy

logger = get_logger(__name__)
global_settings = config.get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("starting up")
    yield
    print("shutting down")


app = FastAPI(lifespan=lifespan)

origins = [
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LayerResponsePublic(BaseModel):
    id: str
    name: str
    color_code: str | None = None
    description: str | None = None
    created_ts: int | None = None
    updated_ts: int | None = None


class LayerResponse(LayerResponsePublic):
    is_hidden: bool


@app.post(path="/layer")
async def create_layer(
    name: str = Form(...),
    description: str | None = Form(None),
    is_hidden: bool = Form(True),
    color_code: str = Form(default="#0000FF"),
    zip_file: UploadFile = File(...),
    indexing_strategy: str = Form(...),
    id_col: str | None = Form(None),
    name_col: str = Form(...),
    municipality_col: str = Form(...),
    region_col: str | None = Form(None),
    description_col: str | None = Form(None),
    area_col: str | None = Form(None),
    editor_status: dict = Depends(get_editor_status),
):
    # Create temporary directory
    if not editor_status.get("is_editor"):  # Check if user is editor
        raise HTTPException(
            status_code=403, detail="User does not have permission to create layers"
        )

    if not zip_file.filename:
        raise HTTPException(
            status_code=400, detail=f"Missing filename in main .shp file"
        )

    if indexing_strategy not in ["name_municipality", "id"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid indexing strategy: {indexing_strategy}. Must be 'name_municipality' or 'id'.",
        )

    try:
        indexing_strategy_val: IndexingStrategy = indexing_strategy  # type: ignore
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid indexing strategy: {indexing_strategy}. Must be 'name_municipality' or 'id'.",
        )

    col_options = ColOptions(
        indexingStrategy=indexing_strategy_val,
        idCol=id_col,
        nameCol=name_col,
        municipalityCol=municipality_col,
        regionCol=region_col,
        descriptionCol=description_col,
        areaCol=area_col,
    )

    layer_id = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".zip") as temp_file:
            shutil.copyfileobj(zip_file.file, temp_file)
            temp_file.flush()

            async with connection.get_async_context_db() as session:
                layer = await import_shapefile_to_layer(
                    session,
                    temp_file.name,
                    name,
                    col_options,
                    color_code=color_code,
                    description=description,
                    is_hidden=is_hidden,
                )
                layer_id = layer.id
                layer_name = f"layer_{layer.id}"
                await create_geoserver_layers(layer.id, layer_name, is_hidden=is_hidden)

                return LayerResponse(
                    id=str(layer.id),
                    name=layer.name,
                    description=layer.description,
                    is_hidden=layer.is_hidden,
                    color_code=layer.color_code,
                    created_ts=int(layer.created_ts.timestamp() * 1000),
                    updated_ts=int(layer.updated_ts.timestamp() * 1000),
                )

    except Exception as e:
        logger.error(e)

        # attempt cleanup
        if layer_id:
            try:
                await delete_geoserver_layer(layer_id)
            except Exception as e1:
                logger.error(f"Failed to delete GeoServer layer: {e1}")
                # Continue with database deletion even if GeoServer fails

            try:
                async with connection.get_async_context_db() as session:
                    await delete_forest_layer_by_id(session, str(layer_id))
            except Exception as e2:
                logger.error(f"Failed to delete layer from database: {e2}")

        raise HTTPException(
            status_code=400, detail=f"Failed to import shapefile: {str(e)}"
        )


@app.delete(path="/layer/{layer_id}")
async def delete_layer(layer_id: str, editor_status=Depends(get_editor_status)):
    """
    Delete a forest layer and its associated GeoServer layer.
    Returns 404 if layer not found, 500 if deletion fails.
    """
    if not editor_status.get("is_editor"):  # Check if user is editor
        raise HTTPException(
            status_code=403, detail="User does not have permission to delete layers"
        )

    try:
        async with connection.get_async_context_db() as session:
            # First check if layer exists
            layer = await get_forest_layer_by_id(session, str(layer_id))
            if not layer:
                raise HTTPException(
                    status_code=404, detail=f"Layer with id {layer_id} not found"
                )

            # Try to delete from both GeoServer and database
            try:
                await delete_geoserver_layer(layer_id)
            except Exception as e:
                logger.error(f"Failed to delete GeoServer layer: {e}")
                # Continue with database deletion even if GeoServer fails

            # Delete from database
            result = await delete_forest_layer_by_id(session, str(layer_id))
            if not result:
                raise HTTPException(status_code=500, detail="Database deletion failed")

            return {"message": f"Layer {layer_id} deleted successfully"}

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error deleting layer {layer_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete layer: {str(e)}")


@app.get(path="/layer/{layer_id}", response_model=LayerResponse | LayerResponsePublic)
async def get_layer(layer_id, editor_status=Depends(get_editor_status_optional)):
    try:
        async with connection.get_async_context_db() as session:
            layer = await get_forest_layer_by_id(session, id=layer_id)

            if not layer:
                raise HTTPException(
                    status_code=404, detail=f"Layer with id {layer_id} not found"
                )

            if not editor_status.get("is_editor") and layer.is_hidden:
                raise HTTPException(
                    status_code=403,
                    detail="User does not have permission to view layer",
                )

            if editor_status.get("is_editor"):
                return LayerResponse(
                    id=str(layer.id),
                    name=layer.name,
                    description=layer.description,
                    is_hidden=layer.is_hidden,
                    color_code=layer.color_code,
                    created_ts=int(layer.created_ts.timestamp() * 1000),
                    updated_ts=int(layer.updated_ts.timestamp() * 1000),
                )
            else:
                return LayerResponsePublic(
                    id=str(layer.id),
                    name=layer.name,
                    description=layer.description,
                    color_code=layer.color_code,
                    created_ts=int(layer.created_ts.timestamp() * 1000),
                    updated_ts=int(layer.updated_ts.timestamp() * 1000),
                )

    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch layers: {str(e)}")


@app.get(path="/layers", response_model=list[LayerResponse] | list[LayerResponsePublic])
async def get_layers(editor_status=Depends(get_editor_status_optional)):
    try:
        async with connection.get_async_context_db() as session:
            layers = await get_all_forest_layers(session)

            if not editor_status.get("is_editor"):
                layers = [layer for layer in layers if not layer.is_hidden]

            return_layers = []

            if editor_status.get("is_editor"):
                for layer in layers:
                    return_layers.append(
                        LayerResponse(
                            id=str(layer.id),
                            name=layer.name,
                            description=layer.description,
                            is_hidden=layer.is_hidden,
                            color_code=layer.color_code,
                            created_ts=int(layer.created_ts.timestamp() * 1000),
                            updated_ts=int(layer.updated_ts.timestamp() * 1000),
                        )
                    )
            else:
                for layer in layers:
                    return_layers.append(
                        LayerResponsePublic(
                            id=str(layer.id),
                            name=layer.name,
                            description=layer.description,
                            color_code=layer.color_code,
                            created_ts=int(layer.created_ts.timestamp() * 1000),
                            updated_ts=int(layer.updated_ts.timestamp() * 1000),
                        )
                    )

            return return_layers
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch layers: {str(e)}")


# TODO: for each updated area, invalidate the cache by bounding box.
@app.patch(path="/layer/{layer_id}")
async def update_layer(
    layer_id: UUID,
    name: str | None = Form(None),
    description: str | None = Form(None),
    zip_file: UploadFile | None = File(None),
    shapefile_id_col: str | None = Form(None),
    is_hidden: bool | None = Form(None),
    color_code: str | None = Form(None),
    overwrite_existing: bool = Form(False),
    editor_status=Depends(get_editor_status),
):
    if not editor_status.get("is_editor"):  # Check if user is editor
        raise HTTPException(
            status_code=403, detail="User does not have permission to update layers"
        )

    try:
        async with connection.get_async_context_db() as session:
            # Get existing layer
            layer = await get_forest_layer_by_id(session, str(layer_id))
            if not layer:
                raise HTTPException(
                    status_code=404, detail=f"Layer with id {layer_id} not found"
                )

            # Update metadata if provided
            if name:
                layer.name = name
            if description:
                layer.description = description
            if color_code:
                layer.color_code = color_code

            if is_hidden is not None:
                if layer.is_hidden == is_hidden:
                    logger.info(f"Layer {layer_id} already has is_hidden={is_hidden}")
                else:
                    result = await set_layer_visibility(layer_id, is_hidden=is_hidden)

                    if result:
                        layer.is_hidden = is_hidden
                    else:
                        raise HTTPException(
                            status_code=500,
                            detail=f"Failed to update layer visibility",
                        )

            # if shapefile_id_col is not None:
            # layer.shapefile_id_col = shapefile_id_col

            # Import new areas if shapefile provided
            if zip_file and zip_file.filename and shapefile_id_col:
                with tempfile.NamedTemporaryFile(suffix=".zip") as temp_file:
                    shutil.copyfileobj(zip_file.file, temp_file)
                    temp_file.flush()

                    await update_layer_areas(
                        session,
                        shapefile_id_col,
                        zip_path=temp_file.name,
                        overwrite_existing=overwrite_existing,
                    )

            # Update layer in database
            updated_layer = await update_forest_layer(session, layer)

            if not updated_layer:
                raise HTTPException(
                    status_code=500, detail=f"Failed to update layer metadata"
                )

            return {
                "id": str(updated_layer.id),
                "name": updated_layer.name,
                "description": updated_layer.description,
                "is_hidden": updated_layer.is_hidden,
                "color_code": updated_layer.color_code,
                "created_ts": int(layer.created_ts.timestamp() * 1000),
                "updated_ts": int(layer.updated_ts.timestamp() * 1000),
            }

    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=500, detail=f"Failed to update layer: {str(e)}")


class GeoJSONFeature(BaseModel):
    type: str = "Feature"
    id: str
    geometry: dict[str, Any]
    properties: dict[str, Any]


class GeoJSONFeatureCollection(BaseModel):
    type: str = "FeatureCollection"
    features: list[GeoJSONFeature]


@app.get(path="/layer/{layer_id}/areas")
async def get_areas_for_layer(
    layer_id: str, editor_status=Depends(get_editor_status_optional)
):
    """
    Fetch all areas (geometries) for a specific layer as a GeoJSON FeatureCollection.
    Regular users can only access areas from non-hidden layers.
    Editors can access all areas.
    """
    try:
        async with connection.get_async_context_db() as session:
            # First check if layer exists and if user has permission
            layer = await get_forest_layer_by_id(session, id=layer_id)

            if not layer:
                raise HTTPException(
                    status_code=404, detail=f"Layer with id {layer_id} not found"
                )

            if not editor_status.get("is_editor") and layer.is_hidden:
                raise HTTPException(
                    status_code=403,
                    detail="User does not have permission to view areas in this layer",
                )

            # Get all areas for this layer
            areas = await get_forest_areas_centroids_by_layer_id(
                session, layer_id, target_srid=4326
            )

            # Convert to GeoJSON features
            features = []
            for area in areas:
                geom: geoalchemy2.Geometry = area.centroid
                if geom:
                    # Convert WKBElement to Shapely geometry
                    shapely_geom = geoalchemy2.shape.to_shape(geom)
                    # Convert Shapely geometry to GeoJSON
                    geojson_dict = shapely_geom.__geo_interface__
                    geometry_json = geojson_dict
                else:
                    geometry_json = None

                properties = {
                    "id": str(area.id),
                    "layer_id": str(area.layer_id),
                    "name": area.name if hasattr(area, "name") else None,
                    "description": (
                        area.description if hasattr(area, "description") else None
                    ),
                    "municipality": (
                        area.municipality if hasattr(area, "municipality") else None
                    ),
                    "region": area.region if hasattr(area, "region") else None,
                    "area_ha": float(area.area_ha) if area.area_ha else None,
                    "date": area.date if hasattr(area, "date") else None,
                    "created_ts": (
                        int(area.created_ts.timestamp() * 1000)
                        if area.created_ts
                        else None
                    ),
                    "updated_ts": (
                        int(area.updated_ts.timestamp() * 1000)
                        if area.updated_ts
                        else None
                    ),
                }

                # Include original properties if available
                if hasattr(area, "original_properties") and area.original_properties:
                    properties.update(area.original_properties)

                # Include pictures if available
                if hasattr(area, "pictures") and area.pictures:
                    properties["pictures"] = area.pictures

                if geometry_json:  # Only add features with valid geometry
                    features.append(
                        GeoJSONFeature(
                            id=str(area.id),
                            geometry=geometry_json,
                            properties=properties,
                        )
                    )

            # Return as a GeoJSON FeatureCollection
            return GeoJSONFeatureCollection(features=features)

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch areas for layer {layer_id}: {str(e)}",
        )


@app.patch(path="/layer/{layer_id}/area/{feature_id}", response_model=GeoJSONFeature)
async def update_feature_in_layer(
    layer_id: UUID,
    feature_id: UUID,
    name: str | None = Form(None),
    description: str | None = Form(None),
    pictures_json: str | None = Form(
        None
    ),  # Expects a JSON string e.g. '["url1", "url2"]'
    municipality: str | None = Form(None),
    region: str | None = Form(None),
    area_ha: float | None = Form(None),
    date: str | None = Form(None),  # Ensure date is treated as a string
    owner: str | None = Form(None),
    person_responsible: str | None = Form(None),
    # geometry_geojson: str | None = Form(
    #     None
    # ),  # Expects a GeoJSON geometry string, e.g. '{"type": "Point", "coordinates": [25, 60]}'
    # original_properties_json: str | None = Form(
    #     None
    # ),  # Expects a JSON string for a dictionary e.g. '{"key": "value"}'
    editor_status: dict = Depends(get_editor_status),
):
    if not editor_status.get("is_editor"):
        raise HTTPException(
            status_code=403, detail="User does not have permission to update features"
        )

    async with connection.get_async_context_db() as session:
        area_to_update = await get_forest_area_by_id(session, str(feature_id))

        if not area_to_update:
            raise HTTPException(
                status_code=404, detail=f"Feature with id {feature_id} not found"
            )

        if str(area_to_update.layer_id) != str(layer_id):
            raise HTTPException(
                status_code=403,
                detail=f"Feature {feature_id} does not belong to layer {layer_id}",
            )

        updated_fields = False
        if name is not None:
            area_to_update.name = name
            updated_fields = True
        if description is not None:
            area_to_update.description = description  # Stored as JSON string in JSONB
            updated_fields = True
        if pictures_json is not None:
            try:
                area_to_update.pictures = json.loads(pictures_json)
                updated_fields = True
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=400, detail="Invalid JSON format for pictures"
                )
        if municipality is not None:
            area_to_update.municipality = municipality
            updated_fields = True
        if region is not None:
            area_to_update.region = region
            updated_fields = True
        if area_ha is not None:
            area_to_update.area_ha = area_ha
            updated_fields = True
        if date is not None:
            try:
                # Convert date to string if it's not already
                area_to_update.date = str(date)
                updated_fields = True
            except Exception as e:
                raise HTTPException(
                    status_code=400, detail=f"Invalid format for date: {str(e)}"
                )
        if owner is not None:
            area_to_update.owner = owner
            updated_fields = True
        if person_responsible is not None:
            area_to_update.person_responsible = person_responsible
            updated_fields = True
        # if original_properties_json is not None:
        #     try:
        #         area_to_update.original_properties = json.loads(
        #             original_properties_json
        #         )
        #         updated_fields = True
        #     except json.JSONDecodeError:
        #         raise HTTPException(
        #             status_code=400,
        #             detail="Invalid JSON format for original_properties",
        #         )

        # if geometry_geojson is not None:
        #     try:
        #         # Assumes input GeoJSON is EPSG:4326 and transforms to SRID 3067
        #         # ST_GeomFromGeoJSON expects the GeoJSON string directly.
        #         new_geometry = func.ST_Transform(
        #             func.ST_SetSRID(func.ST_GeomFromGeoJSON(geometry_geojson), 4326),
        #             3067,
        #         )
        #         area_to_update.geometry = new_geometry
        #         updated_fields = True
        #     except Exception as e:
        #         logger.error(
        #             f"Error processing geometry_geojson for feature {feature_id}: {e}"
        #         )
        #         raise HTTPException(
        #             status_code=400,
        #             detail=f"Invalid GeoJSON format or geometry error: {str(e)}",
        #         )

        if updated_fields:
            area_to_update.updated_ts = datetime.now(timezone.utc)
            updated_area_db = await update_forest_area(session, area_to_update)
            if not updated_area_db:
                # This case should ideally not be hit if update_forest_area raises on SQL error
                raise HTTPException(
                    status_code=500, detail="Failed to update feature in database"
                )
            try:
                await invalidate_geoserver_cache_for_feature(
                    layer_id_uuid=layer_id,  # FastAPI converts path param to UUID
                    feature_id_uuid=feature_id,  # FastAPI converts path param to UUID
                )
                logger.info(
                    f"GeoServer GWC cache invalidation request processed for feature {feature_id} in layer {layer_id}"
                )
            except Exception as e_cache:
                # Log error but don't fail the entire request if cache invalidation fails
                logger.error(
                    f"Failed to invalidate GeoServer GWC cache for feature {feature_id} in layer {layer_id}: {e_cache}"
                )
            final_area = updated_area_db
        else:
            final_area = area_to_update  # No changes made, return existing

        # Construct GeoJSONFeature response using the feature's centroid
        geometry_for_response_dict = {}
        # The centroid is computed and should be refreshed by update_forest_area
        if final_area.centroid is not None:
            try:
                shapely_geom = geoalchemy2.shape.to_shape(final_area.centroid)
                # Note: This geometry is in SRID 3067. GeoJSON typically implies WGS84 (4326).
                # For consistency with get_areas_for_layer, we don't transform it here.
                # Clients should be aware of the CRS or it should be specified in the GeoJSON's CRS member if needed.
                geometry_for_response_dict = shapely_geom.__geo_interface__
            except Exception as e:
                logger.error(
                    f"Error converting centroid to GeoJSON for feature {final_area.id}: {e}"
                )
                # Keep geometry_for_response_dict as {}

        properties = {
            "id": str(final_area.id),
            "layer_id": str(final_area.layer_id),
            "name": final_area.name,
            "description": final_area.description,
            "municipality": final_area.municipality,
            "region": final_area.region,
            "area_ha": (
                float(final_area.area_ha) if final_area.area_ha is not None else None
            ),
            "date": final_area.date,
            "owner": final_area.owner,
            "person_responsible": final_area.person_responsible,
            "created_ts": (
                int(final_area.created_ts.timestamp() * 1000)
                if final_area.created_ts
                else None
            ),
            "updated_ts": (
                int(final_area.updated_ts.timestamp() * 1000)
                if final_area.updated_ts
                else None
            ),
        }
        if final_area.pictures:
            properties["pictures"] = final_area.pictures
        if final_area.original_properties:
            # Ensure original_properties is a dict before updating
            if isinstance(final_area.original_properties, dict):
                properties.update(final_area.original_properties)
            else:  # Log if it's not a dict, though model expects dict
                logger.warning(
                    f"Feature {final_area.id} original_properties is not a dict: {type(final_area.original_properties)}"
                )

        return GeoJSONFeature(
            id=str(final_area.id),
            geometry=geometry_for_response_dict,  # Must be a dict
            properties=properties,
        )


@app.get("/admin/validate")
async def validate_admin(
    editor_status=Depends(get_editor_status),
):
    if not editor_status.get("is_editor"):
        raise HTTPException(
            status_code=403, detail="User does not have admin or editor permission"
        )

    return {"is_editor": True}
