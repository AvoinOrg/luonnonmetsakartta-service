from datetime import datetime, timezone
import pytest
from uuid import UUID

from sqlalchemy import text

from app.db import connection
from app.db.models.forest_layer import ForestLayer
from app.db.forest_layer import (
    create_forest_layer,
    delete_forest_layer,
    delete_forest_layer_by_id,
    get_forest_layer_by_id,
    get_all_forest_layers,
    get_forest_layer_by_name,
    get_forest_layers_by_symbol,
    update_forest_layer,
    get_index_name_for_id,
)
from app.db.connection_mock import monkeypatch_get_async_context_db, setup_and_teardown

pytestmark = pytest.mark.order(201)


@pytest.fixture(scope="session")
def forest_layer_data():
    return {
        "name": "Test Forest Layer",
        "color_code": "#FF0000",
        "symbol": "TFL",
        "description": "Test forest layer description",
        "col_options": {
            "indexingStrategy": "name_municipality",
            "idCol": "id",
            "nameCol": "name",
            "municipalityCol": "municipality",
            "regionCol": "region",
            "areaCol": "area",
        },
        "original_properties": {"key": "value"},
    }


@pytest.fixture(scope="session")
def forest_layer(forest_layer_data):
    forest_layer = ForestLayer()
    for key, value in forest_layer_data.items():
        setattr(forest_layer, key, value)
    return forest_layer


@pytest.fixture(scope="session")
async def created_forest_layer(forest_layer, monkeypatch_get_async_context_db):
    async with connection.get_async_context_db() as session:
        created = await create_forest_layer(session, forest_layer)
        return created


@pytest.mark.asyncio
@pytest.mark.order(201)
async def test_create_forest_layer(
    forest_layer, created_forest_layer, monkeypatch_get_async_context_db
):
    assert created_forest_layer.id is not None
    assert isinstance(created_forest_layer.id, UUID)
    assert created_forest_layer.name == forest_layer.name


@pytest.mark.asyncio
@pytest.mark.order(202)
async def test_forest_layer_values_match(forest_layer_data, created_forest_layer):
    assert created_forest_layer.name == forest_layer_data["name"]
    assert created_forest_layer.color_code == forest_layer_data["color_code"]
    assert created_forest_layer.symbol == forest_layer_data["symbol"]
    assert created_forest_layer.description == forest_layer_data["description"]
    assert (
        created_forest_layer.original_properties
        == forest_layer_data["original_properties"]
    )


@pytest.mark.asyncio
@pytest.mark.order(203)
async def test_get_forest_layer_by_id(
    created_forest_layer, monkeypatch_get_async_context_db
):
    async with connection.get_async_context_db() as session:
        fetched_layer = await get_forest_layer_by_id(
            session, str(created_forest_layer.id)
        )
        assert fetched_layer is not None
        assert fetched_layer.id == created_forest_layer.id


@pytest.mark.asyncio
@pytest.mark.order(204)
async def test_get_forest_layer_by_name(
    created_forest_layer, monkeypatch_get_async_context_db
):
    async with connection.get_async_context_db() as session:
        fetched_layer = await get_forest_layer_by_name(
            session, created_forest_layer.name
        )
        assert fetched_layer is not None
        assert fetched_layer.name == created_forest_layer.name


@pytest.mark.asyncio
@pytest.mark.order(205)
async def test_get_forest_layers_by_symbol(
    created_forest_layer, monkeypatch_get_async_context_db
):
    async with connection.get_async_context_db() as session:
        layers = await get_forest_layers_by_symbol(session, created_forest_layer.symbol)
        assert len(layers) > 0
        assert layers[0].symbol == created_forest_layer.symbol


@pytest.mark.asyncio
@pytest.mark.order(206)
async def test_get_all_forest_layers(
    created_forest_layer, monkeypatch_get_async_context_db
):
    async with connection.get_async_context_db() as session:
        layers = await get_all_forest_layers(session)
        assert len(layers) > 0
        assert any(layer.id == created_forest_layer.id for layer in layers)


@pytest.mark.asyncio
@pytest.mark.order(207)
async def test_update_forest_layer(
    created_forest_layer, monkeypatch_get_async_context_db
):
    updated_name = "Updated Forest Layer Name"
    updated_symbol = "UFL"

    async with connection.get_async_context_db() as session:
        layer = await get_forest_layer_by_id(session, str(created_forest_layer.id))
        assert layer is not None
        layer.name = updated_name
        layer.symbol = updated_symbol
        updated = await update_forest_layer(session, layer)
        assert updated is not None
        assert updated.name == updated_name
        assert updated.symbol == updated_symbol


@pytest.mark.asyncio
@pytest.mark.order(208)
async def test_delete_forest_layer(
    created_forest_layer, monkeypatch_get_async_context_db
):
    async with connection.get_async_context_db() as session:
        result = await delete_forest_layer(session, created_forest_layer)
        assert result is True

        fetched = await get_forest_layer_by_id(session, str(created_forest_layer.id))
        assert fetched is None


@pytest.mark.asyncio
@pytest.mark.order(209)
async def test_delete_forest_layer_by_id(
    forest_layer_data, monkeypatch_get_async_context_db
):
    async with connection.get_async_context_db() as session:
        new_layer = ForestLayer()
        for key, value in forest_layer_data.items():
            setattr(new_layer, key, value)
        created = await create_forest_layer(session, new_layer)

        result = await delete_forest_layer_by_id(session, str(created.id))
        assert result is True

        fetched = await get_forest_layer_by_id(session, str(created.id))
        assert fetched is None


@pytest.mark.asyncio
@pytest.mark.order(210)
async def test_spatial_index_creation(
    forest_layer_data, monkeypatch_get_async_context_db
):
    async with connection.get_async_context_db() as session:
        new_layer = ForestLayer()
        for key, value in forest_layer_data.items():
            setattr(new_layer, key, value)
        created = await create_forest_layer(session, new_layer)

        index_name = get_index_name_for_id(created.id)

        # Verify index exists
        result = await session.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :index_name)"
            ),
            {"index_name": index_name},
        )
        assert result.scalar() is True

        # Cleanup
        await delete_forest_layer(session, created)
