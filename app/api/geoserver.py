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


async def create_geoserver_layer(
    forest_layer_id: str,
    forest_layer_name: str,
) -> bool:
    """Create GeoServer layer for forest areas with given layer_id."""

    # SQL view parameters
    view_name = f"forest_areas_{forest_layer_id}"
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
                    {
                        "name": "geometry",
                        "binding": "org.locationtech.jts.geom.Geometry",
                    }
                ]
            },
        }
    }

    async with httpx.AsyncClient() as client:
        url = f"{geoserver_url}/rest/workspaces/{geoserver_workspace}/datastores/{geoserver_store}/featuretypes"

        # Create new feature type
        response = await client.post(
            f"{geoserver_url}/rest/workspaces/{geoserver_workspace}/datastores/{geoserver_store}/featuretypes",
            json=layer_config,
            auth=(username, password),
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 201:
            return True
        else:
            raise Exception(f"Failed to create layer: {response.text}")


async def delete_geoserver_layer(forest_layer_id: str) -> bool:
    """
    Call GeoServer's REST endpoint to remove the corresponding feature type and its associated resources.

    This function issues a DELETE request to:
      /rest/workspaces/{workspace}/datastores/{store}/featuretypes/{layer}
    """
    view_name = f"forest_areas_{forest_layer_id}"
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
