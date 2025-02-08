import os
import asyncio
import argparse
from app import config
from app.db import connection
from app.utils.geometry import import_shapefile_to_layer


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--layer-name", default="MyLayer", help="Name of the layer")
    parser.add_argument("--description", default=None, help="Layer description")
    parser.add_argument(
        "--zip",
        default="/app/data/test_data.zip",
        help="Path to zip file",
    )
    args = parser.parse_args()

    settings = config.get_settings()
    async with connection.get_async_context_db() as session:
        new_layer = await import_shapefile_to_layer(
            db_session=session,
            zip_path=args.zip,
            layer_name=args.layer_name,
            description=args.description,
        )
        print(f"Layer imported with ID: {new_layer.id}, Name: {new_layer.name}")


if __name__ == "__main__":
    asyncio.run(main())
