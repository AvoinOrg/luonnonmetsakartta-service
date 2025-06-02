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
    zitadel_client_id: (str):
    zitadel_client_secret: (str):
    zitadel_domain: (str):
    Returns:
    instance of Settings
    """

    is_production: bool = str_to_bool(env_vars.get("IS_PRODUCTION", "False"))
    geoserver_url: str = env_vars["GEOSERVER_URL"]
    geoserver_workspace: str = env_vars["GEOSERVER_WORKSPACE"]
    geoserver_store: str = env_vars["GEOSERVER_STORE"]
    geoserver_user: str = env_vars["GEOSERVER_USER"]
    geoserver_password: str = env_vars["GEOSERVER_PASSWORD"]
    pg_url: URL = get_pg_url(is_production)
    zitadel_domain: str = os.getenv("ZITADEL_DOMAIN") or ""
    zitadel_client_id: str = os.getenv("ZITADEL_CLIENT_ID") or ""
    zitadel_client_secret: str = os.getenv("ZITADEL_CLIENT_SECRET") or ""
    zitadel_test_client_id: str = os.getenv("ZITADEL_TEST_CLIENT_ID") or ""
    zitadel_test_client_secret: str = os.getenv("ZITADEL_TEST_CLIENT_SECRET") or ""
    zitadel_test_client_id_no_roles: str = (
        os.getenv("ZITADEL_TEST_CLIENT_ID_NO_ROLES") or ""
    )
    zitadel_test_client_secret_no_roles: str = (
        os.getenv("ZITADEL_TEST_CLIENT_SECRET_NO_ROLES") or ""
    )
    zitadel_project_id: str = os.getenv("ZITADEL_PROJECT_ID") or ""
    zitadel_project_editor_role: str = os.getenv("ZITADEL_PROJECT_EDITOR_ROLE") or ""
    # zitadel_project_admin_role: str = os.getenv("ZITADEL_PROJECT_ADMIN_ROLE") or ""


@lru_cache
def get_settings():
    logger.info("Loading config settings from the environment...")
    return Settings()
