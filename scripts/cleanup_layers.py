import httpx
import asyncio
import pytest
import sys
from uuid import UUID

from app.config import get_settings
from app.db.prod_connection_mock import prod_monkeypatch_get_async_context_db
from app.main import app, lifespan
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


def verify_sandbox_environment():
    """Verify that we're pointing to a sandbox GeoServer instance."""
    geoserver_url = settings.geoserver_url

    if "sandbox" not in geoserver_url.lower():
        logger.error(
            f"SAFETY CHECK FAILED: GeoServer URL '{geoserver_url}' does not contain 'sandbox'"
        )
        logger.error("This script should only run against sandbox environments!")
        logger.error("Exiting without performing any actions.")
        sys.exit(1)

    logger.info(
        f"Safety check passed: GeoServer URL '{geoserver_url}' verified as sandbox environment"
    )


async def get_auth_headers():
    """Get OAuth2 token from Zitadel using client credentials flow"""
    token_url = f"{settings.zitadel_domain}/oauth/v2/token"

    data = {
        "grant_type": "client_credentials",
        "client_id": settings.zitadel_test_client_id,
        "client_secret": settings.zitadel_test_client_secret,
        "scope": f"openid email profile offline_access urn:zitadel:iam:org:project:roles urn:zitadel:iam:org:project:id:{settings.zitadel_project_id}:aud",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if response.status_code != 200:
            raise Exception(f"Failed to get auth token: {response.text}")

        token_data = response.json()
        return {"Authorization": f"Bearer {token_data['access_token']}"}


@pytest.mark.asyncio
async def test_cleanup_all_layers(prod_monkeypatch_get_async_context_db):
    """Get all layers and delete them."""
    # Perform safety check first
    verify_sandbox_environment()

    logger.info("Starting cleanup of all layers")

    # Get auth headers for API calls
    auth_headers = await get_auth_headers()

    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            # Get all layers
            response = await client.get("/layers", headers=auth_headers)

            if response.status_code != 200:
                logger.error(f"Failed to fetch layers: {response.text}")
                return

            layers = response.json()
            logger.info(f"Found {len(layers)} layers to delete")

            if not layers:
                logger.info("No layers found to delete. Exiting.")
                return

            # Optional: Add a confirmation prompt
            confirmation = input(
                f"Are you sure you want to delete {len(layers)} layers? (yes/no): "
            )
            if confirmation.lower() not in ["yes", "y"]:
                logger.info("Operation cancelled by user.")
                return

            # Delete each layer
            for layer in layers:
                layer_id = layer["id"]
                layer_name = layer["name"]
                logger.info(f"Deleting layer: {layer_name} (ID: {layer_id})")
                print(layer)

                try:
                    delete_response = await client.delete(
                        f"/layer/{layer_id}", headers=auth_headers
                    )

                    if delete_response.status_code == 200:
                        logger.info(f"Successfully deleted layer: {layer_name}")
                    else:
                        logger.error(
                            f"Failed to delete layer {layer_name}: {delete_response.text}"
                        )
                except Exception as e:
                    logger.error(f"Error deleting layer {layer_name}: {str(e)}")

            logger.info("Layer cleanup completed")


# This allows running the script directly with pytest
if __name__ == "__main__":
    logger.info("Running layer cleanup script")
    # This runs the test function with the connection mock
    pytest.main(["-xvs", __file__])
