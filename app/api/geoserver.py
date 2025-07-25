import json
import httpx
from typing import Optional
from sqlalchemy.sql import text
from uuid import UUID
from app.config import get_settings
from app.db import connection
from app.utils.logger import get_logger

global_settings = get_settings()
logger = get_logger(__name__)

geoserver_url = global_settings.geoserver_url
geoserver_workspace = global_settings.geoserver_workspace
geoserver_store = global_settings.geoserver_store
username = global_settings.geoserver_user
password = global_settings.geoserver_password


def get_layer_name_for_id(layer_id: str | UUID) -> str:
    layer_id_str = str(layer_id)
    sanitized_id = layer_id_str.replace("-", "")
    return f"forest_areas_{sanitized_id}"


def get_layer_centroid_name_for_id(layer_id: str | UUID) -> str:
    layer_id_str = str(layer_id)
    sanitized_id = layer_id_str.replace("-", "")
    return f"forest_areas_{sanitized_id}_centroid"


async def get_layer_bounds(layer_id: str | UUID) -> dict:
    """Calculate the bounding box for a layer in both native SRS and lat/lon."""
    async with connection.get_async_context_db() as session:
        # Get bounds in native SRS (EPSG:3067)
        native_bounds_sql = """
            SELECT 
                ST_XMin(ST_Extent(geometry)) as minx,
                ST_XMax(ST_Extent(geometry)) as maxx, 
                ST_YMin(ST_Extent(geometry)) as miny,
                ST_YMax(ST_Extent(geometry)) as maxy
            FROM forest_area 
            WHERE layer_id = :layer_id
        """

        # Get bounds in WGS84 (EPSG:4326)
        lonlat_bounds_sql = """
            SELECT 
                ST_XMin(ST_Extent(ST_Transform(geometry, 4326))) as lon_minx,
                ST_XMax(ST_Extent(ST_Transform(geometry, 4326))) as lon_maxx,
                ST_YMin(ST_Extent(ST_Transform(geometry, 4326))) as lon_miny,
                ST_YMax(ST_Extent(ST_Transform(geometry, 4326))) as lon_maxy
            FROM forest_area 
            WHERE layer_id = :layer_id
        """

        # Execute native bounds query
        result = await session.execute(text(native_bounds_sql), {"layer_id": layer_id})
        native_bounds = result.mappings().first()

        # Execute lat/lon bounds query
        result = await session.execute(text(lonlat_bounds_sql), {"layer_id": layer_id})
        lonlat_bounds = result.mappings().first()

        # Combine results
        bounds = {**native_bounds, **lonlat_bounds}

        # Provide default bounds if no data exists
        if bounds["minx"] is None:
            # Default bounds for Finland in EPSG:3067
            bounds = {
                "minx": 50000,
                "maxx": 750000,
                "miny": 6600000,
                "maxy": 7800000,
                "lon_minx": 19.0,
                "lon_maxx": 32.0,
                "lon_miny": 59.5,
                "lon_maxy": 70.0,
            }

        return bounds


