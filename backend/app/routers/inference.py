"""
Inference Endpoints
====================
Real-time viewport inference with streaming results.

Each viewport inference creates an AnalysisBox that contains all
detected nuclei.  The box is returned to the frontend so it can
be rendered, selected, and deleted.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings
from app.models.database import get_db
from app.models.nucleus import AnalysisBox, Slide
from app.schemas.nucleus import (
    AnalysisBoxOut,
    InferenceViewportRequest,
    NucleusBase,
)
from app.services.bulk_insert import (
    NucleiStreamer,
    bulk_insert_nuclei_async,
)
from app.services.inference import get_inference_engine, ProgressTracker
from app.services.slide import get_slide_service
from app.spatial.transform import CoordinateTransformer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/inference", tags=["Inference"])
settings = get_settings()

def _compute_box_stats(nuclei_list, bounds, mpp):
    """Compute summary statistics for an analysis box from raw nuclei."""
    total = len(nuclei_list)
    width_um = (bounds.x_max - bounds.x_min) * mpp
    height_um = (bounds.y_max - bounds.y_min) * mpp
    area_mm2 = (width_um * height_um) * 1e-6

    # Count per cell type
    counts = {}
    for nuc in nuclei_list:
        ct = nuc.cell_type
        if ct not in counts:
            counts[ct] = {"count": 0, "name": nuc.cell_type_name}
        counts[ct]["count"] += 1

    n_neoplastic = counts.get(1, {}).get("count", 0)
    rn = n_neoplastic / total if total > 0 else 0.0
    density = total / area_mm2 if area_mm2 > 0 else 0.0

    # JSON-serialisable dict keyed by cell_type int → {"count", "name"}
    cell_type_counts = {str(k): v for k, v in counts.items()}

    return {
        "total_nuclei": total,
        "area_mm2": area_mm2,
        "density_per_mm2": density,
        "neoplastic_ratio": rn,
        "cell_type_counts": cell_type_counts,
    }


async def _assign_analysis_label(db: AsyncSession, slide_id: uuid.UUID) -> str:
    """Return the next available label 'Analysis N' for the given slide.

    This finds existing labels matching the pattern 'Analysis {n}' and
    returns the smallest positive integer n that is not currently used.
    """
    stmt = select(AnalysisBox.label).where(AnalysisBox.slide_id == slide_id)
    result = await db.execute(stmt)
    labels = result.scalars().all()

    used = set()
    pattern = re.compile(r"^Analysis\s+(\d+)$")
    for lbl in labels:
        if not isinstance(lbl, str):
            continue
        m = pattern.match(lbl.strip())
        if m:
            try:
                used.add(int(m.group(1)))
            except ValueError:  # pragma: no cover – regex \d+ guarantees valid int
                continue

    n = 1
    while n in used:
        n += 1
    return f"Analysis {n}"


# ── Viewport inference with SSE progress streaming ────────────────
@router.post("/viewport-stream")
async def infer_viewport_stream(
    req: InferenceViewportRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Run HoVerNet inference with real-time progress streaming via SSE.
    
    This endpoint streams progress events as JSON objects:
    - {"type": "progress", "current": N, "total": M, "percentage": X, "message": "..."}
    - {"type": "complete", "nuclei": [...], "count": N}
    - {"type": "error", "message": "..."}
    """
    
    async def event_generator():
        try:
            # Fetch slide metadata
            slide = await db.get(Slide, req.slide_id)
            if not slide:
                yield {
                    "event": "error",
                    "data": json.dumps({"type": "error", "message": "Slide not found"}),
                }
                return

            # Build coordinate transformer
            transformer = CoordinateTransformer(
                mpp=slide.mpp,
                level_0_width=slide.width_px,
                level_0_height=slide.height_px,
            )

            # Validate and transform bounds
            bounds = transformer.bounds_from_level0_rect(
                x=req.x,
                y=req.y,
                w=req.width,
                h=req.height,
            )

            if bounds.width_px <= 0 or bounds.height_px <= 0:
                yield {
                    "event": "error",
                    "data": json.dumps({
                        "type": "error",
                        "message": f"Invalid viewport bounds: width={int(bounds.width_px)}, height={int(bounds.height_px)}",
                    }),
                }
                return

            # Read the WSI region
            slide_svc = get_slide_service(slide.filepath)
            tile_rgb = slide_svc.read_region_l0(
                x=int(bounds.x_min),
                y=int(bounds.y_min),
                width=int(bounds.width_px),
                height=int(bounds.height_px),
            )

            # Create progress tracker
            progress_tracker = ProgressTracker()
            
            def progress_callback(current: int, total: int, message: str):
                progress_tracker.update(current, total, message)

            # Run inference in a thread pool to avoid blocking
            engine = get_inference_engine()
            loop = asyncio.get_event_loop()
            
            # Start inference in background
            inference_task = loop.run_in_executor(
                None,
                lambda: engine.infer_tile(
                    tile_rgb=tile_rgb,
                    offset_x=int(bounds.x_min),
                    offset_y=int(bounds.y_min),
                    mpp=slide.mpp,
                    progress_callback=progress_callback,
                ),
            )

            # Stream progress updates
            last_progress = -1
            while not inference_task.done():
                await asyncio.sleep(0.3)  # Update every 300ms
                progress = progress_tracker.get_progress()
                if progress["current"] != last_progress:
                    yield {
                        "event": "progress",
                        "data": json.dumps({
                            "type": "progress",
                            **progress,
                        }),
                    }
                    last_progress = progress["current"]

            # Get result
            result = await inference_task

            # ── Create AnalysisBox and insert nuclei ──────────
            stats = _compute_box_stats(result.nuclei, bounds, slide.mpp)
            box_geom_wkt = (
                f"POLYGON(({bounds.x_min} {bounds.y_min}, "
                f"{bounds.x_max} {bounds.y_min}, "
                f"{bounds.x_max} {bounds.y_max}, "
                f"{bounds.x_min} {bounds.y_max}, "
                f"{bounds.x_min} {bounds.y_min}))"
            )

            label = await _assign_analysis_label(db, req.slide_id)
            analysis_box = AnalysisBox(
                slide_id=req.slide_id,
                label=label,
                x_min=bounds.x_min,
                y_min=bounds.y_min,
                x_max=bounds.x_max,
                y_max=bounds.y_max,
                geom=box_geom_wkt,
                **stats,
            )
            db.add(analysis_box)
            await db.flush()
            box_id = analysis_box.id

            streamer = NucleiStreamer(
                slide_id=str(req.slide_id),
                mpp=slide.mpp,
                analysis_box_id=str(box_id),
            )
            rows_gen = streamer.from_viewport_result(result.nuclei)
            inserted = await bulk_insert_nuclei_async(db, rows_gen, page_size=500)

            # Explicit commit — session no longer auto-commits.
            await db.commit()

            logger.info(
                "Viewport inference (SSE): slide=%s, box=%s, detected=%d, inserted=%d",
                req.slide_id, box_id, len(result.nuclei), inserted,
            )

            # Build nuclei response
            nuclei_out = [
                {
                    "id": 0,
                    "x": nuc.centroid_x,
                    "y": nuc.centroid_y,
                    "cell_type": nuc.cell_type,
                    "cell_type_name": nuc.cell_type_name,
                    "probability": nuc.probability,
                }
                for nuc in result.nuclei
            ]

            # Build box response
            box_out = AnalysisBoxOut.model_validate(analysis_box).model_dump(mode="json")

            # Send completion event
            yield {
                "event": "complete",
                "data": json.dumps({
                    "type": "complete",
                    "box": box_out,
                    "nuclei": nuclei_out,
                    "count": len(nuclei_out),
                }),
            }

        except Exception as e:
            logger.exception("Viewport inference (SSE) failed")
            yield {
                "event": "error",
                "data": json.dumps({
                    "type": "error",
                    "message": "Inference failed — see server logs for details",
                }),
            }

    return EventSourceResponse(event_generator())
