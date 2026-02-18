"""
ROI Statistics Endpoints
========================
Spatial aggregation queries powered by PostGIS ST_Contains.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import get_db
from app.models.nucleus import Slide
from app.schemas.nucleus import (
    ROIStatsRequest,
    ROIStatsResponse,
    ViewportQuery,
    ViewportNucleiResponse,
)
from app.services.spatial import SpatialQueryService
from app.spatial.transform import CoordinateTransformer, ViewportBounds

router = APIRouter(prefix="/roi", tags=["ROI"])
settings = get_settings()


# ── ROI statistics ────────────────────────────────────────────────
@router.post("/stats", response_model=ROIStatsResponse)
async def roi_stats(
    req: ROIStatsRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Compute spatial statistics for a user-defined ROI.

    Uses PostGIS ST_Contains with the GIST index for O(log n)
    spatial lookups.  Returns:
        - Total nuclei count
        - Density (nuclei/mm²)
        - Neoplastic ratio Rn
        - Per-cell-type breakdown
    """
    slide = await db.get(Slide, req.slide_id)
    if not slide:
        raise HTTPException(404, "Slide not found")

    bounds = ViewportBounds(
        x_min=req.x_min,
        y_min=req.y_min,
        x_max=req.x_max,
        y_max=req.y_max,
    )

    spatial_svc = SpatialQueryService(db)
    return await spatial_svc.get_roi_stats(
        slide_id=req.slide_id,
        bounds=bounds,
        mpp=slide.mpp,
    )


# ── Viewport nuclei (spatial fetch, no inference) ─────────────────
@router.post("/nuclei", response_model=ViewportNucleiResponse)
async def viewport_nuclei(
    req: ViewportQuery,
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch pre-computed nuclei within the user's viewport.

    Unlike the inference endpoints, this does NOT run HoVerNet.
    It only queries existing nuclei from PostGIS.
    """
    slide = await db.get(Slide, req.slide_id)
    if not slide:
        raise HTTPException(404, "Slide not found")

    transformer = CoordinateTransformer(
        mpp=slide.mpp,
        level_0_width=slide.width_px,
        level_0_height=slide.height_px,
    )
    # Frontend sends coordinates already in L0 pixel space.
    # We just need to validate and clamp them to slide bounds.
    bounds = transformer.bounds_from_level0_rect(
        x=req.x,
        y=req.y,
        w=req.width,
        h=req.height,
    )

    spatial_svc = SpatialQueryService(db)
    return await spatial_svc.get_nuclei_in_viewport(
        slide_id=req.slide_id,
        bounds=bounds,
    )
