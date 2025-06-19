# Tests that require a running GeoServer instance
# They use the POSTGRES_ and GEOSERVER_ env variables, instead of the TEST_POSTGRES_ variables
# Don't actually run these tests against production server, but a sandbox instance.

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
    create_geoserver_layers,  # Added for the new fixture
    delete_geoserver_layer,
    get_layer_name_for_id,
    get_layer_centroid_name_for_id,  # Added
    get_layer_permissions,
    invalidate_geoserver_cache_for_features,
    set_layer_visibility,
    _truncate_gwc_tiles_for_gridset,  # Added
    invalidate_geoserver_cache_for_feature,  # Added
)
from app.db.prod_connection_mock import prod_monkeypatch_get_async_context_db
from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

settings = get_settings()

GEOSERVER_URL = settings.geoserver_url
GEOSERVER_WORKSPACE = settings.geoserver_workspace
GEOSERVER_STORE = settings.geoserver_store
GEOSERVER_USER = settings.geoserver_user
GEOSERVER_PASSWORD = settings.geoserver_password

TEST_LAYER_ID = UUID("00000000-0000-0000-0000-000000000999")
TEST_CACHE_LAYER_ID = UUID("00000000-0000-0000-0000-000000000888")
TEST_CACHE_FEATURE_ID = UUID("00000000-0000-0000-0000-000000000777")

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


@pytest.fixture(scope="module", autouse=True)
async def cleanup_existing_geoserver_test_layer(prod_monkeypatch_get_async_context_db):
    """
    Fixture to attempt cleanup of a specific GeoServer test layer and its
    associated database view before tests in this module run.
    This helps ensure a cleaner state, especially if previous test runs
    were interrupted.
    """
    logger.info(
        f"Attempting pre-test cleanup of GeoServer layer and view for ID: {TEST_LAYER_ID}"
    )
    try:
        # delete_geoserver_layer handles both GeoServer resource and DB view deletion.
        # It's expected to be somewhat idempotent or log issues if the layer doesn't exist.
        await delete_geoserver_layer(forest_layer_id=TEST_LAYER_ID)
        logger.info(
            f"Pre-test cleanup attempt for GeoServer layer ID {TEST_LAYER_ID} finished."
        )
    except Exception as e:
        # Log the error and continue. The layer might not have existed,
        # or the specific error might not prevent subsequent tests from running.
        logger.error(
            f"Error during pre-test cleanup for GeoServer layer ID {TEST_LAYER_ID}: {str(e)}"
        )


@pytest.mark.order(test_suite_order)
@pytest.mark.asyncio
async def test_create_geoserver_layer():
    result = await create_geoserver_layer(
        forest_layer_id=TEST_LAYER_ID,
        forest_layer_name="Test GeoServer Layer",
        is_hidden=True,
    )

    assert result is True

    # # Verify layer exists in GeoServer
    # async with httpx.AsyncClient() as client:
    #     url = f"{GEOSERVER_URL}/rest/workspaces/{GEOSERVER_WORKSPACE}/layers/forest_areas_{TEST_LAYER_ID}.json"
    #     print(url)
    #     response = await client.get(
    #         f"{GEOSERVER_URL}/rest/workspaces/{GEOSERVER_WORKSPACE}/layers/forest_areas_{TEST_LAYER_ID}.json",
    #         auth=(GEOSERVER_USER, GEOSERVER_PASSWORD),
    #     )
    #     assert response.status_code == 200


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

    # Retry visibility update if conflicts occur
    if not result:
        logger.warning(
            f"Visibility update failed for layer {TEST_LAYER_ID}. Retrying with rule creation."
        )
        retry_result = await set_layer_visibility(
            TEST_LAYER_ID, is_hidden=False, is_initial_rule=True
        )
        assert retry_result is True, "Retrying visibility update failed."

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


