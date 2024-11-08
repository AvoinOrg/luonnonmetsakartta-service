import os
from functools import lru_cache

from pydantic import BaseSettings

from app.utils.logger import get_logger
from dotenv import load_dotenv

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


@lru_cache
def get_settings():
    logger.info("Loading config settings from the environment...")
    return Settings()
