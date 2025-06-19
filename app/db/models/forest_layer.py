from datetime import datetime
from sqlalchemy import Boolean, Text, text
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from uuid import uuid4
from typing import Optional

from app.db.models.base import Base


# GOTCHA: If you add / remove columns, remember to update the queries that specify each column explicitly
class ForestLayer(Base):
    __tablename__ = "forest_layer"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # shapefile_id_col: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_ts: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("current_timestamp(0)"),
    )
    updated_ts: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("current_timestamp(0)"),
    )
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    color_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    symbol: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_properties: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
