import os
from functools import lru_cache

from pydantic_settings import BaseSettings
from sqlalchemy.engine import URL
from dotenv import load_dotenv

from app.utils.logger import get_logger

load_dotenv()
env_vars = os.environ
logger = get_logger(__name__)


class Settings(BaseSettings):
    """
    BaseSettings, from Pydantic, validates the data so that when we create an instance of Settings,
     environment and testing will have types of str and bool, respectively.
    Parameters:
    Returns:
    instance of Settings
    """
    pg_url: URL = URL.create(
        "postgresql+asyncpg",
        username=env_vars["POSTGRES_USER"],
        password=env_vars["POSTGRES_PASSWORD"],
        host=env_vars["POSTGRES_HOST"],  # Use the PgBouncer service name for STATE DB
        port=int(env_vars["POSTGRES_PORT"]),  # Default PgBouncer port
        database=env_vars["POSTGRES_DB"],
    )


@lru_cache
def get_settings():
    logger.info("Loading config settings from the environment...")
    return Settings()
