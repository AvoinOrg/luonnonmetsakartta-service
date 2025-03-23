from typing import Optional
from sqlalchemy.sql import text
import httpx
from uuid import UUID
from app.config import get_settings
from app.db import connection

global_settings = get_settings()

geoserver_url = global_settings.geoserver_url
geoserver_workspace = global_settings.geoserver_workspace
geoserver_store = global_settings.geoserver_store
username = global_settings.geoserver_user
password = global_settings.geoserver_password


def get_layer_name_for_id(layer_id: str | UUID) -> str:
    return f"forest_areas_{layer_id}"


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
    SELECT 
        id,
        name,
        municipality,
        region,
        area_ha,
        geometry
    FROM forest_area 
    WHERE layer_id = '{forest_layer_id}'
    """

    # Layer configuration
    layer_config = {
        "featureType": {
            "name": view_name,
            "nativeName": view_name,
            "title": f"{forest_layer_name} - {view_name}",
            "abstract": "Forest areas filtered by layer ID",
            "srs": "EPSG:3067",
            "projectionPolicy": "FORCE_DECLARED",
            "enabled": True,
            "advertised": not is_hidden,
            "store": {
                "@class": "dataStore",
                "name": f"{geoserver_workspace}:{geoserver_store}",
            },
            "virtualTable": {
                "name": view_name,
                "sql": sql_view,
                "geometry": {"name": "geometry", "type": "Geometry", "srid": 3067},
                "parameters": [],
            },
            "attributes": {
                "attribute": [
                    {"name": "id", "binding": "java.lang.String"},
                    {"name": "created_ts", "binding": "java.sql.Timestamp"},
                    {"name": "updated_ts", "binding": "java.sql.Timestamp"},
                    {"name": "name", "binding": "java.lang.String"},
                    {
                        "name": "description",
                        "binding": "org.locationtech.jts.geom.Geometry",
                    },
                    {
                        "name": "pictures",
                        "binding": "org.locationtech.jts.geom.Geometry",
                    },
                    {"name": "municipality", "binding": "java.lang.String"},
                    {"name": "region", "binding": "java.lang.String"},
                    {"name": "area_ha", "binding": "java.lang.Double"},
                    {"name": "date", "binding": "java.lang.String"},
                    {
                        "name": "geometry",
                        "binding": "org.locationtech.jts.geom.Geometry",
                    },
                ]
            },
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
            await set_layer_visibility(
                layer_id=forest_layer_id, is_hidden=is_hidden, is_initial_rule=True
            )
            return True
        else:
            raise Exception(f"Failed to create layer: {response.text}")


async def delete_geoserver_layer(forest_layer_id: str | UUID) -> bool:
    """
    Call GeoServer's REST endpoint to remove the corresponding feature type and its associated resources.

    This function issues a DELETE request to:
      /rest/workspaces/{workspace}/datastores/{store}/featuretypes/{layer}
    """
    view_name = get_layer_name_for_id(layer_id=forest_layer_id)
    print(view_name)
    delete_url = f"{geoserver_url}/rest/workspaces/{geoserver_workspace}/datastores/{geoserver_store}/featuretypes/{view_name}?recurse=true"
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            delete_url,
            auth=(username, password),
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code == 200:
            async with connection.get_async_context_db() as session:
                await session.execute(
                    text(f'DROP TABLE IF EXISTS "{view_name}" CASCADE')
                )
                await session.commit()

            return True
        else:
            raise Exception(f"Failed to delete layer: {resp.text}")


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


async def set_layer_visibility(
    layer_id: str | UUID, is_hidden: bool, is_initial_rule: bool = False
) -> bool:
    """
    Modify visibility permissions for a GeoServer layer by appending to existing rules,
    using the JSON format GeoServer expects. For example:
    {
      "workspace.layer_name.w": "ADMIN,LUONNONMETSAKARTTA_SERVICE"
    }
    """
    layer_name = get_layer_name_for_id(layer_id=layer_id)

    # Roles for reading (".r") and writing (".w"), plus anonymous if not hidden
    base_roles = ["ADMIN", "LUONNONMETSAKARTTA_SERVICE", "LUONNONMETSAKARTTA_USER"]
    if not is_hidden:
        base_roles += ["ROLE_AUTHENTICATED", "ROLE_ANONYMOUS"]

    # A single JSON dict with ruleKey: roleValue
    # Example: { "sandbox_luonnonmetsakartta.forest_layer.w": "ADMIN,FOO,BAR" }
    role_string = ",".join(base_roles)
    rule_key = f"{geoserver_workspace}.{layer_name}.r"  # read rule
    # If you also want to set write permissions, you can add another key: .w, etc.

    # Build the POST/PUT body dict
    json_data = {rule_key: role_string}

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
            return True
        else:
            raise Exception(
                f"Failed to update layer visibility: ({response.status_code}) {response.text}"
            )
