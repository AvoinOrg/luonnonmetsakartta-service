import pytest
from uuid import UUID
from shapely.geometry import Polygon
from geoalchemy2.shape import from_shape
import httpx

from app.db import connection
from app.db.models.forest_layer import ForestLayer
from app.db.models.forest_area import ForestArea
from app.api.geoserver import create_geoserver_layer, delete_geoserver_layer
from app.db.connection_mock import monkeypatch_get_async_context_db
from app.config import get_settings

settings = get_settings()

GEOSERVER_URL = settings.geoserver_url
GEOSERVER_WORKSPACE = settings.geoserver_workspace
GEOSERVER_STORE = settings.geoserver_store
GEOSERVER_USER = settings.geoserver_user
GEOSERVER_PASSWORD = settings.geoserver_password

TEST_LAYER_ID = UUID("00000000-0000-0000-0000-000000000999")

# @pytest.fixture(scope="session")
# async def test_layer_with_areas(monkeypatch_get_async_context_db):
#     async with connection.get_async_context_db() as session:
#         # Create test layer
#         layer = ForestLayer(
#             name="Test GeoServer Layer",
#             description="Test Layer for GeoServer integration"
#         )
#         session.add(layer)
#         await session.commit()
#         await session.refresh(layer)

#         # Create test areas
#         polygon = Polygon([(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)])
#         areas = []
#         for i in range(3):
#             area = ForestArea(
#                 layer_id=layer.id,
#                 name=f"Test Area {i}",
#                 municipality="Test City",
#                 region="Test Region",
#                 area_ha=100.0,
#                 geometry=from_shape(polygon, srid=3067)
#             )
#             areas.append(area)

#         session.add_all(areas)
#         await session.commit()

#         yield layer

#         # Cleanup
#         await session.delete(layer)
#         await session.commit()


@pytest.mark.order(1)
@pytest.mark.asyncio
async def test_create_geoserver_layer():
    result = await create_geoserver_layer(
        forest_layer_id=TEST_LAYER_ID, forest_layer_name="Test GeoServer Layer"
    )

    assert result is True

    # Verify layer exists in GeoServer
    async with httpx.AsyncClient() as client:
        url = f"{GEOSERVER_URL}/rest/workspaces/{GEOSERVER_WORKSPACE}/layers/forest_areas_{TEST_LAYER_ID.hex}.json"
        print(url)
        response = await client.get(
            f"{GEOSERVER_URL}/rest/workspaces/{GEOSERVER_WORKSPACE}/layers/forest_areas_{TEST_LAYER_ID.hex}.json",
            auth=(GEOSERVER_USER, GEOSERVER_PASSWORD),
        )
        assert response.status_code == 200

@pytest.mark.order(after="test_create_geoserver_layer")
@pytest.mark.asyncio
async def test_delete_geoserver_layer():
    """
    Test deleting the same GeoServer layer created in test_create_geoserver_layer.
    Then verify that GeoServer returns 404 or similar error message
    upon attempting to fetch the layer again.
    """
    # 1) Delete the layer
    result = await delete_geoserver_layer(forest_layer_id=TEST_LAYER_ID)
    assert result is True, "Expected geoserver delete function to return True"

    # 2) Verify deletion
    async with httpx.AsyncClient() as client:
        layer_url = f"{GEOSERVER_URL}/rest/workspaces/{GEOSERVER_WORKSPACE}/layers/forest_areas_{TEST_LAYER_ID.hex}.json"
        response = await client.get(
            layer_url, auth=(GEOSERVER_USER, GEOSERVER_PASSWORD)
        )
        # We expect 404 or similar error post-deletion
        assert response.status_code == 404, (
            f"Expected status_code=404 after deletion, got {response.status_code}"
        )
