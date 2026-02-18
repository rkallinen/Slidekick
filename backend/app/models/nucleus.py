"""
SQLAlchemy ORM models for Slides, AnalysisBoxes, and Nuclei.

All spatial columns use GeoAlchemy2 with SRID 0 (Cartesian pixel space).

Schema:
    Slide  1──*  AnalysisBox  1──*  Nucleus

Each viewport analysis creates an AnalysisBox that contains all
detected nuclei.  Boxes can be selected, inspected, and deleted
from the viewer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base


# ── Slides ────────────────────────────────────────────────────────
class Slide(Base):
    __tablename__ = "slides"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    filepath: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    mpp: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)
    width_px: Mapped[int] = mapped_column(Integer, nullable=False)
    height_px: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    analysis_boxes: Mapped[list["AnalysisBox"]] = relationship(
        back_populates="slide", cascade="all, delete-orphan"
    )


# ── Analysis Boxes ────────────────────────────────────────────────
class AnalysisBox(Base):
    """
    A rectangular viewport analysis region.  Created each time the
    user runs 'Analyze Viewport'.  Contains all detected nuclei
    and pre-computed summary statistics.
    """
    __tablename__ = "analysis_boxes"
    __table_args__ = (
        Index("idx_abox_geom_gist", "geom", postgresql_using="gist"),
        Index("idx_abox_slide_id", "slide_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slide_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("slides.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(Text, nullable=False, default="Viewport Analysis")

    # Bounding rectangle in L0 pixel coords
    x_min: Mapped[float] = mapped_column(Float, nullable=False)
    y_min: Mapped[float] = mapped_column(Float, nullable=False)
    x_max: Mapped[float] = mapped_column(Float, nullable=False)
    y_max: Mapped[float] = mapped_column(Float, nullable=False)

    # PostGIS envelope for spatial queries
    geom = mapped_column(
        Geometry(geometry_type="POLYGON", srid=0), nullable=False
    )

    # Pre-computed summary (denormalised for fast reads)
    total_nuclei: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    area_mm2: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    density_per_mm2: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    neoplastic_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cell_type_counts: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    slide: Mapped["Slide"] = relationship(back_populates="analysis_boxes")
    nuclei: Mapped[list["Nucleus"]] = relationship(
        back_populates="analysis_box", cascade="all, delete-orphan"
    )


# ── Nuclei (spatial) ─────────────────────────────────────────────
class Nucleus(Base):
    __tablename__ = "nuclei"
    __table_args__ = (
        Index("idx_nuclei_geom_gist", "geom", postgresql_using="gist"),
        Index("idx_nuclei_contour_gist", "contour", postgresql_using="gist"),
        Index("idx_nuclei_slide_id", "slide_id"),
        Index("idx_nuclei_box_id", "analysis_box_id"),
        Index("idx_nuclei_cell_type", "slide_id", "cell_type"),
        CheckConstraint(
            "probability >= 0.0 AND probability <= 1.0",
            name="ck_nuclei_probability_range",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    slide_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("slides.id", ondelete="CASCADE"), nullable=False
    )
    analysis_box_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_boxes.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Centroid — POINT in L0 pixel coords (SRID 0)
    geom = mapped_column(
        Geometry(geometry_type="POINT", srid=0), nullable=False
    )
    # Full contour — POLYGON in L0 pixel coords
    contour = mapped_column(
        Geometry(geometry_type="POLYGON", srid=0), nullable=True
    )
    cell_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    cell_type_name: Mapped[str] = mapped_column(Text, nullable=False, default="Background")
    probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    area_um2: Mapped[float | None] = mapped_column(Float, nullable=True)
    perimeter_um: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    slide: Mapped["Slide"] = relationship()
    analysis_box: Mapped["AnalysisBox"] = relationship(back_populates="nuclei")
