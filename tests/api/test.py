from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import pytest_asyncio
import httpx

from app.main import app, lifespan

@pytest.fixture(
    scope="session"
)  # I add the following fixture to configure asyncio in pytest
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
async def client():
    async with lifespan(app):  # lifespan does not return the asgi app
        transport = httpx.ASGITransport(app=app)  # type:ignore
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            yield client


@pytest_asyncio.fixture(scope="session")
async def response_data(client):
    params = {}

    response = await client.get(f"/hello", params=params)
    return response


@pytest.mark.order(1)
@pytest.mark.asyncio
async def test_response_is_ok(response_data):
    assert response_data.status_code == 200
