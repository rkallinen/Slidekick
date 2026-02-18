"""
OpenSlide Wrapper + Deep Zoom Image (DZI) Generation
=====================================================
Provides thread-safe WSI access and DZI tile serving for
the OpenSeadragon viewer.

Thread-Safety Model
-------------------
OpenSlide's C library (``libopenslide``) is **not** thread-safe:
concurrent reads from the same ``OpenSlide`` handle can produce
corrupted tiles or segfaults.

This module uses **thread-local storage** (``threading.local()``)
so that every OS thread obtains its own independent ``OpenSlide``
handle for a given file.  The ``SlideService`` class itself is
shareable across threads (and cached via ``@lru_cache``), but every
call that touches the C library goes through ``_get_slide()`` /
``_get_dz()``, which return a per-thread handle.

This eliminates the need for a global ``threading.Lock`` on every
read operation and allows truly parallel tile serving from the
bounded ``ThreadPoolExecutor`` configured in ``main.py``.
"""

from __future__ import annotations

import io
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from openslide import OpenSlide
from openslide.deepzoom import DeepZoomGenerator
from PIL import Image

from app.config import get_settings

settings = get_settings()

# ── Thread-local storage for OpenSlide handles ────────────────────
_tls = threading.local()


def _tls_open(filepath: str) -> OpenSlide:
    """
    Return a thread-local ``OpenSlide`` handle for *filepath*.

    Each thread maintains its own ``dict[str, OpenSlide]`` so that
    no two threads ever touch the same C-level handle.
    """
    if not hasattr(_tls, "slides"):
        _tls.slides = {}
    handle = _tls.slides.get(filepath)
    if handle is None:
        handle = OpenSlide(filepath)
        _tls.slides[filepath] = handle
    return handle


def _tls_dz(filepath: str) -> DeepZoomGenerator:
    """
    Return a thread-local ``DeepZoomGenerator`` for *filepath*.
    """
    if not hasattr(_tls, "dzgens"):
        _tls.dzgens = {}
    dz = _tls.dzgens.get(filepath)
    if dz is None:
        slide = _tls_open(filepath)
        dz = DeepZoomGenerator(slide, tile_size=254, overlap=1, limit_bounds=True)
        _tls.dzgens[filepath] = dz
    return dz


