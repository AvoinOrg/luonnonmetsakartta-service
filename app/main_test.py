# test_main.py
import zipfile
import pytest
import httpx
from pathlib import Path
import geopandas as gpd
from shapely.geometry import Polygon
import tempfile

from app.main import app, lifespan
from app.utils.logger import get_logger
from app.db.connection_mock import monkeypatch_get_async_context_db
from app.config import get_settings

settings = get_settings()

logger = get_logger(__name__)
pytestmark = pytest.mark.order(103)
order_num = 1000


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


@pytest.mark.order(order_num + 1)
@pytest.mark.asyncio
async def test_create_layer_missing_file(
    client, auth_headers, monkeypatch_get_async_context_db
):
    data = {"name": "Test Layer", "description": "Test Description"}

    response = await client.post(
        "/layer",
        files=[("zip_file", (None, None, "application/zip"))],
        data=data,
        headers=auth_headers,
    )

    assert response.status_code == 400  # Bad request, missing file


@pytest.mark.order(order_num + 1)
@pytest.mark.asyncio
async def test_create_layer_unauthorized(
    client: httpx.AsyncClient,
    mock_shapefile,
    invalid_auth_headers,
    monkeypatch_get_async_context_db,
):
    """Test that creating a layer fails with invalid authentication"""
    files = [("zip_file", ("test.zip", mock_shapefile, "application/zip"))]
    data = {
        "name": "Test Layer",
        "description": "Test Description",
    }

    response = await client.post(
        "/layer", files=files, data=data, headers=invalid_auth_headers
    )

    assert response.status_code == 401


@pytest.mark.order(order_num + 1)
@pytest.mark.asyncio
async def test_create_layer_no_permissions(
    client: httpx.AsyncClient,
    mock_shapefile,
    auth_headers_no_roles,
    monkeypatch_get_async_context_db,
):
    """Test that creating a layer fails when user has no permissions"""
    files = [("zip_file", ("test.zip", mock_shapefile, "application/zip"))]
    data = {
        "name": "Test Layer",
        "description": "Test Description",
    }

    response = await client.post(
        "/layer", files=files, data=data, headers=auth_headers_no_roles
    )

    assert response.status_code == 403


@pytest.mark.order(order_num + 2)
@pytest.mark.asyncio
async def test_create_layer_invalid_file(
    client, auth_headers, monkeypatch_get_async_context_db
):
    files = [
        ("shp_file", ("test.shp", b"invalid data", "application/octet-stream")),
    ]

    data = {
        "name": "Test Layer",
    }

    response = await client.post("/layer", files=files, data=data, headers=auth_headers)

    assert response.status_code == 422


@pytest.mark.order(order_num + 12)
@pytest.mark.asyncio
async def test_validate_admin(client: httpx.AsyncClient, auth_headers):
    """Test admin validation with valid service user token"""
    response = await client.get("/admin/validate", headers=auth_headers)
    assert response.status_code == 200


@pytest.mark.order(order_num + 13)
@pytest.mark.asyncio
async def test_validate_admin_unauthorized(
    client: httpx.AsyncClient, invalid_auth_headers
):
    """Test that admin validation fails with invalid token"""
    # Test with invalid token
    response = await client.get("/admin/validate", headers=invalid_auth_headers)

    assert response.status_code == 401


@pytest.mark.order(order_num + 14)
@pytest.mark.asyncio
async def test_validate_admin_no_permissions(
    client: httpx.AsyncClient, auth_headers_no_roles
):
    """Test that admin validation fails with invalid token"""
    # Test with invalid token
    response = await client.get("/admin/validate", headers=auth_headers_no_roles)

    assert response.status_code == 403
