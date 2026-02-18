"""
Coordinate Transformation Engine
=================================
Bridges the gap between three coordinate spaces:

1. **Level 0 (L0)** — Native WSI pixel coordinates (highest resolution).
2. **Viewport**     — Tile-level coordinates at a given zoom level.
3. **Physical**     — Real-world μm / mm units derived via MPP.

The fundamental relationship:

    d_physical = d_pixels × MPP
    A_mm²      = A_px × MPP² × 1e-6

All PostGIS geometries are stored in L0 pixel coordinates (SRID 0).
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Polygon, box


# ── Bounding Box (viewport rectangle) ────────────────────────────
@dataclass(frozen=True, slots=True)
class ViewportBounds:
    """A rectangle in Level-0 pixel coordinates."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def width_px(self) -> float:
        return self.x_max - self.x_min

    @property
    def height_px(self) -> float:
        return self.y_max - self.y_min

    @property
    def area_px(self) -> float:
        return self.width_px * self.height_px

    def area_mm2(self, mpp: float) -> float:
        """Convert pixel area to mm² using Microns-Per-Pixel."""
        return self.area_px * (mpp ** 2) * 1e-6

    def to_shapely(self) -> Polygon:
        """Return a Shapely box for use with spatial queries."""
        return box(self.x_min, self.y_min, self.x_max, self.y_max)

    def to_wkt(self) -> str:
        """WKT polygon string for PostGIS ST_GeomFromText."""
        poly = self.to_shapely()
        return poly.wkt

    def contains_point(self, x: float, y: float) -> bool:
        return (
            self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max
        )


# ── Coordinate Transformer ───────────────────────────────────────
class CoordinateTransformer:
    """
    Handles all coordinate conversions between WSI levels, physical
    space, and PostGIS geometry representations.

    Parameters
    ----------
    mpp : float
        Microns-Per-Pixel at Level 0.
    level_0_width : int
        Full width of the WSI at Level 0 in pixels.
    level_0_height : int
        Full height of the WSI at Level 0 in pixels.
    """

    def __init__(
        self, mpp: float, level_0_width: int, level_0_height: int
    ) -> None:
        self.mpp = mpp
        self.l0_width = level_0_width
        self.l0_height = level_0_height

    # ── Level conversion ──────────────────────────────────────

    @staticmethod
    def downsample_factor(level: int) -> int:
        """
        OpenSlide levels are powers of 2.
        Level 0 → 1×, Level 1 → 2×, Level 2 → 4×, …
        """
        return 1 << level  # 2^level

    def viewport_to_level0(
        self,
        vp_x: float,
        vp_y: float,
        level: int,
    ) -> tuple[float, float]:
        """Convert viewport-level coordinates to Level-0 pixels."""
        ds = self.downsample_factor(level)
        return vp_x * ds, vp_y * ds

    # ── Physical unit conversion ──────────────────────────────

    def px_to_um(self, distance_px: float) -> float:
        """Convert a pixel distance to micrometres."""
        return distance_px * self.mpp

    def px_to_mm(self, distance_px: float) -> float:
        return distance_px * self.mpp * 1e-3

    def area_px_to_um2(self, area_px: float) -> float:
        """Convert pixel² area to μm²."""
        return area_px * (self.mpp ** 2)

    def area_px_to_mm2(self, area_px: float) -> float:
        """Convert pixel² area to mm²."""
        return area_px * (self.mpp ** 2) * 1e-6

    # ── Density calculation ───────────────────────────────────

    def density_per_mm2(self, count: int, area_px: float) -> float:
        """
        Compute nuclear density: nuclei per mm².

            ρ = N / (A_px × MPP² × 10⁻⁶)
        """
        area_mm2 = self.area_px_to_mm2(area_px)
        if area_mm2 == 0:
            return 0.0
        return count / area_mm2

    # ── Viewport bounds construction ──────────────────────────

    def viewport_bounds_to_level0(
        self,
        vp_x: float,
        vp_y: float,
        vp_w: float,
        vp_h: float,
        level: int,
    ) -> ViewportBounds:
        """
        Convert a viewport rectangle (x, y, w, h at a given level)
        to Level-0 pixel coordinates, clamped to the slide extent.
        """
        ds = self.downsample_factor(level)
        x_min = max(0.0, vp_x * ds)
        y_min = max(0.0, vp_y * ds)
        x_max = min(float(self.l0_width), (vp_x + vp_w) * ds)
        y_max = min(float(self.l0_height), (vp_y + vp_h) * ds)
        return ViewportBounds(x_min, y_min, x_max, y_max)

    def bounds_from_level0_rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
    ) -> ViewportBounds:
        """Create ViewportBounds directly from Level-0 coords."""
        return ViewportBounds(
            x_min=max(0.0, x),
            y_min=max(0.0, y),
            x_max=min(float(self.l0_width), x + w),
            y_max=min(float(self.l0_height), y + h),
        )

    # ── Scale bar computation ─────────────────────────────────

    def scale_bar_px(self, target_um: float, level: int = 0) -> float:
        """
        How many pixels at the given level correspond to `target_um`
        micrometres?  Used by VirtualMicrometer on the frontend.
        """
        ds = self.downsample_factor(level)
        return target_um / (self.mpp * ds)
