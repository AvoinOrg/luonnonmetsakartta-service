from datetime import datetime
from uuid import uuid4

from sqlalchemy import Text, text
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from geoalchemy2 import Geometry
from typing import Optional

from app.db.models.base import Base


# GOTCHA: If you add / remove columns, remember to update the queries that specify each column explicitly
class Area(Base):
    __tablename__ = "area"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    layer_id: Mapped[str] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_ts: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        server_default=text("current_timestamp(0)"),
    )
    updated_ts: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        server_default=text("current_timestamp(0)"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(JSONB, nullable=True)
    pictures: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    original_properties: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    geometry: Mapped[Geometry] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326), nullable=True
    ) # do multipolygons work?
