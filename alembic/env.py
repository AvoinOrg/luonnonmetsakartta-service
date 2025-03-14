from logging.config import fileConfig
import alembic_postgresql_enum
import os

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
from alembic.autogenerate import renderers
import geoalchemy2
from geoalchemy2 import types as geo_types

from app.db.models.base import Base
from app.db.models.forest_layer import ForestLayer
from app.db.models.forest_area import ForestArea
from app.utils.general import str_to_bool

env_vars = os.environ
# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

is_testing = config.get_main_option("is_testing", "False")

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_url():
    if is_testing == "True":
        password = env_vars["TEST_POSTGRES_PASSWORD"]
        username = env_vars["TEST_POSTGRES_USER"]
        host = env_vars["TEST_POSTGRES_HOST"]
        port = env_vars["TEST_POSTGRES_PORT"]
        database = env_vars["TEST_POSTGRES_DB"]

    else:
        if str_to_bool(env_vars.get("IS_PRODUCTION", "False")):
            password = env_vars["POSTGRES_PASSWORD"]
            username = env_vars["POSTGRES_USER"]
            host = env_vars["POSTGRES_HOST"]
            port = env_vars["POSTGRES_PORT"]
            database = env_vars["POSTGRES_DB"]
        else:
            password = env_vars["DEV_POSTGRES_PASSWORD"]
            username = env_vars["DEV_POSTGRES_USER"]
            host = env_vars["DEV_POSTGRES_HOST"]
            port = env_vars["DEV_POSTGRES_PORT"]
            database = env_vars["DEV_POSTGRES_DB"]

        # If you need to reconstruct the URL string manually without masking:
    db_url = f"postgresql+psycopg2://{username}:{password}@{host}:{port}/{database}"

    return db_url


config.set_main_option("sqlalchemy.url", get_url())


def is_geometry_index(object, name, type_):
    # Check if it's an index and name contains geometry-related patterns
    # Use "_manual_" in index name to skip manually created indices
    if type_ == "index" and "_manual_" not in name.lower():
        geometry_patterns = [
            "_geometry",
            "_geom_",
            "geography_columns",
            "geometry_columns",
        ]
        return any(pattern in name.lower() for pattern in geometry_patterns)
    return False


def include_object(object, name, type_, reflected, compare_to):
    # Skip geometry indices
    if is_geometry_index(object, name, type_):
        return False

    # Skip tables that exist in DB but not in models
    if type_ == "table" and reflected and compare_to is None:
        return False

    return True


def render_item(type_, obj, autogen_context):
    """Custom rendering for specific items during autogeneration."""
    if type_ == 'type':
        if isinstance(obj, geo_types.Geometry):
            autogen_context.imports.add('from geoalchemy2 import Geometry')
            args = []
            if obj.geometry_type != 'GEOMETRY':
                args.append(repr(obj.geometry_type))
            if obj.srid != -1:
                args.append(f"srid={obj.srid}")
            if obj.dimension != 2:
                args.append(f"dimension={obj.dimension}")
            if obj.spatial_index is not None:
                args.append(f"spatial_index={obj.spatial_index}")
            return f"Geometry({', '.join(args)})"
        elif isinstance(obj, geo_types.Geography):
            autogen_context.imports.add('from geoalchemy2 import Geography')
            args = []
            if obj.geometry_type != 'GEOGRAPHY':
                args.append(repr(obj.geometry_type))
            if obj.srid != -1:
                args.append(f"srid={obj.srid}")
            if obj.dimension != 2:
                args.append(f"dimension={obj.dimension}")
            if obj.spatial_index is not None:
                args.append(f"spatial_index={obj.spatial_index}")
            return f"Geography({', '.join(args)})"
    # Return False to let Alembic use the default rendering for other types
    return False



def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
        render_item=render_item,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_item=render_item,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