@pytest.fixture(scope="function")
async def layer_and_feature_for_cache_test(prod_monkeypatch_get_async_context_db):
    """
    Fixture to create a temporary layer and a feature with geometry in the DB,
    and their corresponding GeoServer layers.
    """
    db_layer = None
    db_feature = None
    geoserver_layers_created_successfully = False

    async with connection.get_async_context_db() as session:
        # 1. Create DB Layer
        db_layer = ForestLayer(
            id=TEST_CACHE_LAYER_ID,
            name="Cache Test Layer",
            description="Layer for testing GWC invalidation",
        )
        session.add(db_layer)
        await session.commit()
        await session.refresh(db_layer)
        logger.info(f"Created DB layer for cache test: {db_layer.id}")

        # 2. Create DB Feature with geometry
        # A simple square polygon in EPSG:3067
        polygon = Polygon(
            [
                (250000, 6800000),
                (250000, 6800010),
                (250010, 6800010),
                (250010, 6800000),
                (250000, 6800000),
            ]
        )
        db_feature = ForestArea(
            id=TEST_CACHE_FEATURE_ID,
            layer_id=db_layer.id,
            name="Cache Test Feature",
            geometry=from_shape(polygon, srid=3067),
        )
        session.add(db_feature)
        await session.commit()
        await session.refresh(db_feature)
        logger.info(
            f"Created DB feature for cache test: {db_feature.id} in layer {db_layer.id}"
        )

    # 3. Create GeoServer layers (main and centroid)
    try:
        # Using the plural create_geoserver_layers which handles both
        gs_creation_result = await create_geoserver_layers(
            forest_layer_id=str(
                db_layer.id
            ),  # Ensure it's a string if function expects
            forest_layer_name=db_layer.name,
            is_hidden=False,  # Make it public for easier verification if needed
        )
        # Check if both area and centroid layers were successfully created
        if (
            gs_creation_result["area_layer"]["success"]
            and gs_creation_result["centroid_layer"]["success"]
        ):
            geoserver_layers_created_successfully = True
            logger.info(
                f"Successfully created GeoServer layers for cache test layer: {db_layer.id}"
            )
        else:
            logger.error(
                f"Failed to create one or more GeoServer layers for cache test: {gs_creation_result}"
            )
            # If GeoServer layer creation fails, the test might not be meaningful,
            # but we'll still proceed to cleanup.
    except Exception as e_gs:
        logger.error(
            f"Exception during GeoServer layer creation for cache test: {e_gs}"
        )

    yield db_layer.id, db_feature.id  # Provide IDs to the test

    # Cleanup
    logger.info(f"Cleaning up cache test data for layer {TEST_CACHE_LAYER_ID}")
    # 4. Delete GeoServer layers (this also drops DB views)
    # Use the main delete_geoserver_layer which handles both area and centroid layers and their views
    try:
        await delete_geoserver_layer(forest_layer_id=TEST_CACHE_LAYER_ID)
        logger.info(
            f"Successfully deleted GeoServer layers for cache test: {TEST_CACHE_LAYER_ID}"
        )
    except Exception as e_del_gs:
        logger.error(
            f"Error deleting GeoServer layers for cache test {TEST_CACHE_LAYER_ID}: {e_del_gs}"
        )

    # 5. Delete DB Feature and Layer (if they were created)
    async with connection.get_async_context_db() as session:
        if TEST_CACHE_FEATURE_ID:
            feat_to_del = await session.get(ForestArea, TEST_CACHE_FEATURE_ID)
            if feat_to_del:
                await session.delete(feat_to_del)
        if TEST_CACHE_LAYER_ID:
            layer_to_del = await session.get(ForestLayer, TEST_CACHE_LAYER_ID)
            if layer_to_del:
                await session.delete(layer_to_del)
        await session.commit()
        logger.info(
            f"Cleaned up DB layer and feature for cache test: {TEST_CACHE_LAYER_ID}, {TEST_CACHE_FEATURE_ID}"
        )


