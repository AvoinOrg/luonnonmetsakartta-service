from datetime import datetime
from uuid import uuid4

from sqlalchemy import Computed, Numeric, Text, text
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from geoalchemy2 import Geometry
from typing import Optional

from app.db.models.base import Base


# GOTCHA: If you add / remove columns, remember to update the queries that specify each column explicitly
class ForestArea(Base):
    __tablename__ = "forest_area"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    layer_id: Mapped[str] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_ts: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),  # Use TIMESTAMP WITH TIME ZONE
        server_default=text("current_timestamp(0)"),
    )
    updated_ts: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),  # Use TIMESTAMP WITH TIME ZONE
        server_default=text("current_timestamp(0)"),
        onupdate=text("current_timestamp(0)"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(JSONB, nullable=True)
    pictures: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    municipality: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    region: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    area_ha: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    date: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    person_responsible: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    geometry: Mapped[Geometry] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=3067), nullable=True
    )  # do multipolygons work?
    centroid: Mapped[Geometry] = mapped_column(
        Geometry(geometry_type="POINT", srid=3067),
        Computed("ST_Centroid(geometry) STORED", persisted=True),
        nullable=True,
    )
    original_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_properties: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
