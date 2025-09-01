# Tests that require a geoserver instance.
# They use the POSTGRES_ and GEOSERVER_ env variables, instead of the TEST_POSTGRES_ variables
# Don't actually test against production server, but a sandbox instance.
import zipfile
import pytest
import httpx
from pathlib import Path
import geopandas as gpd
from shapely.geometry import Polygon
import tempfile
from app.main import app, lifespan
from app.utils.logger import get_logger
from app.db.prod_connection_mock import prod_monkeypatch_get_async_context_db
from app.config import get_settings

settings = get_settings()

logger = get_logger(__name__)
pytestmark = pytest.mark.order(103)
order_num = 1100

test_layer_name = "Test Layer 83046gjsagasg964znfdljg0"


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
async def client():
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            yield client


@pytest.fixture(scope="session", autouse=True)
async def cleanup_test_layers(client: httpx.AsyncClient, auth_headers):
    """
    Fixture to automatically clean up leftover test layers from previous runs
    at the beginning of the test session.
    """
    logger.info("--- Cleaning up leftover test layers before session ---")
    try:
        response = await client.get("/layers", headers=auth_headers)
        if response.status_code == 200:
            layers = response.json()
            for layer in layers:
                if test_layer_name in layer.get("name", ""):
                    # or "Layer For Feature Update Test" in layer.get("name", ""):
                    logger.info(
                        f"Found leftover test layer to delete: {layer.get('name')} ({layer.get('id')})"
                    )
                    delete_response = await client.delete(
                        f"/layer/{layer['id']}", headers=auth_headers
                    )
                    if delete_response.status_code == 200:
                        logger.info(
                            f"Cleaned up leftover test layer: {layer.get('name')} ({layer.get('id')})"
                        )
                    else:
                        logger.warning(
                            f"Failed to clean up leftover test layer: {layer.get('name')} ({layer.get('id')}) - Status: {delete_response.status_code} {delete_response.text}"
                        )
        else:
            logger.warning(
                f"Could not fetch layers for cleanup, status: {response.status_code}"
            )
    except Exception as e:
        logger.error(f"An exception occurred during cleanup: {e}")

    yield

    # Also clean up at the end of the session
    logger.info("--- Cleaning up leftover test layers after session ---")
    try:
        response = await client.get("/layers", headers=auth_headers)
        if response.status_code == 200:
            layers = response.json()
            for layer in layers:
                if test_layer_name in layer.get("name", ""):
                    logger.info(
                        f"Found leftover test layer to delete (post-session): {layer.get('name')} ({layer.get('id')})"
                    )
                    delete_response = await client.delete(
                        f"/layer/{layer['id']}", headers=auth_headers
                    )
                    if delete_response.status_code == 200:
                        logger.info(
                            f"Cleaned up leftover test layer (post-session): {layer.get('name')} ({layer.get('id')})"
                        )
                    else:
                        logger.warning(
                            f"Failed to clean up leftover test layer (post-session): {layer.get('name')} ({layer.get('id')}) - Status: {delete_response.status_code} {delete_response.text}"
                        )
        else:
            logger.warning(
                f"Could not fetch layers for post-session cleanup, status: {response.status_code}"
            )
    except Exception as e:
        logger.error(f"An exception occurred during post-session cleanup: {e}")


@pytest.fixture(scope="session")
def mock_shapefile():
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create simple polygon
        polygon = Polygon([(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)])
        gdf = gpd.GeoDataFrame({"geometry": [polygon]})
        gdf.crs = "EPSG:3857"

        # Save to temporary directory first
        temp_shp = Path(temp_dir) / "test.shp"
        gdf.to_file(temp_shp)

        # Create zip file
        zip_path = Path(temp_dir) / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            # Add all shapefile components
            for ext in [".shp", ".dbf", ".shx", ".prj"]:
                file_path = temp_shp.with_suffix(ext)
                if file_path.exists():
                    zf.write(file_path, file_path.name)

        # Read zip file contents
        with open(zip_path, "rb") as f:
            yield f.read()


@pytest.fixture(scope="session")
def real_shapefile():
    zip_path = Path("data/test_data.zip")
    with open(zip_path, "rb") as f:
        return f.read()


@pytest.fixture(scope="session")
def real_shapefile_unique():
    zip_path = Path("data/test_data_unique.zip")
    with open(zip_path, "rb") as f:
        return f.read()


