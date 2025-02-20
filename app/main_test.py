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
from app.db.prod_connection_mock import prod_monkeypatch_get_async_context_db

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


@pytest.mark.order(order_num)
@pytest.mark.asyncio
async def test_create_layer_success(
    client: httpx.AsyncClient, mock_shapefile, prod_monkeypatch_get_async_context_db
) -> None:
    files = [
        (
            "zip_file",
            ("test.zip", mock_shapefile, "application/zip"),
        )
    ]

    data = {"name": "Test Layer", "description": "Test Description"}

    response = await client.post("/layer", files=files, data=data)

    assert response.status_code == 200
    result = response.json()
    assert result["name"] == "Test Layer"
    assert result["description"] == "Test Description"
    assert "id" in result

    if "id" in result:
        layer_id = result["id"]
        # Cleanup
        response = await client.delete(f"/layer/{layer_id}")
        assert response.status_code == 200


@pytest.mark.order(order_num + 1)
@pytest.mark.asyncio
async def test_create_layer_missing_file(client):
    data = {"name": "Test Layer", "description": "Test Description"}

    response = await client.post(
        "/layer", files=[("zip_file", (None, None, "application/zip"))], data=data
    )

    assert response.status_code == 400  # Bad request, missing file


@pytest.mark.order(order_num + 2)
@pytest.mark.asyncio
async def test_create_layer_invalid_file(client):
    files = [
        ("shp_file", ("test.shp", b"invalid data", "application/octet-stream")),
    ]

    data = {
        "name": "Test Layer",
    }

    response = await client.post("/layer", files=files, data=data)

    assert response.status_code == 422


@pytest.mark.order(order_num + 3)
@pytest.mark.asyncio
async def test_import_real_shapefile_success(
    client, real_shapefile, prod_monkeypatch_get_async_context_db
):
    files = [
        (
            "zip_file",
            ("test_data.zip", real_shapefile, "application/zip"),
        )
    ]

    data = {"name": "Natural Forests", "description": "Imported natural forest areas"}

    response = await client.post("/layer", files=files, data=data)

    assert response.status_code == 200
    result = response.json()
    assert result["name"] == "Natural Forests"
    assert "id" in result

    if "id" in result:
        layer_id = result["id"]
        # Cleanup
        response = await client.delete(f"/layer/{layer_id}")
        assert response.status_code == 200


@pytest.mark.order(order_num + 4)
@pytest.mark.asyncio
async def test_get_layers(
    client: httpx.AsyncClient, mock_shapefile, prod_monkeypatch_get_async_context_db
):
    # Create two test layers
    files = [("zip_file", ("test.zip", mock_shapefile, "application/zip"))]
    layer_ids = []

    try:
        # Create first layer
        response1 = await client.post(
            "/layer",
            files=files,
            data={"name": "Test Layer 1", "description": "First test layer"},
        )
        assert response1.status_code == 200
        layer_ids.append(response1.json()["id"])

        # Create second layer
        response2 = await client.post(
            "/layer",
            files=files,
            data={"name": "Test Layer 2", "description": "Second test layer"},
        )
        assert response2.status_code == 200
        layer_ids.append(response2.json()["id"])

        # Get all layers
        response = await client.get("/layers")
        assert response.status_code == 200

        layers = response.json()
        assert isinstance(layers, list)
        assert len(layers) >= 2

        # Verify our test layers are present
        layer_names = [layer["name"] for layer in layers]
        assert "Test Layer 1" in layer_names
        assert "Test Layer 2" in layer_names

        # Verify layer structure
        for layer in layers:
            assert "id" in layer
            assert "name" in layer
            assert "description" in layer

    finally:
        # Cleanup - delete test layers
        for layer_id in layer_ids:
            delete_response = await client.delete(f"/layer/{layer_id}")
            assert delete_response.status_code == 200
