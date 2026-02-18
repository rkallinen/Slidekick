"""
Tests for app.spatial.transform — ViewportBounds and CoordinateTransformer.
"""
from __future__ import annotations

import math

import pytest
from shapely.geometry import Polygon

from app.spatial.transform import CoordinateTransformer, ViewportBounds


# ═══════════════════════════════════════════════════════════════════
# ViewportBounds
# ═══════════════════════════════════════════════════════════════════
class TestViewportBounds:
    """Tests for the ViewportBounds frozen dataclass."""

    def test_basic_properties(self):
        b = ViewportBounds(x_min=100, y_min=200, x_max=500, y_max=600)
        assert b.width_px == 400
        assert b.height_px == 400
        assert b.area_px == 160000

    def test_zero_area(self):
        b = ViewportBounds(x_min=0, y_min=0, x_max=0, y_max=0)
        assert b.width_px == 0
        assert b.height_px == 0
        assert b.area_px == 0

    @pytest.mark.parametrize("mpp,expected", [
        (0.25, 160000 * (0.25 ** 2) * 1e-6),
        (0.5, 160000 * (0.5 ** 2) * 1e-6),
        (1.0, 160000 * 1.0 * 1e-6),
    ])
    def test_area_mm2(self, mpp, expected):
        b = ViewportBounds(x_min=100, y_min=200, x_max=500, y_max=600)
        assert math.isclose(b.area_mm2(mpp), expected, rel_tol=1e-9)

    def test_area_mm2_zero_area(self):
        b = ViewportBounds(x_min=0, y_min=0, x_max=0, y_max=0)
        assert b.area_mm2(0.25) == 0.0

    def test_to_shapely(self):
        b = ViewportBounds(x_min=0, y_min=0, x_max=100, y_max=200)
        poly = b.to_shapely()
        assert isinstance(poly, Polygon)
        assert poly.bounds == (0.0, 0.0, 100.0, 200.0)

    def test_to_wkt(self):
        b = ViewportBounds(x_min=0, y_min=0, x_max=10, y_max=20)
        wkt = b.to_wkt()
        assert "POLYGON" in wkt

    @pytest.mark.parametrize("x,y,inside", [
        (50, 50, True),       # Interior
        (0, 0, True),         # Corner
        (100, 200, True),     # Opposite corner
        (-1, 50, False),      # Outside left
        (101, 50, False),     # Outside right
        (50, -1, False),      # Outside top
        (50, 201, False),     # Outside bottom
    ])
    def test_contains_point(self, x, y, inside):
        b = ViewportBounds(x_min=0, y_min=0, x_max=100, y_max=200)
        assert b.contains_point(x, y) is inside

    def test_frozen(self):
        b = ViewportBounds(x_min=0, y_min=0, x_max=10, y_max=10)
        with pytest.raises(AttributeError):
            b.x_min = 5  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════
# CoordinateTransformer
# ═══════════════════════════════════════════════════════════════════
class TestCoordinateTransformer:
    """Tests for coordinate conversion logic."""

    @pytest.fixture()
    def tx(self) -> CoordinateTransformer:
        return CoordinateTransformer(mpp=0.25, level_0_width=10000, level_0_height=8000)

    # ── downsample_factor ─────────────────────────────────────

    @pytest.mark.parametrize("level,expected", [
        (0, 1),
        (1, 2),
        (2, 4),
        (3, 8),
        (10, 1024),
    ])
    def test_downsample_factor(self, level, expected):
        assert CoordinateTransformer.downsample_factor(level) == expected

    # ── viewport_to_level0 ────────────────────────────────────

    def test_viewport_to_level0_level0(self, tx):
        assert tx.viewport_to_level0(100, 200, level=0) == (100, 200)

    def test_viewport_to_level0_level2(self, tx):
        assert tx.viewport_to_level0(100, 200, level=2) == (400, 800)

    # ── Physical unit conversions ─────────────────────────────

    def test_px_to_um(self, tx):
        assert tx.px_to_um(100) == 25.0  # 100 * 0.25

    def test_px_to_mm(self, tx):
        assert math.isclose(tx.px_to_mm(4000), 1.0, rel_tol=1e-9)

    def test_area_px_to_um2(self, tx):
        assert math.isclose(tx.area_px_to_um2(100), 100 * 0.0625, rel_tol=1e-9)

    def test_area_px_to_mm2(self, tx):
        expected = 100 * 0.0625 * 1e-6
        assert math.isclose(tx.area_px_to_mm2(100), expected, rel_tol=1e-9)

    # ── density_per_mm2 ──────────────────────────────────────

    def test_density_per_mm2(self, tx):
        area_px = 4000 * 4000  # = 16e6 px²
        area_mm2 = 16e6 * (0.25 ** 2) * 1e-6  # = 1 mm²
        density = tx.density_per_mm2(500, area_px)
        assert math.isclose(density, 500.0 / area_mm2, rel_tol=1e-9)

    def test_density_per_mm2_zero_area(self, tx):
        assert tx.density_per_mm2(500, 0.0) == 0.0

    # ── viewport_bounds_to_level0 ─────────────────────────────

    def test_viewport_bounds_to_level0_identity(self, tx):
        b = tx.viewport_bounds_to_level0(100, 200, 300, 400, level=0)
        assert b.x_min == 100
        assert b.y_min == 200
        assert b.x_max == 400
        assert b.y_max == 600

    def test_viewport_bounds_to_level0_scaled(self, tx):
        b = tx.viewport_bounds_to_level0(100, 200, 300, 400, level=1)
        # ds=2: x_min=200, y_min=400, x_max=(100+300)*2=800, y_max=(200+400)*2=1200
        assert b.x_min == 200
        assert b.y_min == 400
        assert b.x_max == 800
        assert b.y_max == 1200

    def test_viewport_bounds_clamped_negative(self, tx):
        b = tx.viewport_bounds_to_level0(-50, -50, 100, 100, level=0)
        assert b.x_min == 0.0
        assert b.y_min == 0.0

    def test_viewport_bounds_clamped_overflow(self, tx):
        b = tx.viewport_bounds_to_level0(9000, 7000, 5000, 5000, level=0)
        assert b.x_max == 10000.0
        assert b.y_max == 8000.0

    # ── bounds_from_level0_rect ───────────────────────────────

    def test_bounds_from_level0_rect(self, tx):
        b = tx.bounds_from_level0_rect(100, 200, 300, 400)
        assert b.x_min == 100
        assert b.y_min == 200
        assert b.x_max == 400
        assert b.y_max == 600

    def test_bounds_from_level0_rect_clamped(self, tx):
        b = tx.bounds_from_level0_rect(-100, -100, 20000, 20000)
        assert b.x_min == 0.0
        assert b.y_min == 0.0
        assert b.x_max == 10000.0
        assert b.y_max == 8000.0

    # ── scale_bar_px ──────────────────────────────────────────

    def test_scale_bar_px_level0(self, tx):
        # 100 μm / 0.25 μm/px = 400 px
        assert math.isclose(tx.scale_bar_px(100, level=0), 400.0, rel_tol=1e-9)

    def test_scale_bar_px_level1(self, tx):
        # ds=2 → 100 / (0.25 * 2) = 200 px
        assert math.isclose(tx.scale_bar_px(100, level=1), 200.0, rel_tol=1e-9)

    def test_scale_bar_px_level3(self, tx):
        # ds=8 → 100 / (0.25 * 8) = 50 px
        assert math.isclose(tx.scale_bar_px(100, level=3), 50.0, rel_tol=1e-9)