@pytest.mark.order(
    after="test_set_layer_visibility", before="test_delete_geoserver_layer"
)
@pytest.mark.asyncio
async def test_truncate_gwc_tiles_for_gridset_direct_call(
    layer_and_feature_for_cache_test,
    prod_monkeypatch_get_async_context_db,
):
    """
    Tests the _truncate_gwc_tiles_for_gridset function directly.
    Assumes the layer from TEST_LAYER_ID has been created by a previous test.
    """
    layer_id, feature_id = layer_and_feature_for_cache_test
    logger.info(f"Testing _truncate_gwc_tiles_for_gridset for layer ID: {layer_id}")
    raw_layer_name = get_layer_name_for_id(layer_id)

    test_bounds_3857 = (
        2226389.815865101,
        8440380.14088389,
        2338299.6794169014,
        8464963.0,
    )

    # Test with EPSG:900913 gridset
    try:
        result_900913 = await _truncate_gwc_tiles_for_gridset(
            raw_layer_name=raw_layer_name,
            bounds_coords=test_bounds_3857,
            bounds_srs_code=3857,
            gridset_id_to_truncate="EPSG:900913",
            tile_format="application/vnd.mapbox-vector-tile",
        )
        assert (
            result_900913 is True
        ), "GWC truncation for EPSG:900913 gridset failed or returned False"
    except Exception as e:
        logger.error(f"Error during GWC truncation for EPSG:900913: {e}")
        pytest.fail(f"GWC truncation for EPSG:900913 gridset raised an exception: {e}")

    # Test for the centroid layer as well
    raw_centroid_layer_name = get_layer_centroid_name_for_id(layer_id)
    result_centroid_900913 = await _truncate_gwc_tiles_for_gridset(
        raw_layer_name=raw_centroid_layer_name,
        bounds_coords=test_bounds_3857,
        bounds_srs_code=3857,
        gridset_id_to_truncate="EPSG:900913",
        tile_format="application/vnd.mapbox-vector-tile",
    )
    assert (
        result_centroid_900913 is True
    ), "GWC truncation for centroid layer (EPSG:900913) failed"


@pytest.mark.order(
    after="test_truncate_gwc_tiles_for_gridset_direct_call",
    before="test_delete_geoserver_layer",
)
@pytest.mark.asyncio
async def test_invalidate_geoserver_cache_for_feature(
    layer_and_feature_for_cache_test, prod_monkeypatch_get_async_context_db
):
    """
    Tests the invalidate_geoserver_cache_for_feature function.
    This uses a fixture to set up a layer and feature.
    """
    layer_id, feature_id = layer_and_feature_for_cache_test
    logger.info(
        f"Testing invalidate_geoserver_cache_for_feature for layer {layer_id}, feature {feature_id}"
    )

    try:
        # The function itself doesn't return a boolean for overall success,
        # it logs errors internally. We're checking that it runs without exceptions
        # and that logs (viewable during test execution) would show truncation attempts.
        await invalidate_geoserver_cache_for_feature(
            layer_id_uuid=layer_id,  # Function expects UUID
            feature_id_uuid=feature_id,  # Function expects UUID
        )
        # If we reach here, the function executed.
        # Further validation would involve checking GeoServer GWC logs or specific tile responses,
        # which is complex for an automated test.
        logger.info(
            f"invalidate_geoserver_cache_for_feature executed for layer {layer_id}, feature {feature_id}"
        )
    except Exception as e:
        pytest.fail(f"invalidate_geoserver_cache_for_feature raised an exception: {e}")


@pytest.mark.order(
    after="test_set_layer_visibility"
)  # Ensure this runs after other layer operations but before final cleanup
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
        assert (
            response.status_code == 404
        ), f"Expected status_code=404 after deletion, got {response.status_code}"


