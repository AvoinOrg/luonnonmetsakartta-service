from contextlib import asynccontextmanager
import shutil
import tempfile
from pathlib import Path
from fastapi import UploadFile, File, Form, HTTPException
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.utils.logger import get_logger
from app.db import connection
from app.utils.geometry import import_shapefile_to_layer

logger = get_logger(__name__)
global_settings = config.get_settings()

app = FastAPI()

origins = [
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("starting up")
    yield
    print("shutting down")


app = FastAPI(lifespan=lifespan)


@app.get(path="/hello")
async def calculate():
    return {"hi": "there"}


@app.post(path="/import-shapefile")
async def import_shapefile(
    name: str = Form(...),
    description: str = Form(None),
    zip_file: UploadFile = File(...),
):
    # Create temporary directory

    if not zip_file.filename:
        raise HTTPException(
            status_code=400, detail=f"Missing filename in main .shp file"
        )

    try:
        with tempfile.NamedTemporaryFile(suffix=".zip") as temp_file:
            shutil.copyfileobj(zip_file.file, temp_file)
            temp_file.flush()

            async with connection.get_async_context_db() as session:
                layer = await import_shapefile_to_layer(
                    session, temp_file.name, name, description
                )

                return {
                    "id": str(layer.id),
                    "name": layer.name,
                    "description": layer.description,
                }

    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to import shapefile: {str(e)}"
        )
