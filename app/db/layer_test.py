from datetime import datetime, timezone
import pytest
from uuid import UUID

from sqlalchemy import text

from app.db import connection
from app.db.models.layer import Layer
from app.db.layer import (
    create_layer,
    delete_layer,
    delete_layer_by_id,
    get_layer_by_id,
    get_all_layers,
    get_layer_by_name,
    get_layers_by_symbol,
    update_layer,
)
from app.db.connection_mock import monkeypatch_get_async_context_db, setup_and_teardown

pytestmark = pytest.mark.order(1)


@pytest.fixture(scope="session")
def layer_data():
    return {
        "name": "Test Layer",
        "color_code": "#FF0000",
        "symbol": "TL",
        "description": "Test layer description",
        "original_properties": {"key": "value"},
    }


@pytest.fixture(scope="session")
def layer(layer_data):
    layer = Layer()
    for key, value in layer_data.items():
        setattr(layer, key, value)
    return layer


@pytest.fixture(scope="session")
async def created_layer(layer, monkeypatch_get_async_context_db):
    async with connection.get_async_context_db() as session:
        created = await create_layer(session, layer)
        return created


@pytest.mark.asyncio
@pytest.mark.order(1)
async def test_create_layer(layer, created_layer, monkeypatch_get_async_context_db):
    assert created_layer.id is not None
    assert isinstance(created_layer.id, UUID)
    assert created_layer.name == layer.name


@pytest.mark.asyncio
@pytest.mark.order(2)
async def test_layer_values_match(layer_data, created_layer):
    assert created_layer.name == layer_data["name"]
    assert created_layer.color_code == layer_data["color_code"]
    assert created_layer.symbol == layer_data["symbol"]
    assert created_layer.description == layer_data["description"]
    assert created_layer.original_properties == layer_data["original_properties"]


@pytest.mark.asyncio
@pytest.mark.order(3)
async def test_get_layer_by_id(created_layer, monkeypatch_get_async_context_db):
    async with connection.get_async_context_db() as session:
        fetched_layer = await get_layer_by_id(session, str(created_layer.id))
        assert fetched_layer is not None
        assert fetched_layer.id == created_layer.id


@pytest.mark.asyncio
@pytest.mark.order(4)
async def test_get_layer_by_name(created_layer, monkeypatch_get_async_context_db):
    async with connection.get_async_context_db() as session:
        fetched_layer = await get_layer_by_name(session, created_layer.name)
        assert fetched_layer is not None
        assert fetched_layer.name == created_layer.name


@pytest.mark.asyncio
@pytest.mark.order(5)
async def test_get_layers_by_symbol(created_layer, monkeypatch_get_async_context_db):
    async with connection.get_async_context_db() as session:
        layers = await get_layers_by_symbol(session, created_layer.symbol)
        assert len(layers) > 0
        assert layers[0].symbol == created_layer.symbol


@pytest.mark.asyncio
@pytest.mark.order(6)
async def test_get_all_layers(created_layer, monkeypatch_get_async_context_db):
    async with connection.get_async_context_db() as session:
        layers = await get_all_layers(session)
        assert len(layers) > 0
        assert any(layer.id == created_layer.id for layer in layers)


@pytest.mark.asyncio
@pytest.mark.order(7)
async def test_update_layer(created_layer, monkeypatch_get_async_context_db):
    updated_name = "Updated Layer Name"
    updated_symbol = "UL"

    async with connection.get_async_context_db() as session:
        layer = await get_layer_by_id(session, str(created_layer.id))
        assert layer is not None
        layer.name = updated_name
        layer.symbol = updated_symbol
        updated = await update_layer(session, layer)
        assert updated is not None
        assert updated.name == updated_name
        assert updated.symbol == updated_symbol


@pytest.mark.asyncio
@pytest.mark.order(8)
async def test_delete_layer(created_layer, monkeypatch_get_async_context_db):
    async with connection.get_async_context_db() as session:
        result = await delete_layer(session, created_layer)
        assert result is True

        fetched = await get_layer_by_id(session, str(created_layer.id))
        assert fetched is None


@pytest.mark.asyncio
@pytest.mark.order(9)
async def test_delete_layer_by_id(layer_data, monkeypatch_get_async_context_db):
    async with connection.get_async_context_db() as session:
        new_layer = Layer()
        for key, value in layer_data.items():
            setattr(new_layer, key, value)
        created = await create_layer(session, new_layer)

        result = await delete_layer_by_id(session, str(created.id))
        assert result is True

        fetched = await get_layer_by_id(session, str(created.id))
        assert fetched is None


@pytest.mark.asyncio
@pytest.mark.order(10)
async def test_spatial_index_creation(layer_data, monkeypatch_get_async_context_db):
    async with connection.get_async_context_db() as session:
        new_layer = Layer()
        for key, value in layer_data.items():
            setattr(new_layer, key, value)
        created = await create_layer(session, new_layer)

        # Verify index exists
        result = await session.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :index_name)"
            ),
            {"index_name": f"idx_area_geom_layer_{created.id}"},
        )
        assert result.scalar() is True

        # Cleanup
        await delete_layer(session, created)
