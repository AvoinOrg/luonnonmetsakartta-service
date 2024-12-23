import os
from functools import lru_cache

from pydantic_settings import BaseSettings
from sqlalchemy.engine import URL
from dotenv import load_dotenv

from app.utils.general import str_to_bool
from app.utils.logger import get_logger

load_dotenv()
env_vars = os.environ
logger = get_logger(__name__)


def get_pg_url(is_prod):
    if is_prod:
        return URL.create(
            "postgresql+asyncpg",
            username=env_vars["POSTGRES_USER"],
            password=env_vars["POSTGRES_PASSWORD"],
            host=env_vars["POSTGRES_HOST"],
            port=int(env_vars["POSTGRES_PORT"]),
            database=env_vars["POSTGRES_DB"],
        )
    else:
        return URL.create(
            "postgresql+asyncpg",
            username=env_vars["DEV_POSTGRES_USER"],
            password=env_vars["DEV_POSTGRES_PASSWORD"],
            host=env_vars["DEV_POSTGRES_HOST"],
            port=int(env_vars["DEV_POSTGRES_PORT"]),
            database=env_vars["DEV_POSTGRES_DB"],
        )


class Settings(BaseSettings):
    """
    BaseSettings, from Pydantic, validates the data so that when we create an instance of Settings,
     environment and testing will have types of str and bool, respectively.
    Parameters:
    Returns:
    instance of Settings
    """

    is_production: bool = str_to_bool(env_vars.get("IS_PRODUCTION", "False"))
    pg_url: URL = get_pg_url(is_production)


@lru_cache
def get_settings():
    logger.info("Loading config settings from the environment...")
    return Settings()
