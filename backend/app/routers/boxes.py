"""
Analysis Box Endpoints
======================
CRUD operations for analysis boxes (viewport analysis regions).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.nucleus import AnalysisBox, Nucleus, Slide
from app.schemas.nucleus import (
    AnalysisBoxDetail,
    AnalysisBoxListResponse,
    AnalysisBoxOut,
    CellTypeCount,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/boxes", tags=["Analysis Boxes"])


# ── List all boxes for a slide ────────────────────────────────────
@router.get("/{slide_id}", response_model=AnalysisBoxListResponse)
async def list_boxes(
    slide_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return all analysis boxes for a slide, ordered by creation time."""
    slide = await db.get(Slide, slide_id)
    if not slide:
        raise HTTPException(404, "Slide not found")

    stmt = (
        select(AnalysisBox)
        .where(AnalysisBox.slide_id == slide_id)
        .order_by(AnalysisBox.created_at.desc())
    )
    result = await db.execute(stmt)
    boxes = result.scalars().all()

    return AnalysisBoxListResponse(
        slide_id=slide_id,
        boxes=[AnalysisBoxOut.model_validate(b) for b in boxes],
    )


# ── Get single box with detailed breakdown ───────────────────────
@router.get("/detail/{box_id}", response_model=AnalysisBoxDetail)
async def get_box_detail(
    box_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return a single analysis box with full cell type breakdown."""
    box = await db.get(AnalysisBox, box_id)
    if not box:
        raise HTTPException(404, "Analysis box not found")

    # Build breakdown from the stored cell_type_counts JSON
    breakdown = []
    total = box.total_nuclei or 0
    for ct_str, info in box.cell_type_counts.items():
        count = info["count"] if isinstance(info, dict) else info
        name = info.get("name", f"Type {ct_str}") if isinstance(info, dict) else f"Type {ct_str}"
        fraction = count / total if total > 0 else 0.0
        breakdown.append(
            CellTypeCount(
                cell_type=int(ct_str),
                cell_type_name=name,
                count=count,
                fraction=fraction,
            )
        )
    breakdown.sort(key=lambda x: x.cell_type)

    # ROI statistics 
    def count_of(type_id: int) -> int:
        for ct in breakdown:
            if ct.cell_type == type_id:
                return ct.count
        return 0

    background = count_of(0)
    neoplastic = count_of(1)
    inflammatory = count_of(2)
    connective = count_of(3)
    dead = count_of(4)
    epithelial = count_of(5)

    non_background = total - background
    inflammatory_index = (inflammatory / non_background) if non_background > 0 else 0.0
    # Avoid returning JSON-unserializable infinite floats. If the denominator
    # is zero and the numerator is > 0 we return None (meaning "undefined").
    def safe_ratio(num: int, denom: int) -> float | None:
        if denom > 0:
            return num / denom
        return None if num > 0 else 0.0

    ne_epithelial_ratio = safe_ratio(neoplastic, epithelial)
    immune_tumour_ratio = safe_ratio(inflammatory, neoplastic)
    viability = ((total - dead) / total) if total > 0 else 0.0

    # Shannon diversity (natural log)
    shannon_h = 0.0
    if total > 0:
        import math

        for ct in breakdown:
            if ct.count > 0:
                p = ct.count / total
                shannon_h -= p * math.log(p)

    return AnalysisBoxDetail(
        **AnalysisBoxOut.model_validate(box).model_dump(),
        cell_type_breakdown=breakdown,
        shannon_h=shannon_h,
        inflammatory_index=inflammatory_index,
        immune_tumour_ratio=immune_tumour_ratio,
        ne_epithelial_ratio=ne_epithelial_ratio,
        viability=viability,
    )


# ── Delete a box (and all its nuclei via CASCADE) ─────────────────
@router.delete("/{box_id}", status_code=204)
async def delete_box(
    box_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete an analysis box and all its nuclei."""
    box = await db.get(AnalysisBox, box_id)
    if not box:
        raise HTTPException(404, "Analysis box not found")

    await db.delete(box)
    await db.commit()
    logger.info("Deleted analysis box %s (cascade-deleted nuclei)", box_id)
