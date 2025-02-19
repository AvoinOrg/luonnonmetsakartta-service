import asyncio
import pytest
import os
import importlib
import pkgutil
import inspect
from contextlib import asynccontextmanager
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from collections.abc import AsyncGenerator
from alembic.config import Config
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import connection
from app.db.models.base import Base
from app.utils.logger import get_logger
from app.types.general import used_db_types

logger = get_logger(__name__)

TEST_POSTGRES_USER = os.getenv("TEST_POSTGRES_USER", "test-test")
TEST_POSTGRES_PASSWORD = os.getenv("TEST_POSTGRES_PASSWORD", "test-test-test")
TEST_POSTGRES_HOST = os.getenv("TEST_POSTGRES_HOST", "test-postgres-test")
TEST_POSTGRES_PORT = os.getenv("TEST_POSTGRES_PORT", "5432")
TEST_POSTGRES_DB = os.getenv("TEST_POSTGRES_DB", "test-postgres-test")

TEST_DATABASE_URL = f"postgresql+asyncpg://{TEST_POSTGRES_USER}:{TEST_POSTGRES_PASSWORD}@{TEST_POSTGRES_HOST}:{TEST_POSTGRES_PORT}/{TEST_POSTGRES_DB}"

# @pytest.fixture(scope="session")
# def event_loop():
#     loop = asyncio.get_event_loop_policy().new_event_loop()
#     yield loop
#     loop.close()


# @pytest.fixture(scope="session")
# async def async_test_engine():
#     # Create a test database engine
#     test_engine = create_async_engine(
#         TEST_DATABASE_URL,
#         future=True,
#         echo=False,
#         poolclass=NullPool,
#     )
#     yield test_engine
#     await test_engine.dispose()


# @pytest.fixture(scope="session")
# async def async_test_session_maker(async_test_engine):
#     # Create a session maker bound to the test engine
#     async_session_maker = sessionmaker(
#         async_test_engine, class_=AsyncSession, expire_on_commit=False
#     )
#     yield async_session_maker


# @asynccontextmanager
# async def get_async_context_db() -> AsyncGenerator:
#     async with base_async_db_context(
#         AsyncSessionLocal, f"ASYNC Pool: {engine.pool.status()}"
#     ) as session:
#         yield session


# @asynccontextmanager
# async def mock_get_async_context_db(async_test_session_maker) -> AsyncGenerator:
#     async with async_test_session_maker() as session:
#         yield session


@pytest.fixture(scope="session")
def monkeypatch_get_async_context_db():
    # Use monkeypatch to replace get_async_context_db with mock_get_async_context_db
    test_engine = create_async_engine(
        TEST_DATABASE_URL,
        future=True,
        echo=False,
        poolclass=NullPool,
    )

    AsyncSessionLocal = async_sessionmaker(
        test_engine, autoflush=False, expire_on_commit=False
    )

    @asynccontextmanager
    async def mock_get_async_context_db() -> AsyncGenerator:
        async with connection.base_async_db_context(
            AsyncSessionLocal, f"ASYNC Pool: {test_engine.pool.status()}"
        ) as session:
            yield session

    from _pytest.monkeypatch import MonkeyPatch

    m = MonkeyPatch()
    m.setattr(
        connection,
        "get_async_context_db",
        lambda: mock_get_async_context_db(),
    )


async def async_setup():
    async with connection.get_async_context_db() as session:
        engine = session.bind
        url = str(engine.url)
        assert TEST_POSTGRES_DB in url
        assert TEST_POSTGRES_USER in url
        assert TEST_POSTGRES_HOST in url
        assert TEST_POSTGRES_PORT in url

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("is_testing", "True")
        await session.begin()
        # await drop_all_tables_and_types(session)
        command.downgrade(alembic_cfg, "base")
        await session.commit()

        # Run Alembic migrations to create tables
        command.upgrade(alembic_cfg, "head")


async def async_teardown():
    async with connection.get_async_context_db() as session:
        await session.begin()
        # await drop_all_tables_and_types(session)
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("is_testing", "True")
        # Downgrade to the base revision
        command.downgrade(alembic_cfg, "base")
        await session.commit()


@pytest.fixture(scope="session", autouse=True)
def setup_and_teardown(request):
    marker = request.node.get_closest_marker("monkeypatch_get_async_context_db")
    request.getfixturevalue("monkeypatch_get_async_context_db")
    asyncio.run(async_setup())
    yield

    asyncio.run(async_teardown())


# async def drop_all_tables_and_types(conn: AsyncSession):
#     # Dynamically import all model modules and collect model classes
#     model_classes = []
#     models_package = importlib.import_module('app.db.models')

#     for _, name, _ in pkgutil.iter_modules(models_package.__path__):
#         if name != 'base':  # Skip base.py
#             module = importlib.import_module(f'app.db.models.{name}')
#             # Find all classes that inherit from Base
#             for _, obj in inspect.getmembers(module):
#                 if inspect.isclass(obj) and issubclass(obj, Base) and obj != Base:
#                     model_classes.append(obj)

#     # Get table names from model classes
#     table_names = [model.__tablename__ for model in model_classes]

#     # Drop tables one by one
#     for table in table_names:
#         await conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))

#     # Drop custom types
#     for db_type in used_db_types:
#         await conn.execute(text(f"DROP TYPE IF EXISTS {db_type} CASCADE"))

#     await conn.commit()