class SlideService:
    """
    Manages WSI access, metadata extraction, and DZI tile generation.

    One ``SlideService`` instance per unique slide filepath is cached
    by ``get_slide_service()``.  The instance itself stores only the
    filepath; all OpenSlide / DeepZoomGenerator access is performed
    through thread-local helpers so concurrent threads never share a
    C-level handle.

    The **one eagerly-opened handle** (``self._meta_slide``) is used
    exclusively during ``__init__`` on the calling thread to validate
    the file and extract metadata.  It is closed immediately after
    metadata capture to avoid keeping a long-lived handle that could
    be shared across threads.
    """

    def __init__(self, filepath: str | Path) -> None:
        self.filepath = Path(filepath)
        if not self.filepath.exists():
            raise FileNotFoundError(f"WSI not found: {self.filepath}")
        self._filepath_str = str(self.filepath)

        # Eagerly open once **on the calling thread** to validate and
        # capture immutable metadata, then close.
        tmp = OpenSlide(self._filepath_str)
        try:
            self._dimensions: tuple[int, int] = tmp.dimensions
            self._level_count: int = tmp.level_count
            self._level_dimensions: tuple[tuple[int, int], ...] = tmp.level_dimensions
            self._properties: dict[str, Any] = dict(tmp.properties)
        finally:
            tmp.close()

    # ── Metadata (immutable, captured at init — no lock needed) ──

    @property
    def dimensions(self) -> tuple[int, int]:
        """(width, height) at Level 0 in pixels."""
        return self._dimensions

    @property
    def level_count(self) -> int:
        return self._level_count

    @property
    def level_dimensions(self) -> tuple[tuple[int, int], ...]:
        return self._level_dimensions

    @property
    def properties(self) -> dict[str, Any]:
        """All vendor-specific slide properties."""
        return dict(self._properties)

    @property
    def mpp(self) -> float:
        """
        Extract Microns-Per-Pixel from WSI metadata.

        OpenSlide exposes this as 'openslide.mpp-x' (and mpp-y).
        Falls back to the global default if not present.
        """
        mpp_x = self._properties.get("openslide.mpp-x")
        if mpp_x is not None:
            return float(mpp_x)
        return settings.default_mpp

    def slide_info(self) -> dict[str, Any]:
        """Summary dict for the slides API."""
        w, h = self._dimensions
        mpp = self.mpp
        return {
            "filename": self.filepath.name,
            "filepath": str(self.filepath),
            "width_px": w,
            "height_px": h,
            "mpp": mpp,
            "width_mm": w * mpp * 1e-3,
            "height_mm": h * mpp * 1e-3,
            "level_count": self._level_count,
            "magnification": self._properties.get(
                "openslide.objective-power", "unknown"
            ),
            "vendor": self._properties.get("openslide.vendor", "unknown"),
        }

    # ── DZI (Deep Zoom Image) — thread-local handles ─────────

    def get_dzi_xml(self) -> str:
        """Return the DZI XML descriptor for OpenSeadragon."""
        dz = _tls_dz(self._filepath_str)
        return dz.get_dzi("jpeg")

    def get_dzi_tile(
        self,
        level: int,
        col: int,
        row: int,
        fmt: str = "jpeg",
    ) -> bytes:
        """
        Render a single DZI tile as bytes.

        Thread-safe: each thread uses its own OpenSlide handle via
        thread-local storage — no lock contention.

        Parameters
        ----------
        level : int   — DZI zoom level (NOT OpenSlide level).
        col, row : int — Tile column and row.
        fmt : str — "jpeg" or "png".
        """
        dz = _tls_dz(self._filepath_str)
        tile: Image.Image = dz.get_tile(level, (col, row))
        buf = io.BytesIO()
        tile.save(buf, format=fmt, quality=85)
        return buf.getvalue()

    @property
    def dzi_level_count(self) -> int:
        dz = _tls_dz(self._filepath_str)
        return dz.level_count

    @property
    def dzi_tile_count(self) -> int:
        dz = _tls_dz(self._filepath_str)
        return dz.tile_count

    # ── Region extraction (for inference) — thread-local ──────

    def read_region_l0(
        self, x: int, y: int, width: int, height: int
    ) -> np.ndarray:
        """
        Read a region at Level 0 and return as an RGB numpy array.

        Thread-safe: uses a thread-local OpenSlide handle.

        Parameters
        ----------
        x, y : int — Top-left corner in Level-0 pixels.
        width, height : int — Region dimensions.

        Returns
        -------
        np.ndarray — Shape (height, width, 3), dtype uint8, RGB.
        """
        import logging
        logger = logging.getLogger(__name__)

        slide = _tls_open(self._filepath_str)
        slide_width, slide_height = self._dimensions

        # Validate inputs before passing to OpenSlide
        if width <= 0 or height <= 0:
            logger.error(
                "Negative or zero dimensions: slide_path=%s, slide_dims=(%d,%d), "
                "x=%d, y=%d, width=%d, height=%d",
                self.filepath, slide_width, slide_height, x, y, width, height,
            )
            raise ValueError(
                f"Invalid region dimensions: width={width}, height={height} "
                f"(must be positive)"
            )

        # Clamp coordinates to slide bounds
        x_clamped = max(0, min(int(x), slide_width - 1))
        y_clamped = max(0, min(int(y), slide_height - 1))

        # Clamp dimensions to available space
        width_clamped = min(int(width), slide_width - x_clamped)
        height_clamped = min(int(height), slide_height - y_clamped)

        # Log if clamping was necessary
        if (x_clamped != x or y_clamped != y or
                width_clamped != width or height_clamped != height):
            logger.warning(
                "Region clamped to slide bounds: "
                "original=(x=%d, y=%d, w=%d, h=%d), "
                "clamped=(x=%d, y=%d, w=%d, h=%d), "
                "slide_dims=(%d,%d)",
                x, y, width, height,
                x_clamped, y_clamped, width_clamped, height_clamped,
                slide_width, slide_height,
            )

        # Thread-safe: thread-local OpenSlide handle — no lock needed
        region = slide.read_region(
            (x_clamped, y_clamped), 0, (width_clamped, height_clamped)
        )
        return np.array(region.convert("RGB"))

    # ── Cleanup ───────────────────────────────────────────────

    def close(self) -> None:
        """
        Close the thread-local OpenSlide handle for this file (if any).

        Note: This only closes the handle on the *calling* thread.
        Other threads' handles are cleaned up when those threads exit
        (Python destroys ``threading.local`` data on thread teardown).
        """
        if hasattr(_tls, "dzgens"):
            _tls.dzgens.pop(self._filepath_str, None)
        if hasattr(_tls, "slides"):
            handle = _tls.slides.pop(self._filepath_str, None)
            if handle is not None:
                handle.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ── Cached factory ────────────────────────────────────────────────
@lru_cache(maxsize=16)
def get_slide_service(filepath: str) -> SlideService:
    """
    Return a cached SlideService instance for the given filepath.

    The ``SlideService`` itself only stores metadata and the filepath.
    All OpenSlide C-library access goes through thread-local storage,
    so the cached instance is safe to share across threads.
    """
    return SlideService(filepath)


def invalidate_slide_service(filepath: str) -> None:
    """
    Remove a specific filepath from the ``get_slide_service`` LRU cache.

    Call this when a slide file is deleted from disk so the stale
    ``SlideService`` reference is evicted.  The next call to
    ``get_slide_service`` for this filepath will create a fresh instance
    (and fail with ``FileNotFoundError`` if the file truly no longer
    exists).

    Also closes any thread-local OpenSlide handles for the filepath
    on the calling thread.
    """
    # Close thread-local handles on the current thread.
    filepath_str = str(filepath)
    if hasattr(_tls, "dzgens"):
        _tls.dzgens.pop(filepath_str, None)
    if hasattr(_tls, "slides"):
        handle = _tls.slides.pop(filepath_str, None)
        if handle is not None:
            handle.close()

    # Evict from LRU cache by clearing and re-populating would be
    # expensive.  Instead, we rebuild the cache without the target key.
    # Python 3.8+ lru_cache exposes cache_info but not per-key eviction,
    # so we clear the entire cache.  With maxsize=16 for slide metadata
    # this is effectively free.
    get_slide_service.cache_clear()