@pytest.fixture(scope="session")
async def auth_headers():
    """Get OAuth2 token from Zitadel using client credentials flow"""
    settings = get_settings()
    token_url = f"{settings.zitadel_domain}/oauth/v2/token"

    data = {
        "grant_type": "client_credentials",
        "client_id": settings.zitadel_test_client_id,
        "client_secret": settings.zitadel_test_client_secret,
        "scope": f"openid email profile offline_access urn:zitadel:iam:org:project:roles urn:zitadel:iam:org:project:id:{settings.zitadel_project_id}:aud",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if response.status_code != 200:
            raise Exception(f"Failed to get auth token: {response.text}")

        token_data = response.json()
        return {"Authorization": f"Bearer {token_data['access_token']}"}


@pytest.fixture(scope="session")
async def auth_headers_no_roles():
    """Get OAuth2 token from Zitadel using client credentials flow"""
    settings = get_settings()
    token_url = f"{settings.zitadel_domain}/oauth/v2/token"

    data = {
        "grant_type": "client_credentials",
        "client_id": settings.zitadel_test_client_id_no_roles,
        "client_secret": settings.zitadel_test_client_secret_no_roles,
        "scope": f"openid email profile offline_access urn:zitadel:iam:org:project:roles urn:zitadel:iam:org:project:id:{settings.zitadel_project_id}:aud",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if response.status_code != 200:
            raise Exception(f"Failed to get auth token: {response.text}")

        token_data = response.json()
        return {"Authorization": f"Bearer {token_data['access_token']}"}


@pytest.fixture(scope="session")
def invalid_auth_headers():
    token = "invalid.jwt.token"  # Token from Zitadel service user
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.order(order_num)
@pytest.mark.asyncio
async def test_create_layer_success(
    client: httpx.AsyncClient,
    mock_shapefile,
    auth_headers,
    prod_monkeypatch_get_async_context_db,
) -> None:
    layer_id = None

    try:
        files = [("zip_file", ("test.zip", mock_shapefile, "application/zip"))]
        data = {
            "name": test_layer_name,
            "description": "Test Description",
            "is_hidden": True,
            "indexing_strategy": "id",
            "id_col": "id",
            "name_col": "nimi",
            "municipality_col": "kunta",
        }
        response = await client.post(
            "/layer", files=files, data=data, headers=auth_headers
        )
        assert response.status_code == 200
        layer_id = response.json()["id"]

        response = await client.get(f"/layer/{layer_id}", headers=auth_headers)
        assert response.status_code == 200
        result = response.json()
        assert result["name"] == data["name"]
        assert result["description"] == data["description"]
        assert result["is_hidden"] is not None
        assert result["id"] == layer_id

    finally:
        if layer_id:
            response = await client.delete(f"/layer/{layer_id}", headers=auth_headers)
            assert response.status_code == 200


@pytest.mark.order(order_num + 1)
@pytest.mark.asyncio
async def test_import_real_shapefile_success(
    client, real_shapefile, auth_headers, prod_monkeypatch_get_async_context_db
):
    layer_id = None
    try:
        files = [("zip_file", ("test.zip", real_shapefile, "application/zip"))]
        data = {
            "name": test_layer_name + " real",
            "description": "Test Description for real shapefile",
            "indexing_strategy": "id",
            "id_col": "id",
            "name_col": "nimi",
            "municipality_col": "kunta",
        }
        response = await client.post(
            "/layer", files=files, data=data, headers=auth_headers
        )
        assert response.status_code == 200
        layer_id = response.json()["id"]

        response = await client.get(f"/layer/{layer_id}", headers=auth_headers)
        assert response.status_code == 200
        result = response.json()
        assert result["name"] == data["name"]
        assert result["description"] == data["description"]
        assert result["is_hidden"] is not None and result["is_hidden"]
        assert result["id"] == layer_id

    finally:
        if layer_id:
            response = await client.delete(f"/layer/{layer_id}", headers=auth_headers)
            assert response.status_code == 200


@pytest.mark.order(order_num + 1)
@pytest.mark.asyncio
async def test_import_real_shapefile_success_2(
    client, real_shapefile, auth_headers, prod_monkeypatch_get_async_context_db
):
    layer_id = None
    try:
        files = [("zip_file", ("test.zip", real_shapefile, "application/zip"))]
        data = {
            "name": "Real " + test_layer_name,
            "description": "Test Description for real shapefile",
            "indexing_strategy": "id",
            "id_col": "id",
            "name_col": "nimi",
            "municipality_col": "kunta",
            "region_col": "maakunta",
            "description_col": "nimi",
            "area_col": "ala_ha",
        }
        response = await client.post(
            "/layer", files=files, data=data, headers=auth_headers
        )
        assert response.status_code == 200
        layer_id = response.json()["id"]

        response = await client.get(f"/layer/{layer_id}", headers=auth_headers)
        assert response.status_code == 200
        result = response.json()
        assert result["name"] == data["name"]
        assert result["description"] == data["description"]
        assert result["is_hidden"] is not None and result["is_hidden"]
        assert result["id"] == layer_id

    finally:
        if layer_id:
            response = await client.delete(f"/layer/{layer_id}", headers=auth_headers)
            assert response.status_code == 200


@pytest.fixture(scope="function")
async def test_layers(
    client, mock_shapefile, auth_headers, prod_monkeypatch_get_async_context_db
):
    """Fixture to create test layers and clean them up after tests"""
    files = [("zip_file", ("test.zip", mock_shapefile, "application/zip"))]
    layer_ids = []

    # Create hidden layer
    response1 = await client.post(
        "/layer",
        files=files,
        data={
            "name": test_layer_name + " 1",
            "description": "First test layer",
            "indexing_strategy": "id",
            "id_col": "id",
            "name_col": "nimi",
            "municipality_col": "kunta",
        },
        headers=auth_headers,
    )
    assert response1.status_code == 200
    layer_ids.append(response1.json()["id"])

    # Create another layer
    response2 = await client.post(
        "/layer",
        files=files,
        data={
            "name": test_layer_name + " 2",
            "description": "Second test layer",
            "is_hidden": True,
            "indexing_strategy": "id",
            "id_col": "id",
            "name_col": "nimi",
            "municipality_col": "kunta",
        },
        headers=auth_headers,
    )
    assert response2.status_code == 200
    layer_ids.append(response2.json()["id"])

    yield layer_ids

    # Cleanup
    for layer_id in layer_ids:
        delete_response = await client.delete(
            f"/layer/{layer_id}", headers=auth_headers
        )
        assert delete_response.status_code == 200


@pytest.mark.order(order_num + 2)
@pytest.mark.asyncio
async def test_get_layers_no_auth(
    client: httpx.AsyncClient,
    test_layers,
    prod_monkeypatch_get_async_context_db,
):
    """Test layers endpoint with no authentication"""
    response = await client.get("/layers")
    assert response.status_code == 200

    layers = response.json()
    assert isinstance(layers, list)

    # Verify only visible layer is present
    layer_names = [layer["name"] for layer in layers]
    assert test_layer_name + " 1" not in layer_names  # Hidden layer
    assert test_layer_name + " 2" in layer_names  # Public layer

    # Verify layer structure for non-editors
    for layer in layers:
        assert "id" in layer
        assert "name" in layer
        assert "description" in layer
        assert "is_hidden" not in layer


@pytest.mark.order(order_num + 3)
@pytest.mark.asyncio
async def test_get_layers_invalid_auth(
    client: httpx.AsyncClient,
    test_layers,
    invalid_auth_headers,
    prod_monkeypatch_get_async_context_db,
):
    """Test layers endpoint with invalid authentication"""
    response = await client.get("/layers", headers=invalid_auth_headers)
    assert response.status_code == 200

    layers = response.json()
    assert isinstance(layers, list)

    # Verify only visible layer is present
    layer_names = [layer["name"] for layer in layers]
    assert test_layer_name + " 1" not in layer_names
    assert test_layer_name + " 2" in layer_names

    for layer in layers:
        assert "is_hidden" not in layer


@pytest.mark.order(order_num + 4)
@pytest.mark.asyncio
async def test_get_layers_no_roles(
    client: httpx.AsyncClient,
    test_layers,
    auth_headers_no_roles,
    prod_monkeypatch_get_async_context_db,
):
    """Test layers endpoint with authenticated user without roles"""
    response = await client.get("/layers", headers=auth_headers_no_roles)
    assert response.status_code == 200

    layers = response.json()
    assert isinstance(layers, list)

    layer_names = [layer["name"] for layer in layers]
    assert test_layer_name + " 1" not in layer_names
    assert test_layer_name + " 2" in layer_names

    for layer in layers:
        assert "is_hidden" not in layer


@pytest.mark.order(order_num + 5)
@pytest.mark.asyncio
async def test_get_layers_with_editor(
    client: httpx.AsyncClient,
    test_layers,
    auth_headers,
    prod_monkeypatch_get_async_context_db,
):
    """Test layers endpoint with editor role"""
    response = await client.get("/layers", headers=auth_headers)
    assert response.status_code == 200

    layers = response.json()
    assert isinstance(layers, list)

    layer_names = [layer["name"] for layer in layers]
    assert test_layer_name + " 1" in layer_names
    assert test_layer_name + " 2" in layer_names

    # Verify editors see is_hidden field
    for layer in layers:
        assert "is_hidden" in layer


@pytest.fixture(scope="function")
async def test_layer_for_update(
    client, mock_shapefile, auth_headers, prod_monkeypatch_get_async_context_db
):
    """Create a test layer for update tests"""
    files = [("zip_file", ("test.zip", mock_shapefile, "application/zip"))]

    response = await client.post(
        "/layer",
        files=files,
        data={
            "name": test_layer_name + " 1",
            "description": "First test layer",
            "is_hidden": True,
            "indexing_strategy": "id",
            "id_col": "id",
            "name_col": "nimi",
            "municipality_col": "kunta",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    layer_id = response.json()["id"]

    yield layer_id

    # Cleanup
    delete_response = await client.delete(f"/layer/{layer_id}", headers=auth_headers)
    assert delete_response.status_code == 200


@pytest.mark.order(order_num + 6)
@pytest.mark.asyncio
async def test_update_layer_with_editor(
    client: httpx.AsyncClient,
    test_layer_for_update,
    auth_headers,
    prod_monkeypatch_get_async_context_db,
):
    """Test updating layer with editor privileges"""
    updated_data = {
        "name": "Updated " + test_layer_name,
        "description": "Updated description",
        "is_hidden": True,
    }

    response = await client.patch(
        f"/layer/{test_layer_for_update}",
        data=updated_data,  # Use data instead of json
        headers=auth_headers,
    )

    assert response.status_code == 200
    layer = response.json()
    assert layer["name"] == updated_data["name"]
    assert layer["description"] == updated_data["description"]
    assert layer["is_hidden"] == updated_data["is_hidden"]


@pytest.mark.order(order_num + 7)
@pytest.mark.asyncio
async def test_update_layer_no_auth(
    client: httpx.AsyncClient,
    test_layer_for_update,
    prod_monkeypatch_get_async_context_db,
):
    """Test updating layer without authentication"""
    updated_data = {
        "name": "Updated " + test_layer_name,
        "description": "Updated description",
    }

    response = await client.patch(f"/layer/{test_layer_for_update}", json=updated_data)
    assert response.status_code == 401


@pytest.mark.order(order_num + 8)
@pytest.mark.asyncio
async def test_update_layer_invalid_auth(
    client: httpx.AsyncClient,
    test_layer_for_update,
    invalid_auth_headers,
    prod_monkeypatch_get_async_context_db,
):
    """Test updating layer with invalid authentication"""
    updated_data = {
        "name": "Updated " + test_layer_name,
        "description": "Updated description",
    }

    response = await client.patch(
        f"/layer/{test_layer_for_update}",
        json=updated_data,
        headers=invalid_auth_headers,
    )
    assert response.status_code == 401


@pytest.mark.order(order_num + 9)
@pytest.mark.asyncio
async def test_update_layer_no_roles(
    client: httpx.AsyncClient,
    test_layer_for_update,
    auth_headers_no_roles,
    prod_monkeypatch_get_async_context_db,
):
    """Test updating layer with authenticated user without roles"""
    updated_data = {
        "name": "Updated " + test_layer_name,
        "description": "Updated description",
    }

    response = await client.patch(
        f"/layer/{test_layer_for_update}",
        json=updated_data,
        headers=auth_headers_no_roles,
    )
    assert response.status_code == 403


@pytest.mark.order(order_num + 10)
@pytest.mark.asyncio
async def test_get_areas_for_layer(
    client: httpx.AsyncClient,
    test_layers,
    auth_headers,
    auth_headers_no_roles,
    prod_monkeypatch_get_async_context_db,
):
    """Test the endpoint to get all areas for a layer"""

    hidden_layer_id = test_layers[0]  # First layer is hidden
    public_layer_id = test_layers[1]  # Second layer is public

    # Test 1: Editor can access areas from hidden layer
    response = await client.get(f"/layer/{hidden_layer_id}/areas", headers=auth_headers)
    assert response.status_code == 200
    geojson = response.json()

    # Verify GeoJSON structure
    assert "type" in geojson
    assert geojson["type"] == "FeatureCollection"
    assert "features" in geojson
    assert isinstance(geojson["features"], list)

    # Check features if any exist
    for feature in geojson["features"]:
        assert "type" in feature
        assert feature["type"] == "Feature"
        assert "id" in feature
        assert "geometry" in feature
        assert "properties" in feature
        assert "layer_id" in feature["properties"]
        assert feature["properties"]["layer_id"] == hidden_layer_id

    # Test 2: Regular users cannot access areas from hidden layer
    response = await client.get(
        f"/layer/{hidden_layer_id}/areas", headers=auth_headers_no_roles
    )
    assert response.status_code == 403

    # Test 3: Non-authenticated users cannot access areas from hidden layer
    response = await client.get(f"/layer/{hidden_layer_id}/areas")
    assert response.status_code == 403

    # Test 4: Everyone can access areas from public layer
    # Editor
    response = await client.get(f"/layer/{public_layer_id}/areas", headers=auth_headers)
    assert response.status_code == 200
    geojson = response.json()
    assert geojson["type"] == "FeatureCollection"

    # Regular authenticated user
    response = await client.get(
        f"/layer/{public_layer_id}/areas", headers=auth_headers_no_roles
    )
    assert response.status_code == 200
    geojson = response.json()
    assert geojson["type"] == "FeatureCollection"

    # Non-authenticated user
    response = await client.get(f"/layer/{public_layer_id}/areas")
    assert response.status_code == 200
    geojson = response.json()
    assert geojson["type"] == "FeatureCollection"

    # Test 5: Non-existent layer returns 404
    fake_layer_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/layer/{fake_layer_id}/areas", headers=auth_headers)
    assert response.status_code == 404


@pytest.fixture(scope="function")
async def layer_with_feature_for_update(
    client: httpx.AsyncClient,
    mock_shapefile,  # mock_shapefile creates a shapefile with one polygon
    auth_headers,
    prod_monkeypatch_get_async_context_db,
):
    layer_id = None
    feature_id = None

    # Create a layer
    files = [("zip_file", ("test.zip", mock_shapefile, "application/zip"))]
    layer_data = {
        "name": test_layer_name,
        "description": "A layer to test feature updates",
        "is_hidden": True,
        "indexing_strategy": "id",
        "id_col": "id",
        "name_col": "nimi",
        "municipality_col": "kunta",
    }

    response = await client.post(
        "/layer", files=files, data=layer_data, headers=auth_headers
    )
    assert response.status_code == 200
    layer_info = response.json()
    layer_id = layer_info["id"]

    # Get a feature from this layer
    response = await client.get(f"/layer/{layer_id}/areas", headers=auth_headers)
    assert response.status_code == 200
    areas_geojson = response.json()
    assert "features" in areas_geojson and len(areas_geojson["features"]) > 0, (
        "Mock shapefile should create at least one feature"
    )
    feature_id = areas_geojson["features"][0]["id"]

    yield layer_id, feature_id

    # Cleanup
    if layer_id:
        delete_response = await client.delete(
            f"/layer/{layer_id}", headers=auth_headers
        )
        assert delete_response.status_code == 200


@pytest.fixture(scope="function")
async def layer_for_shapefile_update(
    client: httpx.AsyncClient,
    real_shapefile,
    auth_headers,
    prod_monkeypatch_get_async_context_db,
):
    """Create a test layer for shapefile update tests using real data."""
    files = [("zip_file", ("test.zip", real_shapefile, "application/zip"))]
    data = {
        "name": test_layer_name + " for Shapefile Update",
        "description": "Initial layer for testing shapefile updates",
        "is_hidden": True,
        "indexing_strategy": "id",
        "id_col": "id",
        "name_col": "nimi",
        "municipality_col": "kunta",
    }
    response = await client.post("/layer", files=files, data=data, headers=auth_headers)
    assert response.status_code == 200
    layer_id = response.json()["id"]

    yield layer_id

    # Cleanup
    delete_response = await client.delete(f"/layer/{layer_id}", headers=auth_headers)
    assert delete_response.status_code == 200


@pytest.fixture(scope="function")
async def layer_for_shapefile_update_with_name_municipality_indexing(
    client: httpx.AsyncClient,
    real_shapefile_unique,
    auth_headers,
    prod_monkeypatch_get_async_context_db,
):
    """Create a test layer for shapefile update tests using real data."""
    files = [("zip_file", ("test.zip", real_shapefile_unique, "application/zip"))]
    data = {
        "name": test_layer_name + " for Shapefile Update",
        "description": "Initial layer for testing shapefile updates",
        "is_hidden": True,
        "indexing_strategy": "name_municipality",
        "id_col": "id",
        "name_col": "nimi",
        "municipality_col": "kunta",
        "region_col": "maakunta",
        "area_col": "alue",
    }
    response = await client.post("/layer", files=files, data=data, headers=auth_headers)
    assert response.status_code == 200
    layer_id = response.json()["id"]

    yield layer_id

    # Cleanup
    delete_response = await client.delete(f"/layer/{layer_id}", headers=auth_headers)
    assert delete_response.status_code == 200


@pytest.mark.order(order_num + 12)
@pytest.mark.asyncio
async def test_update_layer_with_shapefile_and_delete(
    client: httpx.AsyncClient,
    layer_for_shapefile_update,
    real_shapefile,
    auth_headers,
    prod_monkeypatch_get_async_context_db,
):
    """Test updating a layer with a modified shapefile, deleting features not present in the new file."""
    layer_id = layer_for_shapefile_update

    # Get original areas to know what to expect
    response = await client.get(f"/layer/{layer_id}/areas", headers=auth_headers)
    assert response.status_code == 200
    original_areas = response.json()["features"]
    original_feature_count = len(original_areas)
    assert original_feature_count > 3, "Need at least 4 features for this test"

    # Modify the shapefile data
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        zip_path = temp_dir_path / "test.zip"
        with open(zip_path, "wb") as f:
            f.write(real_shapefile)

        shapefile_dir = temp_dir_path / "unzipped"
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(shapefile_dir)

        shp_file = next(shapefile_dir.glob("*.shp"))
        gdf = gpd.read_file(shp_file)

        # IDs to modify and delete
        id_to_update = gdf.iloc[0]["id"]
        ids_to_delete = [gdf.iloc[1]["id"], gdf.iloc[2]["id"]]
        updated_region = "Updated Region via Shapefile"

        # Modify GDF: update one, delete two
        gdf.loc[gdf["id"] == id_to_update, "maakunta"] = updated_region
        gdf = gdf[~gdf["id"].isin(ids_to_delete)]

        # Save modified GDF to a new shapefile
        modified_shp_path = temp_dir_path / "modified.shp"
        gdf.to_file(modified_shp_path)

        # Create a new zip file with the modified shapefile
        modified_zip_path = temp_dir_path / "modified.zip"
        with zipfile.ZipFile(modified_zip_path, "w") as zf:
            for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
                file = modified_shp_path.with_suffix(ext)
                if file.exists():
                    zf.write(file, file.name)

        with open(modified_zip_path, "rb") as f:
            updated_zip_content = f.read()

    # Call the update endpoint
    files = [("zip_file", ("modified.zip", updated_zip_content, "application/zip"))]
    update_data = {
        "delete_areas_not_updated": True,
        "id_col": "id",
        "name_col": "nimi",
        "municipality_col": "kunta",
        "region_col": "maakunta",
        "area_col": "ala_ha",
    }

    response = await client.patch(
        f"/layer/{layer_id}", files=files, data=update_data, headers=auth_headers
    )
    assert response.status_code == 200, f"Update failed: {response.text}"

    # Verify the changes
    response = await client.get(f"/layer/{layer_id}/areas", headers=auth_headers)
    assert response.status_code == 200
    updated_areas = response.json()["features"]

    assert len(updated_areas) == original_feature_count - 2

    updated_ids = {f["properties"]["original_id"] for f in updated_areas}
    assert str(id_to_update) in updated_ids
    assert str(ids_to_delete[0]) not in updated_ids
    assert str(ids_to_delete[1]) not in updated_ids

    # Check if the name was updated
    updated_feature = next(
        f for f in updated_areas if f["properties"]["original_id"] == str(id_to_update)
    )
    print(updated_feature)
    assert updated_feature["properties"]["region"] == updated_region


@pytest.mark.order(order_num + 12)
@pytest.mark.asyncio
async def test_update_layer_with_shapefile_with_name_municipality_indexing_and_delete(
    client: httpx.AsyncClient,
    layer_for_shapefile_update_with_name_municipality_indexing,
    real_shapefile_unique,
    auth_headers,
    prod_monkeypatch_get_async_context_db,
):
    """Test updating a layer with a modified shapefile, deleting features not present in the new file."""
    layer_id = layer_for_shapefile_update_with_name_municipality_indexing

    # Get original areas to know what to expect
    response = await client.get(f"/layer/{layer_id}/areas", headers=auth_headers)
    assert response.status_code == 200
    original_areas = response.json()["features"]
    original_feature_count = len(original_areas)
    assert original_feature_count > 3, "Need at least 4 features for this test"

    # Modify the shapefile data
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        zip_path = temp_dir_path / "test.zip"
        with open(zip_path, "wb") as f:
            f.write(real_shapefile_unique)

        shapefile_dir = temp_dir_path / "unzipped"
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(shapefile_dir)

        shp_file = next(shapefile_dir.glob("*.shp"))
        gdf = gpd.read_file(shp_file)

        # IDs to modify and delete
        id_to_update = gdf.iloc[0]["id"]
        ids_to_delete = [gdf.iloc[1]["id"], gdf.iloc[2]["id"]]
        updated_region = "Updated Region via Shapefile"

        # Modify GDF: update one, delete two
        gdf.loc[gdf["id"] == id_to_update, "maakunta"] = updated_region
        gdf = gdf[~gdf["id"].isin(ids_to_delete)]

        # Save modified GDF to a new shapefile
        modified_shp_path = temp_dir_path / "modified.shp"
        gdf.to_file(modified_shp_path)

        # Create a new zip file with the modified shapefile
        modified_zip_path = temp_dir_path / "modified.zip"
        with zipfile.ZipFile(modified_zip_path, "w") as zf:
            for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
                file = modified_shp_path.with_suffix(ext)
                if file.exists():
                    zf.write(file, file.name)

        with open(modified_zip_path, "rb") as f:
            updated_zip_content = f.read()

    # Call the update endpoint
    files = [("zip_file", ("modified.zip", updated_zip_content, "application/zip"))]
    update_data = {
        "delete_areas_not_updated": True,
        "id_col": "id",
        "name_col": "nimi",
        "municipality_col": "kunta",
        "region_col": "maakunta",
        "area_col": "ala_ha",
    }

    response = await client.patch(
        f"/layer/{layer_id}", files=files, data=update_data, headers=auth_headers
    )
    assert response.status_code == 200, f"Update failed: {response.text}"

    # Verify the changes
    response = await client.get(f"/layer/{layer_id}/areas", headers=auth_headers)
    assert response.status_code == 200
    updated_areas = response.json()["features"]

    assert len(updated_areas) == original_feature_count - 2

    updated_ids = {f["properties"]["original_id"] for f in updated_areas}
    assert str(id_to_update) in updated_ids
    assert str(ids_to_delete[0]) not in updated_ids
    assert str(ids_to_delete[1]) not in updated_ids

    # Check if the name was updated
    updated_feature = next(
        f for f in updated_areas if f["properties"]["original_id"] == str(id_to_update)
    )

    assert updated_feature["properties"]["region"] == updated_region


@pytest.mark.order(order_num + 13)
@pytest.mark.asyncio
async def test_update_layer_with_shapefile_no_delete(
    client: httpx.AsyncClient,
    layer_for_shapefile_update,
    real_shapefile,
    auth_headers,
    prod_monkeypatch_get_async_context_db,
):
    """Test updating a layer with a modified shapefile, without deleting other features."""
    layer_id = layer_for_shapefile_update

    response = await client.get(f"/layer/{layer_id}/areas", headers=auth_headers)
    assert response.status_code == 200
    original_feature_count = len(response.json()["features"])

    # Create a modified shapefile with only one feature
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        zip_path = temp_dir_path / "test.zip"
        with open(zip_path, "wb") as f:
            f.write(real_shapefile)

        shapefile_dir = temp_dir_path / "unzipped"
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(shapefile_dir)

        shp_file = next(shapefile_dir.glob("*.shp"))
        gdf = gpd.read_file(shp_file)

        # Keep only one feature and modify it
        id_to_update = gdf.iloc[0]["id"]
        updated_name = "Only Updated Feature"
        gdf_updated = gdf[gdf["id"] == id_to_update].copy()
        gdf_updated["nimi"] = updated_name

        modified_shp_path = temp_dir_path / "modified.shp"
        gdf_updated.to_file(modified_shp_path)

        modified_zip_path = temp_dir_path / "modified.zip"
        with zipfile.ZipFile(modified_zip_path, "w") as zf:
            for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
                file = modified_shp_path.with_suffix(ext)
                if file.exists():
                    zf.write(file, file.name)

        with open(modified_zip_path, "rb") as f:
            updated_zip_content = f.read()

    # Call update endpoint with delete_areas_not_updated=False
    files = [("zip_file", ("modified.zip", updated_zip_content, "application/zip"))]
    update_data = {
        "delete_areas_not_updated": False,
        "id_col": "id",
        "name_col": "nimi",
        "municipality_col": "kunta",
        "region_col": "maakunta",
        "area_col": "ala_ha",
    }

    response = await client.patch(
        f"/layer/{layer_id}", files=files, data=update_data, headers=auth_headers
    )
    assert response.status_code == 200

    # Verify changes
    response = await client.get(f"/layer/{layer_id}/areas", headers=auth_headers)
    assert response.status_code == 200
    updated_areas = response.json()["features"]

    assert len(updated_areas) == original_feature_count

    updated_feature = next(
        f for f in updated_areas if f["properties"]["original_id"] == str(id_to_update)
    )
    assert updated_feature["properties"]["name"] == updated_name


@pytest.mark.order(order_num + 13)
@pytest.mark.asyncio
async def test_update_layer_with_shapefile_with_name_municipality_indexing_no_delete(
    client: httpx.AsyncClient,
    layer_for_shapefile_update_with_name_municipality_indexing,
    real_shapefile_unique,
    auth_headers,
    prod_monkeypatch_get_async_context_db,
):
    """Test updating a layer with a modified shapefile, without deleting other features."""
    layer_id = layer_for_shapefile_update_with_name_municipality_indexing

    response = await client.get(f"/layer/{layer_id}/areas", headers=auth_headers)
    assert response.status_code == 200
    original_feature_count = len(response.json()["features"])

    # Create a modified shapefile with only one feature
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        zip_path = temp_dir_path / "test.zip"
        with open(zip_path, "wb") as f:
            f.write(real_shapefile_unique)

        shapefile_dir = temp_dir_path / "unzipped"
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(shapefile_dir)

        shp_file = next(shapefile_dir.glob("*.shp"))
        gdf = gpd.read_file(shp_file)

        # Keep only one feature and modify it
        id_to_update = gdf.iloc[0]["id"]
        updated_region = "Only Updated Region"
        gdf_updated = gdf[gdf["id"] == id_to_update].copy()
        gdf_updated["maakunta"] = updated_region

        modified_shp_path = temp_dir_path / "modified.shp"
        gdf_updated.to_file(modified_shp_path)

        modified_zip_path = temp_dir_path / "modified.zip"
        with zipfile.ZipFile(modified_zip_path, "w") as zf:
            for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
                file = modified_shp_path.with_suffix(ext)
                if file.exists():
                    zf.write(file, file.name)

        with open(modified_zip_path, "rb") as f:
            updated_zip_content = f.read()

    # Call update endpoint with delete_areas_not_updated=False
    files = [("zip_file", ("modified.zip", updated_zip_content, "application/zip"))]
    update_data = {
        "delete_areas_not_updated": False,
        "id_col": "id",
        "name_col": "nimi",
        "municipality_col": "kunta",
        "region_col": "maakunta",
        "area_col": "ala_ha",
    }

    response = await client.patch(
        f"/layer/{layer_id}", files=files, data=update_data, headers=auth_headers
    )
    assert response.status_code == 200

    # Verify changes
    response = await client.get(f"/layer/{layer_id}/areas", headers=auth_headers)
    assert response.status_code == 200
    updated_areas = response.json()["features"]

    assert len(updated_areas) == original_feature_count

    updated_feature = next(
        f for f in updated_areas if f["properties"]["original_id"] == str(id_to_update)
    )
    assert updated_feature["properties"]["region"] == updated_region


@pytest.mark.order(order_num + 11)
@pytest.mark.asyncio
async def test_update_feature_in_layer_success_and_add_picture(
    client: httpx.AsyncClient,
    layer_with_feature_for_update,
    auth_headers,
    prod_monkeypatch_get_async_context_db,
):
    """Test successfully updating a feature in a layer and adding a picture."""
    layer_id, feature_id = layer_with_feature_for_update

    update_payload = {
        "name": "Updated Feature Name",
        "description": "This feature has been successfully updated.",
        "municipality": "Updated Municipality",
        "region": "Updated Region",
        "area_ha": 123.45,
        "date": "2025-06-15",
        "owner": "New Test Owner",
        "person_responsible": "New Test Responsible Person",
        "pictures_json": "[]",
    }

    with open("data/test.jpeg", "rb") as f:
        picture_content = f.read()

    files = [("new_pictures", ("test.jpeg", picture_content, "image/jpeg"))]

    response = await client.patch(
        f"/layer/{layer_id}/area/{feature_id}",
        data=update_payload,
        files=files,
        headers=auth_headers,
    )

    assert response.status_code == 200, f"Failed to update feature: {response.text}"
    updated_feature = response.json()

    assert updated_feature["id"] == feature_id
    assert updated_feature["type"] == "Feature"

    props = updated_feature["properties"]
    assert props["name"] == update_payload["name"]
    assert props["description"] == update_payload["description"]
    assert props["municipality"] == update_payload["municipality"]
    assert props["region"] == update_payload["region"]
    assert props["area_ha"] == update_payload["area_ha"]
    assert props["date"] == update_payload["date"]
    assert props["owner"] == update_payload["owner"]
    assert props["person_responsible"] == update_payload["person_responsible"]
    assert props["layer_id"] == layer_id

    # Check for the new picture
    assert "pictures" in props
    assert len(props["pictures"]) == 1
    new_picture = props["pictures"][0]
    assert "id" in new_picture
    assert "bucket_url" in new_picture
    assert new_picture["name"] == "test.jpeg"
    assert new_picture["is_visible"] is True

    assert "updated_ts" in props and props["updated_ts"] is not None
    if "created_ts" in props and props["created_ts"] is not None:
        assert props["updated_ts"] >= props["created_ts"]


@pytest.mark.order(order_num + 12)
@pytest.mark.asyncio
async def test_update_feature_pictures(
    client: httpx.AsyncClient,
    layer_with_feature_for_update,
    auth_headers,
    prod_monkeypatch_get_async_context_db,
):
    """Test deleting and adding pictures to a feature."""
    layer_id, feature_id = layer_with_feature_for_update

    # Step 1: Add a picture first to have something to delete
    with open("data/test.jpeg", "rb") as f:
        picture_content = f.read()

    add_files = [("new_pictures", ("initial.jpeg", picture_content, "image/jpeg"))]
    add_payload = {"pictures_json": "[]"}

    add_response = await client.patch(
        f"/layer/{layer_id}/area/{feature_id}",
        data=add_payload,
        files=add_files,
        headers=auth_headers,
    )
    assert add_response.status_code == 200
    feature_with_pic = add_response.json()
    assert len(feature_with_pic["properties"]["pictures"]) == 1
    pic_to_delete_id = feature_with_pic["properties"]["pictures"][0]["id"]

    # Step 2: Delete the picture by passing an empty pictures_json
    delete_payload = {"pictures_json": "[]"}
    delete_response = await client.patch(
        f"/layer/{layer_id}/area/{feature_id}",
        data=delete_payload,
        headers=auth_headers,
    )
    assert delete_response.status_code == 200
    feature_no_pics = delete_response.json()
    assert (
        "pictures" not in feature_no_pics["properties"]
        or len(feature_no_pics["properties"]["pictures"]) == 0
    )

    # Step 3: Add two pictures in the same request
    with open("data/test.jpeg", "rb") as f:
        picture_content_1 = f.read()
    with open("data/test.jpeg", "rb") as f:
        picture_content_2 = f.read()

    add_two_files = [
        ("new_pictures", ("new1.jpeg", picture_content_1, "image/jpeg")),
        ("new_pictures", ("new2.jpeg", picture_content_2, "image/jpeg")),
    ]
    add_two_payload = {"pictures_json": "[]"}

    add_two_response = await client.patch(
        f"/layer/{layer_id}/area/{feature_id}",
        data=add_two_payload,
        files=add_two_files,
        headers=auth_headers,
    )
    assert add_two_response.status_code == 200
    feature_with_two_pics = add_two_response.json()

    props = feature_with_two_pics["properties"]
    assert "pictures" in props
    assert len(props["pictures"]) == 2

    pic1 = props["pictures"][0]
    pic2 = props["pictures"][1]

    assert pic1["id"] != pic_to_delete_id
    assert pic2["id"] != pic_to_delete_id
    assert pic1["id"] != pic2["id"]
    assert pic1["name"] == "new1.jpeg"
    assert pic2["name"] == "new2.jpeg"


@pytest.mark.order(order_num + 14)
@pytest.mark.asyncio
async def test_update_layer_bulk_images_from_folder(
    client: httpx.AsyncClient,
    layer_with_feature_for_update,
    auth_headers,
    prod_monkeypatch_get_async_context_db,
):
    """Upload images for a single area using update_layer bulk_images/bulk_area_ids.
    Images are taken from data/test_images/test_area as the frontend would send them.
    """
    layer_id, feature_id = layer_with_feature_for_update

    images_dir = Path("data/test_images/test_area")
    assert images_dir.exists() and images_dir.is_dir(), "images folder missing"

    # Collect images (jpg/jpeg)
    image_paths = sorted(
        list(images_dir.glob("*.jpg")) + list(images_dir.glob("*.jpeg"))
    )
    assert len(image_paths) > 0, "No images found in test folder"

    # Build a multipart payload including both files and repeated bulk_area_ids fields
    files: list[tuple[str, tuple]] = []
    for p in image_paths:
        content = p.read_bytes()
        files.append(("bulk_images", (p.name, content, "image/jpeg")))
        # Include aligned area id as a separate multipart field (no filename)
        files.append(("bulk_area_ids", (None, feature_id)))

    # Send PATCH to update_layer with bulk images and aligned area ids
    resp = await client.patch(
        f"/layer/{layer_id}", files=files, headers=auth_headers
    )
    assert resp.status_code == 200, f"Bulk image upload failed: {resp.text}"

    # Fetch the feature via the feature update
