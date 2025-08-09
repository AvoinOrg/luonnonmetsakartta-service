from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Boolean, Text, text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base

if TYPE_CHECKING:
    from app.db.models.forest_area import ForestArea


class Picture(Base):
    __tablename__ = "picture"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    forest_area_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forest_area.id", ondelete="CASCADE"), nullable=False
    )
    bucket_url: Mapped[str] = mapped_column(Text, nullable=False)
    is_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("TRUE")
    )
    date_added: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("current_timestamp(0)"),
    )
    name: Mapped[str | None] = mapped_column(Text, nullable=True)

    forest_area: Mapped["ForestArea"] = relationship(back_populates="pictures")
