from logging.config import fileConfig
import alembic_postgresql_enum
import os

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

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


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and reflected and compare_to is None:
        # Exclude tables that are reflected from the database but not in metadata
        # This ignores extension-created tables like PostGIS tables
        return False
    return True


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
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
