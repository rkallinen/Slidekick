"""
Tests for app.services.slide — SlideService, thread-local helpers,
caching, and DZI generation.
"""
from __future__ import annotations

import io
import threading
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch, call

import numpy as np
import pytest
from PIL import Image

from app.services.slide import (
    SlideService,
    _tls,
    _tls_dz,
    _tls_open,
    get_slide_service,
    invalidate_slide_service,
)


# ═══════════════════════════════════════════════════════════════════
# Thread-local helpers
# ═══════════════════════════════════════════════════════════════════
class TestTlsOpen:
    @patch("app.services.slide.OpenSlide")
    def test_creates_handle_on_first_call(self, mock_os_cls):
        # Clear TLS state
        if hasattr(_tls, "slides"):
            del _tls.slides
        mock_handle = MagicMock()
        mock_os_cls.return_value = mock_handle

        result = _tls_open("/fake/slide.svs")
        assert result is mock_handle
        mock_os_cls.assert_called_once_with("/fake/slide.svs")

        # Clean up
        del _tls.slides

    @patch("app.services.slide.OpenSlide")
    def test_caches_handle(self, mock_os_cls):
        if hasattr(_tls, "slides"):
            del _tls.slides
        mock_handle = MagicMock()
        mock_os_cls.return_value = mock_handle

        r1 = _tls_open("/fake/slide.svs")
        r2 = _tls_open("/fake/slide.svs")
        assert r1 is r2
        assert mock_os_cls.call_count == 1

        del _tls.slides


class TestTlsDz:
    @patch("app.services.slide.DeepZoomGenerator")
    @patch("app.services.slide.OpenSlide")
    def test_creates_dz_on_first_call(self, mock_os_cls, mock_dz_cls):
        if hasattr(_tls, "slides"):
            del _tls.slides
        if hasattr(_tls, "dzgens"):
            del _tls.dzgens

        mock_handle = MagicMock()
        mock_os_cls.return_value = mock_handle
        mock_dz = MagicMock()
        mock_dz_cls.return_value = mock_dz

        result = _tls_dz("/fake/slide.svs")
        assert result is mock_dz
        mock_dz_cls.assert_called_once()

        del _tls.slides
        del _tls.dzgens

    @patch("app.services.slide.DeepZoomGenerator")
    @patch("app.services.slide.OpenSlide")
    def test_caches_dz(self, mock_os_cls, mock_dz_cls):
        if hasattr(_tls, "slides"):
            del _tls.slides
        if hasattr(_tls, "dzgens"):
            del _tls.dzgens

        mock_handle = MagicMock()
        mock_os_cls.return_value = mock_handle
        mock_dz = MagicMock()
        mock_dz_cls.return_value = mock_dz

        r1 = _tls_dz("/fake/slide.svs")
        r2 = _tls_dz("/fake/slide.svs")
        assert r1 is r2
        assert mock_dz_cls.call_count == 1

        del _tls.slides
        del _tls.dzgens


