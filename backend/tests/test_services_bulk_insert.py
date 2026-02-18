"""
Tests for app.services.bulk_insert — WKT conversion, NucleiStreamer,
log suppression, and bulk insert.
"""
from __future__ import annotations

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.services.bulk_insert import (
    NucleiStreamer,
    _contour_to_wkt,
    _flush_async_buffer,
    _INSERT_SQL,
    bulk_insert_nuclei_async,
    suppress_sql_logging,
)


# ═══════════════════════════════════════════════════════════════════
# _contour_to_wkt
# ═══════════════════════════════════════════════════════════════════
class TestContourToWkt:
    def test_none_contour(self):
        assert _contour_to_wkt(None) is None

    def test_too_few_points(self):
        assert _contour_to_wkt([[0, 0], [1, 1]]) is None

    def test_1d_array(self):
        """1-D array should fail (ndim != 2)."""
        assert _contour_to_wkt([1, 2, 3]) is None

    def test_valid_triangle(self):
        contour = [[0, 0], [10, 0], [10, 10]]
        wkt = _contour_to_wkt(contour)
        assert wkt is not None
        assert "POLYGON" in wkt

    def test_valid_square(self):
        contour = [[0, 0], [10, 0], [10, 10], [0, 10]]
        wkt = _contour_to_wkt(contour)
        assert "POLYGON" in wkt

    def test_already_closed_ring(self):
        contour = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
        wkt = _contour_to_wkt(contour)
        assert "POLYGON" in wkt

    def test_ndarray_input(self):
        arr = np.array([[0, 0], [5, 0], [5, 5], [0, 5]], dtype=np.float64)
        wkt = _contour_to_wkt(arr)
        assert "POLYGON" in wkt

    def test_invalid_polygon_collinear(self):
        """Three collinear points form a degenerate polygon.
        Shapely may still consider it valid (as a zero-area polygon),
        so just verify we get a non-None result (it's still a valid WKT)
        or None depending on Shapely version."""
        contour = [[0, 0], [5, 0], [10, 0]]
        result = _contour_to_wkt(contour)
        # Shapely 2.x may return None for degenerate polygons
        # or may return a valid WKT — both are acceptable.
        assert result is None or "POLYGON" in result


# ═══════════════════════════════════════════════════════════════════
# suppress_sql_logging
# ═══════════════════════════════════════════════════════════════════
class TestSuppressSqlLogging:
    def test_suppresses_and_restores(self):
        sa_logger = logging.getLogger("sqlalchemy.engine")
        original = sa_logger.level

        with suppress_sql_logging():
            assert sa_logger.level == logging.WARNING

        assert sa_logger.level == original

    def test_restores_on_exception(self):
        sa_logger = logging.getLogger("sqlalchemy.engine")
        original = sa_logger.level

        with pytest.raises(RuntimeError):
            with suppress_sql_logging():
                raise RuntimeError("boom")

        assert sa_logger.level == original


# ═══════════════════════════════════════════════════════════════════
# NucleiStreamer
# ═══════════════════════════════════════════════════════════════════
class TestNucleiStreamer:
    def _make_nucleus(self, **overrides):
        defaults = dict(
            centroid_x=100.0,
            centroid_y=200.0,
            contour=np.array([[90, 190], [110, 190], [110, 210], [90, 210]]),
            cell_type=1,
            cell_type_name="Neoplastic",
            probability=0.95,
            area_um2=25.0,
            perimeter_um=20.0,
        )
        defaults.update(overrides)
        return MagicMock(**defaults)

    def test_basic_streaming(self):
        slide_id = str(uuid.uuid4())
        box_id = str(uuid.uuid4())
        streamer = NucleiStreamer(slide_id=slide_id, mpp=0.25, analysis_box_id=box_id)

        nuclei = [self._make_nucleus(), self._make_nucleus(cell_type=2, cell_type_name="Inflammatory")]
        rows = list(streamer.from_viewport_result(nuclei))

        assert len(rows) == 2
        # Check first row structure
        row = rows[0]
        assert row[0] == slide_id
        assert row[1] == box_id
        assert row[2] == 100.0  # centroid_x
        assert row[3] == 200.0  # centroid_y
        assert row[4] is not None  # contour_wkt
        assert row[5] == 1  # cell_type
        assert row[6] == "Neoplastic"
        assert row[7] == 0.95
        assert row[8] == 25.0
        assert row[9] == 20.0

    def test_none_box_id(self):
        streamer = NucleiStreamer(slide_id=str(uuid.uuid4()), mpp=0.25, analysis_box_id=None)
        assert streamer.analysis_box_id is None

    def test_empty_nuclei(self):
        streamer = NucleiStreamer(slide_id=str(uuid.uuid4()), mpp=0.25)
        rows = list(streamer.from_viewport_result([]))
        assert rows == []

    def test_zero_area_nucleus(self):
        """Nucleus with area_um2=0 should still yield a row."""
        nuc = self._make_nucleus(area_um2=0, perimeter_um=0)
        streamer = NucleiStreamer(slide_id=str(uuid.uuid4()), mpp=0.25)
        rows = list(streamer.from_viewport_result([nuc]))
        assert len(rows) == 1
        # area_um2=0 is falsy, so it becomes None
        assert rows[0][8] is None

    def test_none_contour(self):
        """Nucleus with invalid contour should yield None wkt."""
        nuc = self._make_nucleus(contour=None)
        streamer = NucleiStreamer(slide_id=str(uuid.uuid4()), mpp=0.25)
        rows = list(streamer.from_viewport_result([nuc]))
        assert rows[0][4] is None

    def test_default_mpp_used(self):
        """When mpp is None, falls back to settings.default_mpp."""
        streamer = NucleiStreamer(slide_id=str(uuid.uuid4()), mpp=None)
        # Should use the default (0.25 from settings)
        assert streamer.mpp > 0