@pytest.fixture(scope="function")
async def layer_and_features_for_cache_test(prod_monkeypatch_get_async_context_db):
    """
    Fixture to create a temporary layer and multiple features with geometry in the DB,
    and their corresponding GeoServer layers.
    """
    db_layer = None
    db_features = []
    geoserver_layers_created_successfully = False

    async with connection.get_async_context_db() as session:
        # 1. Create DB Layer
        db_layer = ForestLayer(
            id=TEST_CACHE_LAYER_ID,
            name="Cache Test Layer",
            description="Layer for testing GWC invalidation",
        )
        session.add(db_layer)
        await session.commit()
        await session.refresh(db_layer)
        logger.info(f"Created DB layer for cache test: {db_layer.id}")

        # 2. Create DB Features with geometry
        # Two simple square polygons in EPSG:3067
        polygons = [
            Polygon(
                [
                    (250000, 6800000),
                    (250000, 6800010),
                    (250010, 6800010),
                    (250010, 6800000),
                    (250000, 6800000),
                ]
            ),
            Polygon(
                [
                    (250020, 6800020),
                    (250020, 6800030),
                    (250030, 6800030),
                    (250030, 6800020),
                    (250020, 6800020),
                ]
            ),
        ]
        for i, polygon in enumerate(polygons):
            feature = ForestArea(
                id=UUID(f"00000000-0000-0000-0000-00000000077{i}"),
                layer_id=db_layer.id,
                name=f"Cache Test Feature {i}",
                geometry=from_shape(polygon, srid=3067),
            )
            db_features.append(feature)

        session.add_all(db_features)
        await session.commit()
        for feature in db_features:
            await session.refresh(feature)
        logger.info(
            f"Created DB features for cache test: {[feature.id for feature in db_features]} in layer {db_layer.id}"
        )

    # 3. Create GeoServer layers (main and centroid)
    try:
        # Using the plural create_geoserver_layers which handles both
        gs_creation_result = await create_geoserver_layers(
            forest_layer_id=str(
                db_layer.id
            ),  # Ensure it's a string if function expects
            forest_layer_name=db_layer.name,
            is_hidden=False,  # Make it public for easier verification if needed
        )
        # Check if both area and centroid layers were successfully created
        if (
            gs_creation_result["area_layer"]["success"]
            and gs_creation_result["centroid_layer"]["success"]
        ):
            geoserver_layers_created_successfully = True
            logger.info(
                f"Successfully created GeoServer layers for cache test layer: {db_layer.id}"
            )
        else:
            logger.error(
                f"Failed to create one or more GeoServer layers for cache test: {gs_creation_result}"
            )
            # If GeoServer layer creation fails, the test might not be meaningful,
            # but we'll still proceed to cleanup.
    except Exception as e_gs:
        logger.error(
            f"Exception during GeoServer layer creation for cache test: {e_gs}"
        )

    yield db_layer.id, [
        feature.id for feature in db_features
    ]  # Provide IDs to the test

    # Cleanup
    logger.info(f"Cleaning up cache test data for layer {TEST_CACHE_LAYER_ID}")
    # 4. Delete GeoServer layers (this also drops DB views)
    # Use the main delete_geoserver_layer which handles both area and centroid layers and their views
    try:
        await delete_geoserver_layer(forest_layer_id=TEST_CACHE_LAYER_ID)
        logger.info(
            f"Successfully deleted GeoServer layers for cache test: {TEST_CACHE_LAYER_ID}"
        )
    except Exception as e_del_gs:
        logger.error(
            f"Error deleting GeoServer layers for cache test {TEST_CACHE_LAYER_ID}: {e_del_gs}"
        )

    # 5. Delete DB Features and Layer (if they were created)
    async with connection.get_async_context_db() as session:
        for feature in db_features:
            feat_to_del = await session.get(ForestArea, feature.id)
            if feat_to_del:
                await session.delete(feat_to_del)
        layer_to_del = await session.get(ForestLayer, TEST_CACHE_LAYER_ID)
        if layer_to_del:
            await session.delete(layer_to_del)
        await session.commit()
        logger.info(
            f"Cleaned up DB layer and features for cache test: {TEST_CACHE_LAYER_ID}, {[feature.id for feature in db_features]}"
        )


@pytest.mark.order(
    after="test_invalidate_geoserver_cache_for_feature",
    before="test_delete_geoserver_layer",
)
@pytest.mark.asyncio
async def test_invalidate_geoserver_cache_for_features(
    layer_and_features_for_cache_test, prod_monkeypatch_get_async_context_db
):
    """
    Tests the invalidate_geoserver_cache_for_features function.
    This uses a fixture to set up a layer and multiple features.
    """
    layer_id, feature_ids = layer_and_features_for_cache_test
    logger.info(
        f"Testing invalidate_geoserver_cache_for_features for layer {layer_id}, features {feature_ids}"
    )

    try:
        # Test with multiple feature IDs
        await invalidate_geoserver_cache_for_features(
            layer_id_uuid=layer_id, feature_ids=feature_ids
        )
        logger.info(
            f"invalidate_geoserver_cache_for_features executed for layer {layer_id}, features {feature_ids}"
        )

    except Exception as e:
        pytest.fail(f"invalidate_geoserver_cache_for_features raised an exception: {e}")
