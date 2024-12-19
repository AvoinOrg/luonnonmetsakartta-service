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

logger = get_logger(__name__)
pytestmark = pytest.mark.order(103)


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
def test_shapefile():
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
def test_real_shapefile():
    zip_path = Path("data/test_data.zip")
    with open(zip_path, "rb") as f:
        return f.read()


@pytest.mark.asyncio
async def test_import_shapefile_success(
    client: httpx.AsyncClient, test_shapefile
) -> None:
    files = [
        (
            "zip_file",
            ("test.zip", test_shapefile, "application/zip"),
        )
    ]

    data = {
        "name": "Test Layer", 
        "description": "Test Description"
    }

    response = await client.post("/import-shapefile", files=files, data=data)

    assert response.status_code == 200
    result = response.json()
    assert result["name"] == "Test Layer"
    assert result["description"] == "Test Description"
    assert "id" in result


@pytest.mark.asyncio
async def test_import_shapefile_missing_file(client):
    data = {
        "name": "Test Layer", 
        "description": "Test Description"
    }

    response = await client.post(
        "/import-shapefile", 
        files=[("zip_file", (None, None, "application/zip"))],
        data=data
    )

    assert response.status_code == 400  # Bad request, missing file


@pytest.mark.asyncio
async def test_import_shapefile_invalid_file(client):
    files = [
        ("shp_file", ("test.shp", b"invalid data", "application/octet-stream")),
    ]

    data = {
        "name": "Test Layer",
    }

    response = await client.post("/import-shapefile", files=files, data=data)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_import_real_shapefile_success(client, test_real_shapefile):
    files = [
        (
            "zip_file",
            ("test_data.zip", test_real_shapefile, "application/zip"),
        )
    ]

    data = {
        "name": "Natural Forests", 
        "description": "Imported natural forest areas"
    }

    response = await client.post("/import-shapefile", files=files, data=data)

    assert response.status_code == 200
    result = response.json()
    assert result["name"] == "Natural Forests"
    assert "id" in result
