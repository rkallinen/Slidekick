"""
Pydantic schemas for API request/response serialization.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ═══════════════════════════════════════════════════════════════════
# Slide schemas
# ═══════════════════════════════════════════════════════════════════
class SlideOut(BaseModel):
    id: uuid.UUID
    filename: str
    mpp: float
    width_px: int
    height_px: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════
# Nucleus schemas
# ═══════════════════════════════════════════════════════════════════
class NucleusBase(BaseModel):
    """Lightweight nucleus for Canvas overlay rendering."""

    id: int
    x: float = Field(description="Centroid X in Level-0 pixel coords")
    y: float = Field(description="Centroid Y in Level-0 pixel coords")
    cell_type: int
    cell_type_name: str
    probability: float


class NucleusDetail(NucleusBase): # reserved for future use
    """Extended nucleus with morphometric data."""
    area_um2: float | None = None
    perimeter_um: float | None = None
    contour: list[list[float]] | None = Field(
        default=None,
        description="Contour vertices [[x1,y1],[x2,y2],...] in L0 px",
    )


# ═══════════════════════════════════════════════════════════════════
# Cell type stats (shared)
# ═══════════════════════════════════════════════════════════════════
class CellTypeCount(BaseModel):
    cell_type: int
    cell_type_name: str
    count: int
    fraction: float = Field(description="Fraction of total nuclei")


# ═══════════════════════════════════════════════════════════════════
# Analysis Box schemas
# ═══════════════════════════════════════════════════════════════════
class AnalysisBoxOut(BaseModel):
    """Analysis box returned to the frontend."""

    id: uuid.UUID
    slide_id: uuid.UUID
    label: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    total_nuclei: int
    area_mm2: float
    density_per_mm2: float
    neoplastic_ratio: float
    cell_type_counts: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class AnalysisBoxDetail(AnalysisBoxOut):
    """Box with full cell type breakdown (computed from cell_type_counts)."""
    cell_type_breakdown: list[CellTypeCount] = Field(default_factory=list)
    shannon_h: float = 0.0
    inflammatory_index: float | None = 0.0
    # Ratios that may be undefined when the denominator is zero use Optional[float].
    immune_tumour_ratio: float | None = None
    ne_epithelial_ratio: float | None = None
    viability: float | None = 0.0


class AnalysisBoxListResponse(BaseModel):
    """All analysis boxes for a slide."""

    slide_id: uuid.UUID
    boxes: list[AnalysisBoxOut]


# ═══════════════════════════════════════════════════════════════════
# Viewport query
# ═══════════════════════════════════════════════════════════════════
class ViewportQuery(BaseModel):
    """
    Defines the user's current viewport in either Level-0 pixel
    coordinates or viewport-level coordinates with a zoom level.
    """

    slide_id: uuid.UUID
    x: float = Field(description="Top-left X of viewport (px)")
    y: float = Field(description="Top-left Y of viewport (px)")
    width: float = Field(description="Viewport width (px)")
    height: float = Field(description="Viewport height (px)")
    level: int = Field(
        default=0,
        description="WSI zoom level (0 = highest resolution)",
    )

    @field_validator("level")
    @classmethod
    def level_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Zoom level must be >= 0")
        return v


class ViewportNucleiResponse(BaseModel):
    """Response for viewport nucleus queries."""

    slide_id: uuid.UUID
    bounds_l0: dict = Field(
        description="Level-0 bounding box {x_min, y_min, x_max, y_max}"
    )
    nuclei: list[NucleusBase]


# ═══════════════════════════════════════════════════════════════════
# Inference request / task status
# ═══════════════════════════════════════════════════════════════════
class InferenceViewportRequest(BaseModel):
    """Request real-time HoVerNet inference on the current viewport."""

    slide_id: uuid.UUID
    x: float
    y: float
    width: float
    height: float
    level: int = 0


# ═══════════════════════════════════════════════════════════════════
# ROI statistics (legacy — kept for backward compat)
# ═══════════════════════════════════════════════════════════════════
class ROIStatsRequest(BaseModel):
    """Request spatial statistics for a rectangular ROI."""

    slide_id: uuid.UUID
    x_min: float
    y_min: float
    x_max: float
    y_max: float


class ROIStatsResponse(BaseModel):
    """Full spatial statistics for a user-defined ROI."""

    slide_id: uuid.UUID
    total_nuclei: int
    area_mm2: float
    density_per_mm2: float = Field(description="nuclei / mm²")
    neoplastic_ratio: float = Field(
        description="Rn = N_neoplastic / N_total"
    )
    cell_type_breakdown: list[CellTypeCount]
    mpp: float
    bounds_l0: dict


# ═══════════════════════════════════════════════════════════════════
# Scale bar (for VirtualMicrometer)
# ═══════════════════════════════════════════════════════════════════
class ScaleBarResponse(BaseModel):
    target_um: float
    pixels_at_level: float
    level: int
    mpp: float