async def create_geoserver_layers(
    forest_layer_id: str,
    forest_layer_name: str,
    is_hidden: bool = True,
) -> dict:
    """
    Create both the main area layer and its associated centroid layer in GeoServer.

    This is a convenience function that creates both layers in a single operation
    and handles error scenarios appropriately.

    Args:
        forest_layer_id: UUID of the forest layer
        forest_layer_name: Display name for the forest layer
        is_hidden: Whether the layers should be hidden from non-editors

    Returns:
        Dictionary with status of both layer creations
    """
    logger.info(f"Creating GeoServer layers for forest_layer_id: {forest_layer_id}")

    # Track results for both operations
    results = {
        "area_layer": {"success": False, "message": "Not attempted"},
        "centroid_layer": {"success": False, "message": "Not attempted"},
    }

    # Step 1: Create the main area layer
    try:
        area_layer_created = await create_geoserver_layer(
            forest_layer_id=forest_layer_id,
            forest_layer_name=forest_layer_name,
            is_hidden=is_hidden,
        )
        results["area_layer"]["success"] = True
        results["area_layer"]["message"] = "Successfully created area layer"
        logger.info(f"Successfully created area layer for {forest_layer_id}")

    except Exception as e:
        error_msg = f"Failed to create area layer: {str(e)}"
        results["area_layer"]["message"] = error_msg
        logger.error(error_msg)
        # Don't proceed with centroid layer if area layer failed
        return results

    # Step 2: Create the centroid layer
    try:
        centroid_layer_created = await create_geoserver_centroid_layer(
            forest_layer_id=forest_layer_id,
            forest_layer_name=forest_layer_name,
            is_hidden=is_hidden,
        )
        results["centroid_layer"]["success"] = True
        results["centroid_layer"]["message"] = "Successfully created centroid layer"
        logger.info(f"Successfully created centroid layer for {forest_layer_id}")

    except Exception as e:
        error_msg = f"Failed to create centroid layer: {str(e)}"
        results["centroid_layer"]["message"] = error_msg
        logger.error(error_msg)

        # The area layer was created but the centroid layer failed
        # Depending on your requirements, you might want to:
        # 1. Leave the area layer (current behavior)
        # 2. Delete the area layer to maintain consistency
        #
        # If you want to delete the area layer when centroid fails, uncomment:
        # try:
        #     await delete_geoserver_layer(forest_layer_id)
        #     results["area_layer"]["message"] += " (but was deleted because centroid layer failed)"
        #     results["area_layer"]["success"] = False
        # except Exception as cleanup_error:
        #     logger.error(f"Error cleaning up area layer: {str(cleanup_error)}")

    # Return combined results
    return results


