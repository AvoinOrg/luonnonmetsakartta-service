import pytest
from uuid import UUID
from shapely.geometry import Polygon
from geoalchemy2.shape import from_shape
import httpx

from app.db import connection
from app.db.models.forest_layer import ForestLayer
from app.db.models.forest_area import ForestArea
from app.api.geoserver import (
    create_geoserver_layer,
    delete_geoserver_layer,
    get_layer_name_for_id,
    get_layer_permissions,
    set_layer_visibility,
)
from app.db.prod_connection_mock import prod_monkeypatch_get_async_context_db
from app.config import get_settings

settings = get_settings()

GEOSERVER_URL = settings.geoserver_url
GEOSERVER_WORKSPACE = settings.geoserver_workspace
GEOSERVER_STORE = settings.geoserver_store
GEOSERVER_USER = settings.geoserver_user
GEOSERVER_PASSWORD = settings.geoserver_password

TEST_LAYER_ID = UUID("00000000-0000-0000-0000-000000000999")

test_suite_order = 2000

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


@pytest.mark.order(test_suite_order)
@pytest.mark.asyncio
async def test_create_geoserver_layer():
    result = await create_geoserver_layer(
        forest_layer_id=TEST_LAYER_ID, forest_layer_name="Test GeoServer Layer"
    )

    assert result is True

    # Verify layer exists in GeoServer
    async with httpx.AsyncClient() as client:
        url = f"{GEOSERVER_URL}/rest/workspaces/{GEOSERVER_WORKSPACE}/layers/forest_areas_{TEST_LAYER_ID}.json"
        print(url)
        response = await client.get(
            f"{GEOSERVER_URL}/rest/workspaces/{GEOSERVER_WORKSPACE}/layers/forest_areas_{TEST_LAYER_ID}.json",
            auth=(GEOSERVER_USER, GEOSERVER_PASSWORD),
        )
        assert response.status_code == 200


@pytest.mark.order(after="test_create_geoserver_layer")
@pytest.mark.asyncio
async def test_get_layer_permissions():
    layer_name = get_layer_name_for_id(TEST_LAYER_ID)
    permissions = await get_layer_permissions(TEST_LAYER_ID)

    # Check for a read rule "<workspace>.<layer>.r"
    read_rule_key = f"{GEOSERVER_WORKSPACE}.{layer_name}.r"
    assert read_rule_key in permissions, f"Expected read rule {read_rule_key}"

    # Assert unwanted roles are not present
    read_rule_roles = permissions[read_rule_key]
    assert "ROLE_ANONYMOUS" not in read_rule_roles
    assert "ROLE_AUTHENTICATED" not in read_rule_roles


@pytest.mark.order(after="test_get_layer_permissions")
@pytest.mark.asyncio
async def test_set_layer_visibility():
    result = await set_layer_visibility(TEST_LAYER_ID, is_hidden=False)

    assert result is True

    layer_name = get_layer_name_for_id(TEST_LAYER_ID)
    permissions = await get_layer_permissions(TEST_LAYER_ID)

    # Check for a read rule "<workspace>.<layer>.r"
    read_rule_key = f"{GEOSERVER_WORKSPACE}.{layer_name}.r"
    assert read_rule_key in permissions, f"Expected read rule {read_rule_key}"

    # Assert unwanted roles are not present
    read_rule_roles = permissions[read_rule_key]
    assert "ROLE_ANONYMOUS" in read_rule_roles
    assert "ROLE_AUTHENTICATED" in read_rule_roles


@pytest.mark.order(after="test_set_layer_visibility")
@pytest.mark.asyncio
async def test_delete_geoserver_layer(prod_monkeypatch_get_async_context_db):
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
        layer_url = f"{GEOSERVER_URL}/rest/workspaces/{GEOSERVER_WORKSPACE}/layers/forest_areas_{TEST_LAYER_ID}.json"
        response = await client.get(
            layer_url, auth=(GEOSERVER_USER, GEOSERVER_PASSWORD)
        )
        # We expect 404 or similar error post-deletion
        assert response.status_code == 404, (
            f"Expected status_code=404 after deletion, got {response.status_code}"
        )
