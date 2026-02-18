"""
Streaming Bulk Insert — O(1) Memory Nuclear Data Pipeline
==========================================================
Provides a generator-based ``NucleiStreamer`` and native PostgreSQL
bulk-loading functions that bypass driver parameter limits entirely.

- **NucleiStreamer**: A zero-copy generator that transforms raw HoVerNet
    output dicts from Viewport ``InferenceResult`` into flat tuples suitable
  for bulk insertion. It never materialises the full list on the heap.

- **bulk_insert_nuclei_async**: Async wrapper that runs parameterized
  INSERT statements through ``asyncpg`` via the raw DBAPI connection,
  using numbered ``$N`` bind parameters for every value to eliminate SQL injection.

- **suppress_sql_logging**: Context manager that temporarily sets the
  ``sqlalchemy.engine`` logger to WARNING during bulk insert phases to
  keep the terminal clear.

"""

from __future__ import annotations

import logging
import uuid as _uuid
from contextlib import contextmanager
from typing import Generator, Iterator

import numpy as np
from shapely.geometry import Polygon as ShapelyPolygon

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# ═══════════════════════════════════════════════════════════════════
# Log Suppression
# ═══════════════════════════════════════════════════════════════════

@contextmanager
def suppress_sql_logging():
    """
    Temporarily raise ``sqlalchemy.engine`` log level to WARNING
    to prevent thousands of lines of  output during bulk
    inserts.  Restores the original level on exit.
    """
    sa_logger = logging.getLogger("sqlalchemy.engine")
    original_level = sa_logger.level
    sa_logger.setLevel(logging.WARNING)
    try:
        yield
    finally:
        sa_logger.setLevel(original_level)


# ═══════════════════════════════════════════════════════════════════
# NucleiStreamer — Generator Pattern
# ═══════════════════════════════════════════════════════════════════

def _contour_to_wkt(contour) -> str | None:
    """
    Convert a contour (list or ndarray of [x, y] pairs) to a WKT
    POLYGON string, returning None if invalid.
    """
    if contour is None:
        return None

    arr = np.asarray(contour, dtype=np.float64)
    if arr.ndim != 2 or len(arr) < 3:
        return None

    ring = arr.tolist()
    # Close the ring if necessary
    if ring[0] != ring[-1]:
        ring.append(ring[0])

    poly = ShapelyPolygon(ring)
    if poly.is_valid:
        return poly.wkt
    return None


class NucleiStreamer:
    """
    Zero-copy generator that yields flat tuples from raw HoVerNet
    output for Viewport inference (``InferenceResult.nuclei``).

    Each yielded tuple has the shape::

        (slide_id, analysis_box_id, centroid_x, centroid_y, contour_wkt,
         cell_type, cell_type_name, probability, area_um2, perimeter_um)
    """

    def __init__(self, slide_id: str, mpp: float | None = None, analysis_box_id: str | None = None):
        self.slide_id = str(slide_id)
        self.analysis_box_id = str(analysis_box_id) if analysis_box_id else None
        self.mpp = mpp or settings.default_mpp
        self._mpp_sq = self.mpp ** 2
        self._cell_types = settings.cell_type_map

    # ── From Viewport InferenceResult ─────────────────────────

    def from_viewport_result(
        self,
        nuclei,  # list[DetectedNucleus]
    ) -> Generator[tuple, None, None]:
        """
        Yield insert tuples from ``InferenceResult.nuclei``.
        Consumes one nucleus at a time — O(1) memory overhead.
        """
        for nuc in nuclei:
            contour_wkt = _contour_to_wkt(nuc.contour)
            yield (
                self.slide_id,
                self.analysis_box_id,
                float(nuc.centroid_x),
                float(nuc.centroid_y),
                contour_wkt,
                int(nuc.cell_type),
                str(nuc.cell_type_name),
                float(nuc.probability),
                float(nuc.area_um2) if nuc.area_um2 else None,
                float(nuc.perimeter_um) if nuc.perimeter_um else None,
            )