# ═══════════════════════════════════════════════════════════════════
# SlideService
# ═══════════════════════════════════════════════════════════════════
class TestSlideService:
    @pytest.fixture()
    def mock_openslide(self):
        """Patch OpenSlide for SlideService.__init__."""
        with patch("app.services.slide.OpenSlide") as MockOS:
            handle = MagicMock()
            handle.dimensions = (50000, 40000)
            handle.level_count = 5
            handle.level_dimensions = (
                (50000, 40000),
                (25000, 20000),
                (12500, 10000),
                (6250, 5000),
                (3125, 2500),
            )
            handle.properties = {
                "openslide.mpp-x": "0.252",
                "openslide.objective-power": "40",
                "openslide.vendor": "aperio",
            }
            MockOS.return_value = handle
            yield handle

    def test_init_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="WSI not found"):
            SlideService("/nonexistent/path.svs")

    def test_init_extracts_metadata(self, mock_openslide, tmp_path):
        # Create a dummy file
        slide_file = tmp_path / "test.svs"
        slide_file.touch()

        svc = SlideService(slide_file)
        assert svc.dimensions == (50000, 40000)
        assert svc.level_count == 5
        assert len(svc.level_dimensions) == 5
        assert "openslide.vendor" in svc.properties

    def test_init_closes_handle(self, mock_openslide, tmp_path):
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        SlideService(slide_file)
        mock_openslide.close.assert_called_once()

    def test_mpp_from_metadata(self, mock_openslide, tmp_path):
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        svc = SlideService(slide_file)
        assert svc.mpp == 0.252

    def test_mpp_falls_back_to_default(self, mock_openslide, tmp_path):
        mock_openslide.properties = {}
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        svc = SlideService(slide_file)
        # Should use settings.default_mpp (0.25)
        assert svc.mpp == 0.25

    def test_slide_info(self, mock_openslide, tmp_path):
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        svc = SlideService(slide_file)
        info = svc.slide_info()
        assert info["filename"] == "test.svs"
        assert info["width_px"] == 50000
        assert info["height_px"] == 40000
        assert info["mpp"] == 0.252
        assert "width_mm" in info
        assert "height_mm" in info
        assert info["level_count"] == 5
        assert info["magnification"] == "40"
        assert info["vendor"] == "aperio"

    def test_slide_info_unknown_magnification(self, mock_openslide, tmp_path):
        mock_openslide.properties = {}
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        svc = SlideService(slide_file)
        info = svc.slide_info()
        assert info["magnification"] == "unknown"
        assert info["vendor"] == "unknown"

    # ── DZI methods ───────────────────────────────────────────

    @patch("app.services.slide._tls_dz")
    def test_get_dzi_xml(self, mock_dz_fn, mock_openslide, tmp_path):
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        svc = SlideService(slide_file)

        mock_dz = MagicMock()
        mock_dz.get_dzi.return_value = '<Image TileSize="254"/>'
        mock_dz_fn.return_value = mock_dz

        xml = svc.get_dzi_xml()
        assert "TileSize" in xml

    @patch("app.services.slide._tls_dz")
    def test_get_dzi_tile(self, mock_dz_fn, mock_openslide, tmp_path):
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        svc = SlideService(slide_file)

        # Create a real small JPEG
        img = Image.new("RGB", (10, 10), color="red")
        buf = io.BytesIO()
        img.save(buf, "JPEG")
        expected_bytes = buf.getvalue()

        mock_tile = MagicMock(spec=Image.Image)
        mock_tile.save = MagicMock(side_effect=lambda b, **kw: b.write(expected_bytes))

        mock_dz = MagicMock()
        mock_dz.get_tile.return_value = mock_tile
        mock_dz_fn.return_value = mock_dz

        result = svc.get_dzi_tile(level=12, col=5, row=3)
        assert isinstance(result, bytes)

    @patch("app.services.slide._tls_dz")
    def test_dzi_level_count(self, mock_dz_fn, mock_openslide, tmp_path):
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        svc = SlideService(slide_file)

        mock_dz = MagicMock()
        mock_dz.level_count = 15
        mock_dz_fn.return_value = mock_dz

        assert svc.dzi_level_count == 15

    @patch("app.services.slide._tls_dz")
    def test_dzi_tile_count(self, mock_dz_fn, mock_openslide, tmp_path):
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        svc = SlideService(slide_file)

        mock_dz = MagicMock()
        mock_dz.tile_count = 1000
        mock_dz_fn.return_value = mock_dz

        assert svc.dzi_tile_count == 1000

    # ── read_region_l0 ────────────────────────────────────────

    @patch("app.services.slide._tls_open")
    def test_read_region_l0(self, mock_open_fn, mock_openslide, tmp_path):
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        svc = SlideService(slide_file)

        mock_slide = MagicMock()
        mock_img = Image.new("RGBA", (100, 100), "white")
        mock_slide.read_region.return_value = mock_img
        mock_open_fn.return_value = mock_slide

        arr = svc.read_region_l0(x=0, y=0, width=100, height=100)
        assert isinstance(arr, np.ndarray)
        assert arr.shape == (100, 100, 3)

    @patch("app.services.slide._tls_open")
    def test_read_region_l0_clamps(self, mock_open_fn, mock_openslide, tmp_path):
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        svc = SlideService(slide_file)

        mock_slide = MagicMock()
        mock_img = Image.new("RGBA", (50, 40), "white")
        mock_slide.read_region.return_value = mock_img
        mock_open_fn.return_value = mock_slide

        # Request beyond slide bounds (50000x40000)
        arr = svc.read_region_l0(x=49990, y=39990, width=100, height=100)
        # Should clamp and still return an array
        assert isinstance(arr, np.ndarray)

    @patch("app.services.slide._tls_open")
    def test_read_region_l0_negative_dimensions(self, mock_open_fn, mock_openslide, tmp_path):
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        svc = SlideService(slide_file)

        mock_slide = MagicMock()
        mock_open_fn.return_value = mock_slide

        with pytest.raises(ValueError, match="Invalid region dimensions"):
            svc.read_region_l0(x=0, y=0, width=-1, height=100)

    @patch("app.services.slide._tls_open")
    def test_read_region_l0_zero_height(self, mock_open_fn, mock_openslide, tmp_path):
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        svc = SlideService(slide_file)

        mock_slide = MagicMock()
        mock_open_fn.return_value = mock_slide

        with pytest.raises(ValueError, match="Invalid region dimensions"):
            svc.read_region_l0(x=0, y=0, width=100, height=0)

    # ── close / context manager ───────────────────────────────

    def test_context_manager(self, mock_openslide, tmp_path):
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        with SlideService(slide_file) as svc:
            assert svc.dimensions == (50000, 40000)

    def test_close_cleans_tls(self, mock_openslide, tmp_path):
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        svc = SlideService(slide_file)

        # Pre-populate TLS
        if not hasattr(_tls, "slides"):
            _tls.slides = {}
        if not hasattr(_tls, "dzgens"):
            _tls.dzgens = {}

        mock_handle = MagicMock()
        _tls.slides[svc._filepath_str] = mock_handle
        _tls.dzgens[svc._filepath_str] = MagicMock()

        svc.close()
        assert svc._filepath_str not in _tls.slides
        assert svc._filepath_str not in _tls.dzgens
        mock_handle.close.assert_called_once()

    def test_close_no_tls_state(self, mock_openslide, tmp_path):
        """close() when TLS has no slides/dzgens attrs at all."""
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        svc = SlideService(slide_file)

        # Ensure _tls has no attributes
        if hasattr(_tls, "slides"):
            del _tls.slides
        if hasattr(_tls, "dzgens"):
            del _tls.dzgens

        svc.close()  # Should not raise

    def test_close_handle_not_in_tls(self, mock_openslide, tmp_path):
        """close() when TLS has slides dict but this path isn't in it."""
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        svc = SlideService(slide_file)

        if not hasattr(_tls, "slides"):
            _tls.slides = {}
        if not hasattr(_tls, "dzgens"):
            _tls.dzgens = {}
        # Don't add the filepath to _tls.slides — pop returns None
        svc.close()  # Should not raise

    def test_exit_calls_close(self, mock_openslide, tmp_path):
        """__exit__ delegates to close()."""
        slide_file = tmp_path / "test.svs"
        slide_file.touch()
        svc = SlideService(slide_file)
        svc.close = MagicMock()
        svc.__exit__(None, None, None)
        svc.close.assert_called_once()