async def create_geoserver_layer(
    forest_layer_id: str,
    forest_layer_name: str,
    is_hidden: bool = True,
) -> bool:
    """Create GeoServer layer for forest areas with given layer_id."""

    # Calculate bounds from the database first
    # bounds = await get_layer_bounds(forest_layer_id)

    # SQL view parameters
    view_name = get_layer_name_for_id(layer_id=forest_layer_id)
    sql_view = f"""
        CREATE OR REPLACE VIEW {view_name} AS
        SELECT 
            id,
            name,
            geometry
        FROM forest_area 
        WHERE layer_id::text = '{str(forest_layer_id)}'
    """

    # Step 1: Create a database view
    async with connection.get_async_context_db() as session:
        try:
            await session.execute(text(sql_view))
            await session.commit()
            logger.info(f"Created database view: {view_name}")
        except Exception as e:
            logger.error(f"Failed to create database view: {str(e)}")
            raise Exception(f"View creation failed: {str(e)}")

    # Layer configuration
    layer_config = {
        "featureType": {
            "name": view_name,
            "nativeName": view_name,
            "title": f"{forest_layer_id} - Areas",
            "abstract": "Forest areas filtered by layer ID",
            "srs": "EPSG:3067",
            "projectionPolicy": "FORCE_DECLARED",
            "enabled": True,
            "advertised": True,
            "store": {
                "@class": "dataStore",
                "name": f"{geoserver_workspace}:{geoserver_store}",
            },
            # "virtualTable": {
            #     "name": view_name,
            #     "sql": sql_view,
            #     "geometry": {"name": "geometry", "type": "Geometry", "srid": 3067},
            #     "parameters": [],
            # },
            "defaultStyle": {
                "name": "polygon"  # or whatever style name you want to use
            },
            # "attributes": {
            #     "attribute": [
            #         {"name": "id", "binding": "java.lang.String"},
            #         {"name": "created_ts", "binding": "java.sql.Timestamp"},
            #         {"name": "updated_ts", "binding": "java.sql.Timestamp"},
            #         {"name": "name", "binding": "java.lang.String"},
            #         {
            #             "name": "description",
            #             "binding": "java.lang.String",
            #         },
            #         {
            #             "name": "pictures",
            #             "binding": "java.lang.String",
            #         },
            #         {"name": "municipality", "binding": "java.lang.String"},
            #         {"name": "region", "binding": "java.lang.String"},
            #         {"name": "area_ha", "binding": "java.lang.Double"},
            #         {"name": "date", "binding": "java.lang.String"},
            #         {
            #             "name": "geometry",
            #             "binding": "org.locationtech.jts.geom.Geometry",
            #         },
            #     ]
            # },
            "nativeBoundingBox": {
                "minx": 144286.33218675363,
                "maxx": 752934.2155768903,
                "miny": 6642928.395443255,
                "maxy": 7796732.440183549,
                "crs": "EPSG:3067",
            },
            # Finland in WGS84
            "latLonBoundingBox": {
                "minx": 20.6455928891,
                "maxx": 31.5160921567,
                "miny": 59.846373196,
                "maxy": 70.1641930203,
                "crs": "EPSG:4326",
            },
            # "nativeBoundingBox": {
            #     "minx": bounds["minx"],
            #     "maxx": bounds["maxx"],
            #     "miny": bounds["miny"],
            #     "maxy": bounds["maxy"],
            #     "crs": "EPSG:3067",
            # },
            # "latLonBoundingBox": {
            #     "minx": bounds["lon_minx"],
            #     "maxx": bounds["lon_maxx"],
            #     "miny": bounds["lon_miny"],
            #     "maxy": bounds["lon_maxy"],
            #     "crs": "EPSG:4326",
            # },
        }
    }

    # Rest of your function remains the same
    async with httpx.AsyncClient() as client:
        # Create new feature type
        response = await client.post(
            f"{geoserver_url}/rest/workspaces/{geoserver_workspace}/datastores/{geoserver_store}/featuretypes",
            json=layer_config,
            auth=(username, password),
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 201:
            await _set_single_layer_visibility(
                layer_name=view_name, is_hidden=is_hidden, is_initial_rule=True
            )
            return True
        else:
            raise Exception(f"Failed to create layer: {response.text}")


async def create_geoserver_centroid_layer(
    forest_layer_id: str,
    forest_layer_name: str,
    is_hidden: bool = True,
) -> bool:
    """
    Create GeoServer centroid layer for forest areas with given layer_id.
    This creates a lightweight point layer showing only centroids.
    """
    # Generate view name with _centroid suffix
    view_name = get_layer_centroid_name_for_id(layer_id=forest_layer_id)

    logger.info(f"Creating centroid layer for layer ID: {forest_layer_id}")

    # SQL to create view with just id, name, and centroid
    sql_view = f"""
        CREATE OR REPLACE VIEW {view_name} AS
        SELECT 
            id,
            name,
            created_ts,
            updated_ts,
            description,
            pictures,
            municipality,
            region,
            area_ha,
            date,
            centroid AS geometry
        FROM forest_area 
        WHERE layer_id::text = '{str(forest_layer_id)}'
        AND centroid IS NOT NULL
    """

    # Step 1: Create a database view
    async with connection.get_async_context_db() as session:
        try:
            await session.execute(text(sql_view))
            await session.commit()
            logger.info(f"Created centroid database view: {view_name}")

            # Count rows to confirm data exists
            count_result = await session.execute(
                text(f"SELECT COUNT(*) FROM {view_name}")
            )
            count = count_result.scalar()
            logger.info(f"Centroid view contains {count} points")

        except Exception as e:
            logger.error(f"Failed to create centroid database view: {str(e)}")
            raise Exception(f"Centroid view creation failed: {str(e)}")

    # Layer configuration - simplified for point data
    layer_config = {
        "featureType": {
            "name": view_name,
            "nativeName": view_name,
            "title": f"{forest_layer_id} - Centroids",
            "abstract": "Forest area centroids filtered by layer ID",
            "srs": "EPSG:3067",
            "projectionPolicy": "FORCE_DECLARED",
            "enabled": True,
            "advertised": True,
            "store": {
                "@class": "dataStore",
                "name": f"{geoserver_workspace}:{geoserver_store}",
            },
            "defaultStyle": {"name": "point"},  # Use appropriate point style
            "attributes": {
                "attribute": [
                    {"name": "id", "binding": "java.lang.String"},
                    {"name": "name", "binding": "java.lang.String"},
                    {"name": "created_ts", "binding": "java.sql.Timestamp"},
                    {"name": "updated_ts", "binding": "java.sql.Timestamp"},
                    {"name": "description", "binding": "java.lang.String"},
                    {"name": "pictures", "binding": "java.lang.String"},
                    {"name": "municipality", "binding": "java.lang.String"},
                    {"name": "region", "binding": "java.lang.String"},
                    {"name": "area_ha", "binding": "java.lang.Double"},
                    {"name": "date", "binding": "java.lang.String"},
                    {"name": "geometry", "binding": "org.locationtech.jts.geom.Point"},
                ]
            },
            "nativeBoundingBox": {
                "minx": 144286.33218675363,
                "maxx": 752934.2155768903,
                "miny": 6642928.395443255,
                "maxy": 7796732.440183549,
                "crs": "EPSG:3067",
            },
            "latLonBoundingBox": {
                "minx": 20.6455928891,
                "maxx": 31.5160921567,
                "miny": 59.846373196,
                "maxy": 70.1641930203,
                "crs": "EPSG:4326",
            },
        }
    }

    # Create the layer in GeoServer
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{geoserver_url}/rest/workspaces/{geoserver_workspace}/datastores/{geoserver_store}/featuretypes",
            json=layer_config,
            auth=(username, password),
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 201:
            # Set the same visibility rules as the main layer
            await _set_single_layer_visibility(
                layer_name=view_name, is_hidden=is_hidden, is_initial_rule=True
            )
            logger.info(f"Successfully created centroid layer: {view_name}")
            return True
        else:
            # Clean up view if GeoServer layer creation fails
            async with connection.get_async_context_db() as session:
                await session.execute(text(f"DROP VIEW IF EXISTS {view_name}"))
                await session.commit()

            raise Exception(f"Failed to create centroid layer: {response.text}")


async def delete_geoserver_layer(forest_layer_id: str | UUID) -> bool:
    """
    Delete both the main area layer and its associated centroid layer from GeoServer,
    along with their database views.
    """
    # Get names for both layers
    area_view_name = get_layer_name_for_id(layer_id=forest_layer_id)
    centroid_view_name = get_layer_centroid_name_for_id(layer_id=forest_layer_id)

    logger.info(f"Deleting GeoServer layers for forest_layer_id: {forest_layer_id}")
    logger.info(f"Area layer: {area_view_name}, Centroid layer: {centroid_view_name}")

    # Track success for both operations
    area_deleted = False
    centroid_deleted = False

    async with httpx.AsyncClient() as client:
        # 1. Delete the main area layer
        area_delete_url = f"{geoserver_url}/rest/workspaces/{geoserver_workspace}/datastores/{geoserver_store}/featuretypes/{area_view_name}?recurse=true"
        area_resp = await client.delete(
            area_delete_url,
            auth=(username, password),
            headers={"Content-Type": "application/json"},
        )
        area_deleted = area_resp.status_code == 200

        if not area_deleted:
            logger.warning(
                f"Failed to delete area layer: ({area_resp.status_code}) {area_resp.text}"
            )

        # 2. Delete the centroid layer
        centroid_delete_url = f"{geoserver_url}/rest/workspaces/{geoserver_workspace}/datastores/{geoserver_store}/featuretypes/{centroid_view_name}?recurse=true"
        centroid_resp = await client.delete(
            centroid_delete_url,
            auth=(username, password),
            headers={"Content-Type": "application/json"},
        )
        centroid_deleted = centroid_resp.status_code == 200

        if not centroid_deleted:
            logger.warning(
                f"Failed to delete centroid layer: ({centroid_resp.status_code}) {centroid_resp.text}"
            )

        permissions_deleted = await delete_layer_permissions(view_name=area_view_name)
        if not permissions_deleted:
            logger.warning(f"Failed to delete permissions for layer: {area_view_name}")

        permissions_deleted = await delete_layer_permissions(
            view_name=centroid_view_name
        )
        if not permissions_deleted:
            logger.warning(
                f"Failed to delete permissions for layer: {centroid_view_name}"
            )

    # 3. Clean up database views regardless of GeoServer result
    async with connection.get_async_context_db() as session:
        try:
            # Drop both views (using CASCADE to handle dependencies)
            await session.execute(
                text(f'DROP VIEW IF EXISTS "{area_view_name}" CASCADE')
            )
            await session.execute(
                text(f'DROP VIEW IF EXISTS "{centroid_view_name}" CASCADE')
            )
            await session.commit()
            logger.info(
                f"Dropped database views: {area_view_name}, {centroid_view_name}"
            )
        except Exception as e:
            logger.error(f"Error dropping database views: {str(e)}")

    # Consider the operation successful if at least the main layer was deleted
    if not area_deleted and not centroid_deleted and not permissions_deleted:
        raise Exception(f"Failed to delete main area layer from GeoServer")

    return True


async def get_layer_permissions(layer_id: str | UUID) -> dict:
    async with httpx.AsyncClient() as client:
        layer_name = get_layer_name_for_id(layer_id=layer_id)
        security_url = f"{geoserver_url}/rest/security/acl/layers/"
        get_response = await client.get(
            security_url,
            auth=(username, password),
            headers={"Content-Type": "application/json"},
        )

        all_rules = get_response.json()
        # For example, workspace.layerName
        prefix = f"{geoserver_workspace}.{layer_name}."
        # Extract only matching ACL entries
        matching_rules = {k: v for k, v in all_rules.items() if k.startswith(prefix)}

        return matching_rules


async def delete_layer_permissions(view_name: str) -> bool:
    """
    Deletes security rules associated with a GeoServer layer.
    Assumes rules are identified like {workspace}.{layer_name}.r,
    {workspace}.{layer_name}.w, and {workspace}.{layer_name}.a.
    """
    if not geoserver_workspace:
        logger.error(
            "GeoServer workspace is not configured. Cannot delete permissions."
        )
        return False

    rule_ids_to_delete = [
        f"{geoserver_workspace}.{view_name}.r",  # Read rule
        f"{geoserver_workspace}.{view_name}.w",  # Write rule
        f"{geoserver_workspace}.{view_name}.a",  # Admin rule
    ]

    all_rules_handled_successfully = True
    async with httpx.AsyncClient(auth=(username, password)) as client:
        for rule_id in rule_ids_to_delete:
            delete_url = f"{geoserver_url}/rest/security/rules/{rule_id}"
            try:
                response = await client.delete(delete_url)
                if response.status_code == 200:
                    pass
                    # logger.debug(
                    #     msg=f"Successfully deleted GeoServer security rule: {rule_id}"
                    # )
                elif response.status_code == 404:
                    pass
                    # logger.debug(
                    #     f"GeoServer security rule not found (considered success as it doesn't exist): {rule_id}"
                    # )
                else:
                    logger.error(
                        f"Failed to delete GeoServer security rule {rule_id}: {response.status_code} - {response.text}"
                    )
                    all_rules_handled_successfully = False
            except httpx.RequestError as e:
                logger.error(
                    f"HTTP request error deleting GeoServer security rule {rule_id}: {e}"
                )
                all_rules_handled_successfully = False
    return all_rules_handled_successfully


async def set_layer_visibility(
    layer_id: str | UUID,
    is_hidden: bool,
    is_initial_rule: bool = False,
    custom_layer_name: Optional[str] = None,
) -> bool:
    """
    Set visibility permissions for both the main area layer and its centroid layer.

    Args:
        layer_id: The forest layer ID
        is_hidden: Whether layers should be hidden from non-editors
        is_initial_rule: Whether this is the first rule setup for the layers
        custom_layer_name: Optional override for the layer name
    """
    # If custom layer name is provided, use it directly
    if custom_layer_name:
        # Set permissions for just the specified layer
        result = await _set_single_layer_visibility(
            layer_name=custom_layer_name,
            is_hidden=is_hidden,
            is_initial_rule=is_initial_rule,
        )
        return result

    # Otherwise, set permissions for both the area and centroid layers
    area_layer_name = get_layer_name_for_id(layer_id=layer_id)
    centroid_layer_name = get_layer_centroid_name_for_id(layer_id=layer_id)

    # Set permissions for the main area layer
    area_result = await _set_single_layer_visibility(
        layer_name=area_layer_name, is_hidden=is_hidden, is_initial_rule=is_initial_rule
    )

    # Set the same permissions for the centroid layer
    centroid_result = await _set_single_layer_visibility(
        layer_name=centroid_layer_name,
        is_hidden=is_hidden,
        is_initial_rule=is_initial_rule,
    )

    # Both operations need to succeed
    return area_result and centroid_result


async def _set_single_layer_visibility(
    layer_name: str, is_hidden: bool, is_initial_rule: bool = False
) -> bool:
    """
    Helper function to set visibility for a single layer.

    Args:
        layer_name: The exact layer in GeoServer
        is_hidden: Whether layer should be hidden from non-editors
        is_initial_rule: Whether this is the first rule setup
    """
    # Base prefix for layer rules
    layer_prefix = f"{geoserver_workspace}.{layer_name}"

    # Define rule keys
    rule_key_read = f"{layer_prefix}.r"  # read rule
    rule_key_write = f"{layer_prefix}.w"  # write rule

    # Define permissions for different roles
    # Admins and service accounts always get full permissions
    write_roles = ["ADMIN", "LUONNONMETSAKARTTA_SERVICE"]
    write_permissions = ",".join(write_roles)

    # Users always get read permissions
    read_roles = ["LUONNONMETSAKARTTA_USER"]

    # Add public roles if not hidden
    if not is_hidden:
        read_roles.extend(["ROLE_AUTHENTICATED", "ROLE_ANONYMOUS"])

    # Combine with admin roles for read permissions
    read_permissions = ",".join(read_roles + write_roles)

    # Build the rules
    json_data = {
        rule_key_read: read_permissions,  # Read permissions
        rule_key_write: write_permissions,  # Write permissions
    }

    async with httpx.AsyncClient() as client:
        security_url = f"{geoserver_url}/rest/security/acl/layers/"
        method = client.put if not is_initial_rule else client.post

        response = await method(
            security_url,
            auth=(username, password),
            headers={"Content-Type": "application/json"},
            json=json_data,
        )

        if response.status_code in (200, 201):
            logger.info(f"Set visibility for layer {layer_name}: hidden={is_hidden}")
            return True
        else:
            logger.error(
                f"Failed to set visibility for layer {layer_name}. Status: {response.status_code}, Response: {response.text}"
            )
            return False


async def invalidate_geoserver_cache_by_bbox(
    layer_id_uuid: UUID,
    bounds_3067: tuple[float, float, float, float],
):
    """
    Invalidates GeoServer GWC tile cache for a given bounding box.
    It transforms the bbox to EPSG:3857 and clears tiles for EPSG:900913 gridset.
    """
    logger.info(
        f"Attempting to invalidate GeoServer cache for layer {layer_id_uuid} using bbox {bounds_3067}"
    )

    bounds_3857 = None

    # Transform bounding box from EPSG:3067 to EPSG:3857
    async with connection.get_async_context_db() as session:
        stmt = text(
            """
            SELECT
                ST_XMin(ST_Transform(ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 3067), 3857)) as minx_3857,
                ST_YMin(ST_Transform(ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 3067), 3857)) as miny_3857,
                ST_XMax(ST_Transform(ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 3067), 3857)) as maxx_3857,
                ST_YMax(ST_Transform(ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 3067), 3857)) as maxy_3857
            """
        )
        result = await session.execute(
            stmt,
            {
                "minx": bounds_3067[0],
                "miny": bounds_3067[1],
                "maxx": bounds_3067[2],
                "maxy": bounds_3067[3],
            },
        )
        bounds_data = result.mappings().first()

        if bounds_data and not any(bounds_data[k] is None for k in bounds_data.keys()):
            bounds_3857 = (
                bounds_data["minx_3857"],
                bounds_data["miny_3857"],
                bounds_data["maxx_3857"],
                bounds_data["maxy_3857"],
            )

    if not bounds_3857:
        logger.warning(
            f"Could not transform bounds for layer {layer_id_uuid}. Skipping GeoServer cache invalidation."
        )
        return

    area_layer_raw_name = get_layer_name_for_id(layer_id_uuid)
    centroid_layer_raw_name = get_layer_centroid_name_for_id(layer_id_uuid)
    tile_format = "application/vnd.mapbox-vector-tile"
    gridset_id = "EPSG:900913"
    srs_code = 3857

    for layer_raw_name in [area_layer_raw_name, centroid_layer_raw_name]:
        logger.info(
            f"Requesting GWC truncation for layer {geoserver_workspace}:{layer_raw_name}, "
            f"gridset {gridset_id}, bounds (SRS {srs_code}): {bounds_3857}"
        )
        await _truncate_gwc_tiles_for_gridset(
            raw_layer_name=layer_raw_name,
            bounds_coords=bounds_3857,
            bounds_srs_code=srs_code,
            gridset_id_to_truncate=gridset_id,
            tile_format=tile_format,
        )


async def _truncate_gwc_tiles_for_gridset(
    raw_layer_name: str,
    bounds_coords: tuple[float, float, float, float],
    bounds_srs_code: int,
    gridset_id_to_truncate: str,
    tile_format: str = "application/vnd.mapbox-vector-tile",
) -> bool:
    """
    Sends a request to GWC to truncate tiles for a given layer, bounds, and gridset.
    """
    if not geoserver_workspace:
        logger.error("GeoServer workspace not configured. Cannot truncate GWC tiles.")
        return False

    # Validate bounding box values
    if any(coord is None for coord in bounds_coords):
        logger.error(
            f"Invalid bounding box values for truncation: {bounds_coords}. Skipping request."
        )
        return False

    full_layer_name = f"{geoserver_workspace}:{raw_layer_name}"
    # GeoWebCache seed/truncate URL structure
    gwc_seed_url = f"{geoserver_url}/gwc/rest/seed/{full_layer_name}.json"

    payload = {
        "seedRequest": {
            "name": full_layer_name,
            "coords": {
                "bounds": {
                    "minx": bounds_coords[0],
                    "miny": bounds_coords[1],
                    "maxx": bounds_coords[2],
                    "maxy": bounds_coords[3],
                }
            },
            "srs": {"number": bounds_srs_code},
            "gridSetId": gridset_id_to_truncate,
            "type": "truncate",
            "threadCount": 1,
            "format": tile_format,
            "zoomStart": 0,
            "zoomStop": 20,
        }
    }

    logger.debug(f"Payload for GWC truncation: {json.dumps(payload, indent=2)}")

    async with httpx.AsyncClient(auth=(username, password)) as client:
        try:
            response = await client.post(gwc_seed_url, json=payload)
            if response.status_code in [200, 202]:
                logger.info(
                    f"GWC tile truncation successfully requested for {full_layer_name}, "
                    f"gridset {gridset_id_to_truncate}, bounds (SRS {bounds_srs_code}): {bounds_coords}"
                )
                return True
            else:
                logger.error(
                    f"Failed to truncate GWC tiles for {full_layer_name}, gridset {gridset_id_to_truncate}. "
                    f"Status: {response.status_code}, Response: {response.text}"
                )
                return False
        except httpx.RequestError as e:
            logger.error(
                f"HTTP request error during GWC tile truncation for {full_layer_name}, "
                f"gridset {gridset_id_to_truncate}: {e}"
            )
            return False
        except Exception as e_gen:
            logger.error(
                f"Generic error during GWC tile truncation for {full_layer_name}, "
                f"gridset {gridset_id_to_truncate}: {e_gen}"
            )
            return False


async def invalidate_geoserver_cache_for_feature(
    layer_id_uuid: UUID, feature_id_uuid: UUID
):
    """
    Invalidates GeoServer GWC tile cache for a specific feature within a layer.
    It attempts to clear tiles for EPSG:900913
    """
    logger.info(
        f"Attempting to invalidate GeoServer cache for feature {feature_id_uuid} in layer {layer_id_uuid}"
    )

    bounds_3067 = None

    async with connection.get_async_context_db() as session:
        # Fetch feature's bounding box in EPSG:3067
        stmt = text(
            """
            SELECT
                ST_XMin(geometry) as minx,
                ST_YMin(geometry) as miny,
                ST_XMax(geometry) as maxx,
                ST_YMax(geometry) as maxy
            FROM forest_area
            WHERE id = :feature_id AND layer_id = :layer_id AND geometry IS NOT NULL;
            """
        )
        result = await session.execute(
            stmt, {"feature_id": str(feature_id_uuid), "layer_id": str(layer_id_uuid)}
        )
        bounds_data = result.mappings().first()

        if bounds_data and not any(bounds_data[k] is None for k in bounds_data.keys()):
            bounds_3067 = (
                bounds_data["minx"],
                bounds_data["miny"],
                bounds_data["maxx"],
                bounds_data["maxy"],
            )

    if not bounds_3067:
        logger.warning(
            f"Could not determine valid bounds for feature {feature_id_uuid}. Skipping GeoServer cache invalidation."
        )
        return

    await invalidate_geoserver_cache_by_bbox(layer_id_uuid, bounds_3067)


async def invalidate_geoserver_cache_for_features(
    layer_id_uuid: UUID, feature_ids: list[UUID]
):
    """
    Invalidates GeoServer GWC tile cache for a list of features within a layer.
    It computes an overlapping bounding box for all features and clears tiles for EPSG:900913.
    """
    logger.info(
        f"Attempting to invalidate GeoServer cache for features {feature_ids} in layer {layer_id_uuid}"
    )

    bounds_3067 = None

    async with connection.get_async_context_db() as session:
        # Fetch the combined bounding box for all features in EPSG:3067
        stmt = text(
            """
            SELECT
                ST_XMin(ST_Extent(geometry)) as minx,
                ST_YMin(ST_Extent(geometry)) as miny,
                ST_XMax(ST_Extent(geometry)) as maxx,
                ST_YMax(ST_Extent(geometry)) as maxy
            FROM forest_area
            WHERE id = ANY(:feature_ids) AND layer_id = :layer_id AND geometry IS NOT NULL;
            """
        )
        result = await session.execute(
            stmt,
            {
                "feature_ids": [str(fid) for fid in feature_ids],
                "layer_id": str(layer_id_uuid),
            },
        )
        bounds_data = result.mappings().first()

        if bounds_data and not any(bounds_data[k] is None for k in bounds_data.keys()):
            bounds_3067 = (
                bounds_data["minx"],
                bounds_data["miny"],
                bounds_data["maxx"],
                bounds_data["maxy"],
            )

    if not bounds_3067:
        logger.warning(
            f"Could not determine combined bounds for features in layer {layer_id_uuid}. Skipping cache invalidation."
        )
        return

    await invalidate_geoserver_cache_by_bbox(layer_id_uuid, bounds_3067)
