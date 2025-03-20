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
        files = [
            (
                "zip_file",
                ("test.zip", mock_shapefile, "application/zip"),
            )
        ]

        data = {
            "name": "Test Layer",
            "description": "Test Description",
            "is_hidden": False,
        }

        response = await client.post(
            "/layer", files=files, data=data, headers=auth_headers
        )

        assert response.status_code == 200
        result = response.json()
        assert result["name"] == data["name"]
        assert result["description"] == data["description"]
        assert result["is_hidden"] is not None and not result["is_hidden"]
        assert "id" in result

        if "id" in result:
            layer_id = result["id"]

        response = await client.get(f"/layer/{layer_id}", headers=auth_headers)
        assert response.status_code == 200
        result = response.json()
        assert result["name"] == data["name"]
        assert result["description"] == data["description"]
        assert result["is_hidden"] is not None and not result["is_hidden"]
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
        files = [
            (
                "zip_file",
                ("test_data.zip", real_shapefile, "application/zip"),
            )
        ]

        data = {
            "name": "Natural Forests",
            "description": "Imported natural forest areas",
        }

        response = await client.post(
            "/layer", files=files, data=data, headers=auth_headers
        )

        assert response.status_code == 200
        result = response.json()
        assert result["name"] == data["name"]
        assert result["description"] == data["description"]
        assert result["is_hidden"] is not None and result["is_hidden"]
        assert "id" in result

        if "id" in result:
            layer_id = result["id"]

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
        data={"name": "Test Layer 1", "description": "First test layer"},
        headers=auth_headers,
    )
    assert response1.status_code == 200
    layer_ids.append(response1.json()["id"])

    # Create visible layer
    response2 = await client.post(
        "/layer",
        files=files,
        data={
            "name": "Test Layer 2",
            "description": "Second test layer",
            "is_hidden": False,
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
    assert len(layers) == 1  # Only public layer visible

    # Verify only visible layer is present
    layer_names = [layer["name"] for layer in layers]
    assert "Test Layer 1" not in layer_names  # Hidden layer
    assert "Test Layer 2" in layer_names  # Public layer

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
    assert len(layers) == 1  # Only public layer visible

    # Verify only visible layer is present
    layer_names = [layer["name"] for layer in layers]
    assert "Test Layer 1" not in layer_names
    assert "Test Layer 2" in layer_names

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
    assert len(layers) == 1

    layer_names = [layer["name"] for layer in layers]
    assert "Test Layer 1" not in layer_names
    assert "Test Layer 2" in layer_names

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
    assert len(layers) == 2  # Both layers visible

    layer_names = [layer["name"] for layer in layers]
    assert "Test Layer 1" in layer_names
    assert "Test Layer 2" in layer_names

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
            "name": "Test Layer 1",
            "description": "First test layer",
            "is_hidden": True,
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
        "name": "Updated Test Layer",
        "description": "Updated description",
        "is_hidden": False,
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
        "name": "Updated Test Layer",
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
        "name": "Updated Test Layer",
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
        "name": "Updated Test Layer",
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
