from contextlib import asynccontextmanager
import json
import shutil
import tempfile
from typing import Any
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
    set_layer_visibility,
)
from app.db.forest_area import get_forest_areas_by_layer_id

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
    description: str = Form(None),
    is_hidden: bool = Form(True),
    color_code: str = Form(default="#0000FF"),
    zip_file: UploadFile = File(...),
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
            areas = await get_forest_areas_by_layer_id(session, layer_id)

            # Convert to GeoJSON features
            features = []
            for area in areas:
                geom = area.geometry
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
                    "description": area.description
                    if hasattr(area, "description")
                    else None,
                    "municipality": area.municipality
                    if hasattr(area, "municipality")
                    else None,
                    "region": area.region if hasattr(area, "region") else None,
                    "area_ha": float(area.area_ha) if area.area_ha else None,
                    "date": area.date if hasattr(area, "date") else None,
                    "created_ts": int(area.created_ts.timestamp() * 1000)
                    if area.created_ts
                    else None,
                    "updated_ts": int(area.updated_ts.timestamp() * 1000)
                    if area.updated_ts
                    else None,
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


@app.get("/admin/validate")
async def validate_admin(
    editor_status=Depends(get_editor_status),
):
    if not editor_status.get("is_editor"):
        raise HTTPException(
            status_code=403, detail="User does not have admin or editor permission"
        )

    return {"is_editor": True}