# ═══════════════════════════════════════════════════════════════════
# Native PostgreSQL Bulk Insert — Async (FastAPI Viewport)
# ═══════════════════════════════════════════════════════════════════

# The parameterized INSERT template.  Every value is a numbered bind
# parameter ($1 … $10).  Geometry construction uses PostGIS functions
# that receive WKT strings as bind parameters — never interpolated.
_INSERT_SQL = (
    "INSERT INTO nuclei"
    "  (slide_id, analysis_box_id, geom, contour,"
    "   cell_type, cell_type_name, probability, area_um2, perimeter_um)"
    " VALUES"
    "  ($1::uuid,"
    "   $2::uuid,"
    "   ST_GeomFromText('POINT(' || $3::double precision || ' ' || $4::double precision || ')', 0),"
    "   CASE WHEN $5::text IS NOT NULL"
    "        THEN ST_GeomFromText($5::text, 0)"
    "        ELSE NULL"
    "   END,"
    "   $6::smallint,"
    "   $7::text,"
    "   $8::double precision,"
    "   $9::double precision,"
    "   $10::double precision)"
)


async def bulk_insert_nuclei_async(
    session,  # AsyncSession
    rows_iter: Iterator[tuple],
    *,
    page_size: int = 500,
) -> int:
    """
    Async bulk insert using **fully parameterized** queries via
    ``asyncpg``'s native ``executemany``.

    Every value — including UUIDs, WKT geometry strings, cell type
    names, and numeric fields — is bound through ``$N`` parameters.
    **No string interpolation** is used anywhere in the SQL path,
    to eliminate SQL injection.

    Parameters
    ----------
    session : AsyncSession
    rows_iter : Iterator[tuple]
        Generator from ``NucleiStreamer``.
    page_size : int
        Number of rows to buffer before flushing to the database.

    Returns
    -------
    int — total rows inserted.
    """
    total = 0
    buffer: list[tuple] = []

    with suppress_sql_logging():
        for row in rows_iter:
            # Build the parameter tuple for asyncpg executemany.
            # row = (slide_id, box_id, cx, cy, contour_wkt,
            #        cell_type, cell_type_name, prob, area, perimeter)
            params = (
                _uuid.UUID(row[0]),                                 # $1  slide_id
                _uuid.UUID(row[1]) if row[1] else None,            # $2  analysis_box_id
                float(row[2]),                                      # $3  centroid_x
                float(row[3]),                                      # $4  centroid_y
                row[4],                                             # $5  contour_wkt (str | None)
                int(row[5]),                                        # $6  cell_type
                str(row[6]),                                        # $7  cell_type_name
                float(row[7]),                                      # $8  probability
                float(row[8]) if row[8] is not None else None,     # $9  area_um2
                float(row[9]) if row[9] is not None else None,     # $10 perimeter_um
            )
            buffer.append(params)

            if len(buffer) >= page_size:
                await _flush_async_buffer(session, buffer)
                total += len(buffer)
                buffer.clear()

        # Flush remaining
        if buffer:
            await _flush_async_buffer(session, buffer)
            total += len(buffer)
            buffer.clear()

    logger.info("Bulk-inserted %d nuclei (async, page_size=%d)", total, page_size)
    return total


async def _flush_async_buffer(session, buffer: list[tuple]) -> None:
    """
    Execute a parameterized INSERT for a page of rows using asyncpg's
    native ``executemany``.

    This drops down to the raw ``asyncpg.Connection`` to call
    ``executemany`` which sends all rows in a single network round-trip
    using the PostgreSQL extended query protocol with binary encoding.
    """
    # Get the raw asyncpg connection from the SQLAlchemy async session.
    sa_conn = await session.connection()
    raw_conn = await sa_conn.get_raw_connection()
    # asyncpg's actual connection object
    asyncpg_conn = raw_conn.driver_connection

    await asyncpg_conn.executemany(_INSERT_SQL, buffer)