# ═══════════════════════════════════════════════════════════════════
# bulk_insert_nuclei_async
# ═══════════════════════════════════════════════════════════════════
class TestBulkInsertNucleiAsync:
    @pytest.mark.asyncio
    async def test_empty_iterator(self):
        session = AsyncMock()
        total = await bulk_insert_nuclei_async(session, iter([]), page_size=10)
        assert total == 0

    @pytest.mark.asyncio
    async def test_inserts_rows(self):
        """Verify rows flow through to asyncpg executemany."""
        # Set up mock chain: session → connection → raw_connection → driver_connection
        mock_driver = AsyncMock()
        mock_raw_conn = MagicMock()
        mock_raw_conn.driver_connection = mock_driver
        mock_sa_conn = AsyncMock()
        mock_sa_conn.get_raw_connection.return_value = mock_raw_conn

        mock_session = AsyncMock()
        mock_session.connection.return_value = mock_sa_conn

        slide_id = str(uuid.uuid4())
        box_id = str(uuid.uuid4())

        rows = [
            (slide_id, box_id, 10.0, 20.0, "POLYGON((0 0, 1 0, 1 1, 0 0))", 1, "Neoplastic", 0.9, 5.0, 3.0),
            (slide_id, box_id, 30.0, 40.0, None, 2, "Inflammatory", 0.8, None, None),
        ]

        total = await bulk_insert_nuclei_async(mock_session, iter(rows), page_size=10)
        assert total == 2
        assert mock_driver.executemany.called

    @pytest.mark.asyncio
    async def test_page_size_flushing(self):
        """Verify buffer flushes at page_size boundary."""
        mock_driver = AsyncMock()
        mock_raw_conn = MagicMock()
        mock_raw_conn.driver_connection = mock_driver
        mock_sa_conn = AsyncMock()
        mock_sa_conn.get_raw_connection.return_value = mock_raw_conn

        mock_session = AsyncMock()
        mock_session.connection.return_value = mock_sa_conn

        slide_id = str(uuid.uuid4())
        box_id = str(uuid.uuid4())

        # 5 rows with page_size=2 → 3 flushes (2 + 2 + 1)
        rows = [
            (slide_id, box_id, float(i), float(i), None, 0, "Background", 0.1, None, None)
            for i in range(5)
        ]

        total = await bulk_insert_nuclei_async(mock_session, iter(rows), page_size=2)
        assert total == 5
        assert mock_driver.executemany.call_count == 3


# ═══════════════════════════════════════════════════════════════════
# _INSERT_SQL sanity
# ═══════════════════════════════════════════════════════════════════
class TestInsertSQL:
    def test_sql_has_all_parameters(self):
        """Verify all 10 $N bind params are present."""
        for i in range(1, 11):
            assert f"${i}" in _INSERT_SQL

    def test_no_string_interpolation(self):
        """No Python format strings or f-string markers."""
        assert "%" not in _INSERT_SQL.replace("%%", "")
        assert "{" not in _INSERT_SQL