# ═══════════════════════════════════════════════════════════════════
# get_slide_service / invalidate_slide_service
# ═══════════════════════════════════════════════════════════════════
class TestSlideServiceFactory:
    @patch("app.services.slide.OpenSlide")
    def test_get_slide_service_caches(self, mock_os_cls, tmp_path):
        get_slide_service.cache_clear()
        slide_file = tmp_path / "test.svs"
        slide_file.touch()

        handle = MagicMock()
        handle.dimensions = (1000, 1000)
        handle.level_count = 1
        handle.level_dimensions = ((1000, 1000),)
        handle.properties = {}
        mock_os_cls.return_value = handle

        s1 = get_slide_service(str(slide_file))
        s2 = get_slide_service(str(slide_file))
        assert s1 is s2
        get_slide_service.cache_clear()

    @patch("app.services.slide.OpenSlide")
    def test_invalidate_clears_cache(self, mock_os_cls, tmp_path):
        get_slide_service.cache_clear()
        slide_file = tmp_path / "test.svs"
        slide_file.touch()

        handle = MagicMock()
        handle.dimensions = (1000, 1000)
        handle.level_count = 1
        handle.level_dimensions = ((1000, 1000),)
        handle.properties = {}
        mock_os_cls.return_value = handle

        s1 = get_slide_service(str(slide_file))
        invalidate_slide_service(str(slide_file))
        s2 = get_slide_service(str(slide_file))
        assert s1 is not s2
        get_slide_service.cache_clear()

    def test_invalidate_closes_tls_handles(self, tmp_path):
        filepath = str(tmp_path / "test.svs")
        if not hasattr(_tls, "slides"):
            _tls.slides = {}
        if not hasattr(_tls, "dzgens"):
            _tls.dzgens = {}

        mock_handle = MagicMock()
        _tls.slides[filepath] = mock_handle
        _tls.dzgens[filepath] = MagicMock()

        get_slide_service.cache_clear()
        invalidate_slide_service(filepath)

        assert filepath not in _tls.slides
        assert filepath not in _tls.dzgens
        mock_handle.close.assert_called_once()

    def test_invalidate_no_tls_slides(self, tmp_path):
        """invalidate_slide_service when _tls has no slides attr."""
        filepath = str(tmp_path / "test.svs")
        if hasattr(_tls, "slides"):
            del _tls.slides
        if hasattr(_tls, "dzgens"):
            del _tls.dzgens

        get_slide_service.cache_clear()
        invalidate_slide_service(filepath)  # Should not raise

    def test_invalidate_handle_not_in_dict(self, tmp_path):
        """invalidate_slide_service when _tls.slides exists but path isn't in it."""
        filepath = str(tmp_path / "nonexistent.svs")
        if not hasattr(_tls, "slides"):
            _tls.slides = {}
        if not hasattr(_tls, "dzgens"):
            _tls.dzgens = {}
        # Don't add filepath → pop returns None → handle is None branch

        get_slide_service.cache_clear()
        invalidate_slide_service(filepath)  # Should not raise

    def test_invalidate_only_dzgens_no_slides(self, tmp_path):
        """invalidate_slide_service when _tls has dzgens but no slides."""
        filepath = str(tmp_path / "test2.svs")
        if hasattr(_tls, "slides"):
            del _tls.slides
        if not hasattr(_tls, "dzgens"):
            _tls.dzgens = {}
        _tls.dzgens[filepath] = MagicMock()

        get_slide_service.cache_clear()
        invalidate_slide_service(filepath)
        assert filepath not in _tls.dzgens
