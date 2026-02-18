"""
Spatial Query Service
=====================
PostGIS-backed spatial queries for nuclear data.

All queries leverage the GIST index on `nuclei.geom` for O(log n)
R-tree lookups via ST_Contains / ST_Intersects.
"""

from __future__ import annotations

import logging
import uuid

from geoalchemy2.functions import (
    ST_Contains,
    ST_MakeEnvelope,
    ST_X,
    ST_Y,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.nucleus import Nucleus
from app.schemas.nucleus import (
    CellTypeCount,
    NucleusBase,
    ROIStatsResponse,
    ViewportNucleiResponse,
)
from app.spatial.transform import ViewportBounds

logger = logging.getLogger(__name__)
settings = get_settings()


class SpatialQueryService:
    """
    Executes spatial queries against the PostGIS nuclei table.
    All methods are async and use the injected AsyncSession.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Viewport nuclei query ─────────────────────────────────

    async def get_nuclei_in_viewport(
        self,
        slide_id: uuid.UUID,
        bounds: ViewportBounds,
        max_results: int = 50_000,
    ) -> ViewportNucleiResponse:
        """
        Fetch all nuclei whose centroids fall within the viewport bounds.

        Uses PostGIS ST_MakeEnvelope + ST_Contains for an indexed spatial
        lookup against the GIST index.

        Parameters
        ----------
        slide_id : UUID
        bounds : ViewportBounds
            Level-0 pixel-coordinate rectangle.
        max_results : int
            Safety cap to prevent memory exhaustion.

        Returns
        -------
        ViewportNucleiResponse
        """
        envelope = ST_MakeEnvelope(
            bounds.x_min, bounds.y_min,
            bounds.x_max, bounds.y_max,
            0,  # SRID 0 = Cartesian
        )

        stmt = (
            select(
                Nucleus.id,
                ST_X(Nucleus.geom).label("x"),
                ST_Y(Nucleus.geom).label("y"),
                Nucleus.cell_type,
                Nucleus.cell_type_name,
                Nucleus.probability,
            )
            .where(
                Nucleus.slide_id == slide_id,
                ST_Contains(envelope, Nucleus.geom),
            )
            .limit(max_results)
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        nuclei = [
            NucleusBase(
                id=row.id,
                x=row.x,
                y=row.y,
                cell_type=row.cell_type,
                cell_type_name=row.cell_type_name,
                probability=row.probability,
            )
            for row in rows
        ]

        return ViewportNucleiResponse(
            slide_id=slide_id,
            bounds_l0={
                "x_min": bounds.x_min,
                "y_min": bounds.y_min,
                "x_max": bounds.x_max,
                "y_max": bounds.y_max,
            },
            nuclei=nuclei,
        )

    # ── ROI statistics ────────────────────────────────────────

    async def get_roi_stats(
        self,
        slide_id: uuid.UUID,
        bounds: ViewportBounds,
        mpp: float,
    ) -> ROIStatsResponse:
        """
        Compute spatial aggregation statistics for a rectangular ROI.

        Uses a single PostGIS query with conditional aggregation to
        compute per-cell-type counts, total count, and derives:
            - density (nuclei/mm²)
            - neoplastic ratio Rn = N_neoplastic / N_total

        Parameters
        ----------
        slide_id : UUID
        bounds : ViewportBounds
            ROI in Level-0 pixel coordinates.
        mpp : float
            Microns-Per-Pixel for this slide.
        """
        envelope = ST_MakeEnvelope(
            bounds.x_min, bounds.y_min,
            bounds.x_max, bounds.y_max,
            0,
        )

        # ── Aggregate query: count per cell_type ──────────────
        stmt = (
            select(
                Nucleus.cell_type,
                Nucleus.cell_type_name,
                func.count().label("cnt"),
            )
            .where(
                Nucleus.slide_id == slide_id,
                ST_Contains(envelope, Nucleus.geom),
            )
            .group_by(Nucleus.cell_type, Nucleus.cell_type_name)
            .order_by(Nucleus.cell_type)
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        total = sum(r.cnt for r in rows)
        area_mm2 = bounds.area_mm2(mpp)

        # Per-type breakdown
        breakdown = [
            CellTypeCount(
                cell_type=r.cell_type,
                cell_type_name=r.cell_type_name,
                count=r.cnt,
                fraction=r.cnt / total if total > 0 else 0.0,
            )
            for r in rows
        ]

        # Neoplastic ratio: Rn = N_neoplastic / N_total
        n_neoplastic = sum(r.cnt for r in rows if r.cell_type == 1)
        rn = n_neoplastic / total if total > 0 else 0.0

        # Density: ρ = N / A_mm²
        density = total / area_mm2 if area_mm2 > 0 else 0.0

        return ROIStatsResponse(
            slide_id=slide_id,
            total_nuclei=total,
            area_mm2=area_mm2,
            density_per_mm2=density,
            neoplastic_ratio=rn,
            cell_type_breakdown=breakdown,
            mpp=mpp,
            bounds_l0={
                "x_min": bounds.x_min,
                "y_min": bounds.y_min,
                "x_max": bounds.x_max,
                "y_max": bounds.y_max,
            },
        )
