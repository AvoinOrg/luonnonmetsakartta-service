# forest_area_test.py

from datetime import datetime, timezone
import pytest
from uuid import UUID
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon

from app.db import connection
from app.db.models.forest_area import ForestArea
from app.db.forest_area import (
    create_forest_area,
    delete_forest_area,
    delete_forest_area_by_id,
    delete_forest_area_by_layer_id,
    get_forest_area_by_id,
    get_all_forest_areas,
    get_forest_area_by_name,
    get_forest_areas_by_municipality,
    get_forest_areas_by_layer_id,
    get_forest_areas_centroids_by_layer_id,
    update_forest_area,
)
from app.db.connection_mock import monkeypatch_get_async_context_db, setup_and_teardown

pytestmark = pytest.mark.order(2)


@pytest.fixture(scope="session")
def test_polygon():
    # Create a simple polygon for testing
    return Polygon([(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)])


@pytest.fixture(scope="session")
def forest_area_data(test_polygon):
    return {
        "name": "Test Forest Area",
        "layer_id": "12345678-1234-5678-1234-567812345678",
        "description": {"details": "Test forest area description"},
        "pictures": [{"url": "test.jpg"}],
        "municipality": "Test City",
        "geometry": from_shape(test_polygon, srid=3067),
        "original_properties": {"key": "value"},
    }


@pytest.fixture(scope="session")
def forest_area(forest_area_data):
    area = ForestArea()
    for key, value in forest_area_data.items():
        setattr(area, key, value)
    return area


@pytest.fixture(scope="session")
async def created_forest_area(forest_area, monkeypatch_get_async_context_db):
    async with connection.get_async_context_db() as session:
        created = await create_forest_area(session, forest_area)
        return created


@pytest.mark.asyncio
@pytest.mark.order(101)
async def test_create_forest_area(forest_area, created_forest_area):
    assert created_forest_area.id is not None
    assert isinstance(created_forest_area.id, UUID)
    assert created_forest_area.name == forest_area.name


@pytest.mark.asyncio
@pytest.mark.order(102)
async def test_forest_area_values_match(forest_area_data, created_forest_area):
    assert created_forest_area.name == forest_area_data["name"]
    assert str(created_forest_area.layer_id) == forest_area_data["layer_id"]
    assert created_forest_area.description == forest_area_data["description"]
    assert created_forest_area.pictures == forest_area_data["pictures"]
    assert created_forest_area.municipality == forest_area_data["municipality"]
    assert (
        created_forest_area.original_properties
        == forest_area_data["original_properties"]
    )
    # Geometry comparison needs special handling due to PostGIS type
    assert created_forest_area.geometry is not None


@pytest.mark.asyncio
@pytest.mark.order(103)
async def test_get_forest_area_by_id(
    created_forest_area, monkeypatch_get_async_context_db
):
    async with connection.get_async_context_db() as session:
        fetched_area = await get_forest_area_by_id(session, str(created_forest_area.id))
        assert fetched_area is not None
        assert fetched_area.id == created_forest_area.id


@pytest.mark.asyncio
@pytest.mark.order(104)
async def test_get_forest_area_by_name(
    created_forest_area, monkeypatch_get_async_context_db
):
    async with connection.get_async_context_db() as session:
        fetched_area = await get_forest_area_by_name(session, created_forest_area.name)
        assert fetched_area is not None
        assert fetched_area.name == created_forest_area.name


@pytest.mark.asyncio
@pytest.mark.order(105)
async def test_get_forest_areas_by_layer_id(
    created_forest_area, monkeypatch_get_async_context_db
):
    async with connection.get_async_context_db() as session:
        areas = await get_forest_areas_by_layer_id(
            session, str(created_forest_area.layer_id)
        )
        assert len(areas) > 0
        assert areas[0].layer_id == created_forest_area.layer_id


@pytest.mark.asyncio
@pytest.mark.order(105)
async def test_get_forest_areas_centroids_by_layer_id(
    created_forest_area, monkeypatch_get_async_context_db
):
    async with connection.get_async_context_db() as session:
        areas = await get_forest_areas_centroids_by_layer_id(
            session, str(created_forest_area.layer_id)
        )
        assert len(areas) > 0
        assert areas[0].layer_id == created_forest_area.layer_id
        assert areas[0].centroid is not None
        assert areas[0].geometry is None


@pytest.mark.asyncio
@pytest.mark.order(106)
async def test_get_forest_areas_by_municipality(
    created_forest_area, monkeypatch_get_async_context_db
):
    async with connection.get_async_context_db() as session:
        areas = await get_forest_areas_by_municipality(
            session, created_forest_area.municipality
        )
        assert len(areas) > 0
        assert areas[0].municipality == created_forest_area.municipality


@pytest.mark.asyncio
@pytest.mark.order(107)
async def test_get_all_forest_areas(
    created_forest_area, monkeypatch_get_async_context_db
):
    async with connection.get_async_context_db() as session:
        areas = await get_all_forest_areas(session)
        assert len(areas) > 0
        assert any(area.id == created_forest_area.id for area in areas)


@pytest.mark.asyncio
@pytest.mark.order(108)
async def test_update_forest_area(
    created_forest_area, monkeypatch_get_async_context_db
):
    updated_name = "Updated Forest Area Name"
    updated_municipality = "Updated City"

    async with connection.get_async_context_db() as session:
        area = await get_forest_area_by_id(session, str(created_forest_area.id))
        assert area is not None
        area.name = updated_name
        area.municipality = updated_municipality
        updated = await update_forest_area(session, area)
        assert updated is not None
        assert updated.name == updated_name
        assert updated.municipality == updated_municipality


@pytest.mark.asyncio
@pytest.mark.order(109)
async def test_delete_forest_area(
    created_forest_area, monkeypatch_get_async_context_db
):
    async with connection.get_async_context_db() as session:
        result = await delete_forest_area(session, created_forest_area)
        assert result is True
        fetched = await get_forest_area_by_id(session, str(created_forest_area.id))
        assert fetched is None


@pytest.mark.asyncio
@pytest.mark.order(110)
async def test_delete_forest_area_by_id(
    forest_area_data, monkeypatch_get_async_context_db
):
    async with connection.get_async_context_db() as session:
        new_area = ForestArea()
        for key, value in forest_area_data.items():
            setattr(new_area, key, value)
        created = await create_forest_area(session, new_area)

        result = await delete_forest_area_by_id(session, str(created.id))
        assert result is True
        fetched = await get_forest_area_by_id(session, str(created.id))
        assert fetched is None


@pytest.mark.asyncio
@pytest.mark.order(110)
async def test_delete_forest_area_by_layer_id(
    forest_area_data, monkeypatch_get_async_context_db
):
    async with connection.get_async_context_db() as session:
        new_area = ForestArea()
        for key, value in forest_area_data.items():
            setattr(new_area, key, value)
        created = await create_forest_area(session, new_area)

        result = await delete_forest_area_by_layer_id(session, str(created.layer_id))
        assert result is True
        fetched = await get_forest_area_by_id(session, str(created.id))
        assert fetched is None
