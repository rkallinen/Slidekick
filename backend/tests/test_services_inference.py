"""
Tests for app.services.inference — HoVerNet engine, geometry helpers,
progress tracking, device selection, and output parsing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from app.services.inference import (
    DetectedNucleus,
    HoVerNetEngine,
    InferenceResult,
    ProgressTracker,
    _select_device,
)


# ═══════════════════════════════════════════════════════════════════
# ProgressTracker
# ═══════════════════════════════════════════════════════════════════
class TestProgressTracker:
    def test_initial_state(self):
        pt = ProgressTracker()
        p = pt.get_progress()
        assert p["current"] == 0
        assert p["total"] == 0
        assert p["percentage"] == 0
        assert p["message"] == ""

    def test_update_and_get(self):
        pt = ProgressTracker()
        pt.update(5, 10, "Half done")
        p = pt.get_progress()
        assert p["current"] == 5
        assert p["total"] == 10
        assert p["percentage"] == 50
        assert p["message"] == "Half done"

    def test_percentage_100(self):
        pt = ProgressTracker()
        pt.update(10, 10, "Done")
        assert pt.get_progress()["percentage"] == 100

    def test_percentage_zero_total(self):
        pt = ProgressTracker()
        pt.update(5, 0, "")
        assert pt.get_progress()["percentage"] == 0


# ═══════════════════════════════════════════════════════════════════
# InferenceResult
# ═══════════════════════════════════════════════════════════════════
class TestInferenceResult:
    def test_empty(self):
        r = InferenceResult()
        assert r.count == 0
        assert r.nuclei == []
        assert r.tile_x == 0

    def test_count_matches_nuclei(self):
        nuc = DetectedNucleus(
            centroid_x=10, centroid_y=20,
            contour=np.array([[0, 0], [1, 0], [1, 1]]),
            cell_type=1, cell_type_name="Neoplastic",
            probability=0.9,
        )
        r = InferenceResult(nuclei=[nuc, nuc], tile_x=100, tile_y=200, tile_w=256, tile_h=256)
        assert r.count == 2
        assert r.tile_x == 100


# ═══════════════════════════════════════════════════════════════════
# DetectedNucleus
# ═══════════════════════════════════════════════════════════════════
class TestDetectedNucleus:
    def test_defaults(self):
        nuc = DetectedNucleus(
            centroid_x=10, centroid_y=20,
            contour=np.array([[0, 0], [1, 0], [1, 1]]),
            cell_type=0, cell_type_name="Background",
            probability=0.5,
        )
        assert nuc.area_um2 == 0.0
        assert nuc.perimeter_um == 0.0


# ═══════════════════════════════════════════════════════════════════
# _select_device
# ═══════════════════════════════════════════════════════════════════
class TestSelectDevice:
    def test_explicit_override(self):
        assert _select_device("cuda:1") == "cuda:1"

    def test_settings_override(self):
        with patch("app.services.inference.settings") as mock_settings:
            mock_settings.device = "mps"
            assert _select_device(None) == "mps"

    def test_mps_available(self):
        with (
            patch("app.services.inference.settings") as mock_settings,
            patch("app.services.inference.torch") as mock_torch,
        ):
            mock_settings.device = ""
            mock_torch.backends.mps.is_available.return_value = True
            assert _select_device(None) == "mps"

    def test_cuda_available(self):
        with (
            patch("app.services.inference.settings") as mock_settings,
            patch("app.services.inference.torch") as mock_torch,
        ):
            mock_settings.device = ""
            mock_torch.backends.mps.is_available.return_value = False
            mock_torch.cuda.is_available.return_value = True
            assert _select_device(None) == "cuda"

    def test_cpu_fallback(self):
        with (
            patch("app.services.inference.settings") as mock_settings,
            patch("app.services.inference.torch") as mock_torch,
        ):
            mock_settings.device = ""
            mock_torch.backends.mps.is_available.return_value = False
            mock_torch.cuda.is_available.return_value = False
            assert _select_device(None) == "cpu"


# ═══════════════════════════════════════════════════════════════════
# HoVerNetEngine — geometry helpers
# ═══════════════════════════════════════════════════════════════════
class TestGeometryHelpers:
    """Test _polygon_area and _polygon_perimeter (static methods)."""

    def test_polygon_area_triangle(self):
        # Right triangle with legs 3 and 4 → area = 6
        verts = np.array([[0, 0], [3, 0], [0, 4]], dtype=np.float64)
        assert math.isclose(HoVerNetEngine._polygon_area(verts), 6.0, rel_tol=1e-9)

    def test_polygon_area_square(self):
        verts = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=np.float64)
        assert math.isclose(HoVerNetEngine._polygon_area(verts), 100.0, rel_tol=1e-9)

    def test_polygon_area_fewer_than_3(self):
        assert HoVerNetEngine._polygon_area(np.array([[0, 0], [1, 1]])) == 0.0

    def test_polygon_area_single_point(self):
        assert HoVerNetEngine._polygon_area(np.array([[5, 5]])) == 0.0

    def test_polygon_area_empty(self):
        assert HoVerNetEngine._polygon_area(np.array([])) == 0.0

    def test_polygon_perimeter_square(self):
        verts = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=np.float64)
        assert math.isclose(HoVerNetEngine._polygon_perimeter(verts), 40.0, rel_tol=1e-9)

    def test_polygon_perimeter_fewer_than_2(self):
        assert HoVerNetEngine._polygon_perimeter(np.array([[0, 0]])) == 0.0

    def test_polygon_perimeter_empty(self):
        assert HoVerNetEngine._polygon_perimeter(np.array([])) == 0.0


# ═══════════════════════════════════════════════════════════════════
# HoVerNetEngine — _parse_raw_output
# ═══════════════════════════════════════════════════════════════════
class TestParseRawOutput:
    """Test the raw output parsing without loading TIAToolbox."""

    @pytest.fixture()
    def engine(self):
        """Create engine without loading model (skip TIAToolbox)."""
        with patch("app.services.inference._select_device", return_value="cpu"):
            eng = HoVerNetEngine(device="cpu")
        return eng

    def test_empty_dict(self, engine):
        result = engine._parse_raw_output({}, 0, 0, 0.25, 256, 256)
        assert result.count == 0
        assert result.tile_x == 0
        assert result.tile_w == 256

    def test_single_nucleus(self, engine):
        raw = {
            0: {
                "centroid": [50.0, 60.0],
                "contour": [[40, 50], [60, 50], [60, 70], [40, 70]],
                "type": 1,
                "prob": 0.95,
            },
        }
        result = engine._parse_raw_output(raw, offset_x=100, offset_y=200, mpp=0.25, tile_h=256, tile_w=256)
        assert result.count == 1
        nuc = result.nuclei[0]
        assert nuc.centroid_x == 150.0  # 50 + 100
        assert nuc.centroid_y == 260.0  # 60 + 200
        assert nuc.cell_type == 1
        assert nuc.cell_type_name == "Neoplastic"
        assert nuc.probability == 0.95
        # Contour should be offset
        assert nuc.contour[0, 0] == 140.0  # 40 + 100
        assert nuc.contour[0, 1] == 250.0  # 50 + 200

    def test_unknown_cell_type(self, engine):
        raw = {
            0: {
                "centroid": [10.0, 10.0],
                "contour": [[0, 0], [20, 0], [20, 20], [0, 20]],
                "type": 99,
                "prob": 0.5,
            },
        }
        result = engine._parse_raw_output(raw, 0, 0, 0.25, 256, 256)
        assert result.nuclei[0].cell_type_name == "Unknown"

    def test_missing_type_defaults_to_zero(self, engine):
        raw = {
            0: {
                "centroid": [10.0, 10.0],
                "contour": [[0, 0], [10, 0], [10, 10]],
            },
        }
        result = engine._parse_raw_output(raw, 0, 0, 0.25, 256, 256)
        assert result.nuclei[0].cell_type == 0
        assert result.nuclei[0].probability == 0.0

    def test_morphometrics_computed(self, engine):
        """Verify area_um2 and perimeter_um are computed from contour."""
        # 10x10 square → area=100px² → 100 * 0.0625 = 6.25 μm²
        raw = {
            0: {
                "centroid": [5.0, 5.0],
                "contour": [[0, 0], [10, 0], [10, 10], [0, 10]],
                "type": 1,
                "prob": 0.9,
            },
        }
        result = engine._parse_raw_output(raw, 0, 0, 0.25, 256, 256)
        nuc = result.nuclei[0]
        assert nuc.area_um2 > 0
        assert nuc.perimeter_um > 0

    def test_multiple_nuclei(self, engine):
        raw = {
            0: {
                "centroid": [10.0, 10.0],
                "contour": [[0, 0], [20, 0], [20, 20]],
                "type": 1,
                "prob": 0.9,
            },
            1: {
                "centroid": [50.0, 50.0],
                "contour": [[40, 40], [60, 40], [60, 60]],
                "type": 2,
                "prob": 0.8,
            },
        }
        result = engine._parse_raw_output(raw, 0, 0, 0.25, 256, 256)
        assert result.count == 2


# ═══════════════════════════════════════════════════════════════════
# HoVerNetEngine — ensure_loaded / load_model
# ═══════════════════════════════════════════════════════════════════
class TestEngineLoading:
    def test_ensure_loaded_calls_load_model(self):
        with patch("app.services.inference._select_device", return_value="cpu"):
            eng = HoVerNetEngine(device="cpu")
        eng.load_model = MagicMock()
        eng.ensure_loaded()
        eng.load_model.assert_called_once()

    def test_ensure_loaded_skips_when_loaded(self):
        with patch("app.services.inference._select_device", return_value="cpu"):
            eng = HoVerNetEngine(device="cpu")
        eng._loaded = True
        eng.load_model = MagicMock()
        eng.ensure_loaded()
        eng.load_model.assert_not_called()


# ═══════════════════════════════════════════════════════════════════
# Singleton — get_inference_engine
# ═══════════════════════════════════════════════════════════════════
class TestGetInferenceEngine:
    def test_returns_engine(self):
        with patch("app.services.inference._select_device", return_value="cpu"):
            import app.services.inference as mod
            mod._engine_instance = None
            eng = mod.get_inference_engine()
            assert isinstance(eng, HoVerNetEngine)

    def test_singleton(self):
        with patch("app.services.inference._select_device", return_value="cpu"):
            import app.services.inference as mod
            mod._engine_instance = None
            e1 = mod.get_inference_engine()
            e2 = mod.get_inference_engine()
            assert e1 is e2
            # Clean up
            mod._engine_instance = None


# ═══════════════════════════════════════════════════════════════════
# HoVerNetEngine.infer_batch
# ═══════════════════════════════════════════════════════════════════
class TestInferBatch:
    def test_infer_batch_delegates_to_infer_tile(self):
        with patch("app.services.inference._select_device", return_value="cpu"):
            eng = HoVerNetEngine(device="cpu")

        fake_result = InferenceResult(nuclei=[], tile_x=0, tile_y=0, tile_w=10, tile_h=10)
        eng.infer_tile = MagicMock(return_value=fake_result)

        tiles = [np.zeros((64, 64, 3), dtype=np.uint8)] * 3
        offsets = [(0, 0), (64, 0), (128, 0)]
        results = eng.infer_batch(tiles, offsets, mpp=0.25)

        assert len(results) == 3
        assert eng.infer_tile.call_count == 3


# ═══════════════════════════════════════════════════════════════════
# HoVerNetEngine.load_model (real TIAToolbox path — fully mocked)
# ═══════════════════════════════════════════════════════════════════
class TestLoadModel:
    def test_load_model_success(self):
        """Ensure load_model calls get_pretrained_model and sets flags."""
        with patch("app.services.inference._select_device", return_value="cpu"):
            eng = HoVerNetEngine(device="cpu")

        mock_model = MagicMock()
        mock_model.to.return_value = mock_model
        mock_ioconfig = MagicMock()
        mock_ioconfig.patch_input_shape = [256, 256]
        mock_ioconfig.patch_output_shape = [164, 164]

        with patch.dict("sys.modules", {"tiatoolbox": MagicMock(), "tiatoolbox.models": MagicMock(), "tiatoolbox.models.architecture": MagicMock()}):
            with patch("tiatoolbox.models.architecture.get_pretrained_model", return_value=(mock_model, mock_ioconfig), create=True):
                # We need to mock the import inside load_model
                import sys
                mock_arch = MagicMock()
                mock_arch.get_pretrained_model.return_value = (mock_model, mock_ioconfig)
                sys.modules["tiatoolbox.models.architecture"] = mock_arch

                eng.load_model()

                assert eng._loaded is True
                assert eng._model is mock_model
                assert eng._ioconfig is mock_ioconfig
                mock_model.to.assert_called_once_with("cpu")
                mock_model.eval.assert_called_once()

                # Clean up
                del sys.modules["tiatoolbox.models.architecture"]

    def test_load_model_failure(self):
        """Ensure load_model re-raises on error."""
        with patch("app.services.inference._select_device", return_value="cpu"):
            eng = HoVerNetEngine(device="cpu")

        import sys
        mock_arch = MagicMock()
        mock_arch.get_pretrained_model.side_effect = RuntimeError("download failed")
        sys.modules["tiatoolbox.models.architecture"] = mock_arch

        with pytest.raises(RuntimeError, match="download failed"):
            eng.load_model()

        assert eng._loaded is False
        del sys.modules["tiatoolbox.models.architecture"]


# ═══════════════════════════════════════════════════════════════════
# HoVerNetEngine.infer_tile (full pipeline — mocked model)
# ═══════════════════════════════════════════════════════════════════
class TestInferTile:
    """Test the complete infer_tile pipeline with a mocked TIAToolbox model."""

    @pytest.fixture()
    def loaded_engine(self):
        """Create an engine with a mock model already loaded."""
        with patch("app.services.inference._select_device", return_value="cpu"):
            eng = HoVerNetEngine(device="cpu")

        mock_model = MagicMock()
        mock_ioconfig = MagicMock()
        mock_ioconfig.patch_input_shape = [256, 256]
        mock_ioconfig.patch_output_shape = [164, 164]

        eng._model = mock_model
        eng._ioconfig = mock_ioconfig
        eng._loaded = True
        return eng

    def test_small_tile_single_patch(self, loaded_engine):
        """A tile smaller than patch_output_shape produces 1 patch."""
        eng = loaded_engine
        tile = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)

        # Mock model.infer_batch to return 3 heads with correct shapes
        # Each head: (N, H_out, W_out, C) — but we only need per-patch slicing
        np_map = np.zeros((1, 164, 164, 2))
        hv_map = np.zeros((1, 164, 164, 2))
        tp_map = np.zeros((1, 164, 164, 6))
        eng._model.infer_batch.return_value = (np_map, hv_map, tp_map)

        # Mock postproc to return a small inst_dict with one nucleus
        inst_map = np.zeros((164, 164), dtype=np.int32)
        inst_dict = {
            1: {
                "centroid": [50.0, 60.0],
                "contour": [[40, 50], [60, 50], [60, 70], [40, 70]],
                "type": 1,
                "prob": 0.95,
            }
        }
        eng._model.postproc.return_value = (inst_map, inst_dict)

        result = eng.infer_tile(tile, offset_x=100, offset_y=200, mpp=0.25)

        assert isinstance(result, InferenceResult)
        assert result.count == 1
        nuc = result.nuclei[0]
        assert nuc.centroid_x == 150.0  # 50 + 100
        assert nuc.centroid_y == 260.0  # 60 + 200
        assert nuc.cell_type == 1

    def test_large_tile_multiple_batches(self, loaded_engine):
        """A tile large enough to produce multiple batches."""
        eng = loaded_engine
        # 500x500 tile with stride=164 → ceil(500/164)^2 = 16 patches → 2+ batches with batch_size=6
        tile = np.random.randint(0, 255, (500, 500, 3), dtype=np.uint8)

        # Mock: return empty inst_dict for all patches
        def fake_infer_batch(model, batch_tensor, device):
            n = batch_tensor.shape[0]
            return (
                np.zeros((n, 164, 164, 2)),
                np.zeros((n, 164, 164, 2)),
                np.zeros((n, 164, 164, 6)),
            )

        eng._model.infer_batch.side_effect = fake_infer_batch
        eng._model.postproc.return_value = (np.zeros((164, 164)), {})

        with patch("app.services.inference.settings") as mock_settings:
            mock_settings.batch_size = 4
            mock_settings.cell_type_map = {0: "Background", 1: "Neoplastic"}
            result = eng.infer_tile(tile, offset_x=0, offset_y=0, mpp=0.25)

        assert isinstance(result, InferenceResult)
        assert result.count == 0  # No nuclei detected

    def test_boundary_padding(self, loaded_engine):
        """Patches at tile boundary are zero-padded."""
        eng = loaded_engine
        # Tile that doesn't evenly divide into patch_output strides
        tile = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)

        def fake_infer_batch(model, batch_tensor, device):
            n = batch_tensor.shape[0]
            # Verify all patches are 256x256
            assert batch_tensor.shape[1] == 256
            assert batch_tensor.shape[2] == 256
            return (
                np.zeros((n, 164, 164, 2)),
                np.zeros((n, 164, 164, 2)),
                np.zeros((n, 164, 164, 6)),
            )

        eng._model.infer_batch.side_effect = fake_infer_batch
        eng._model.postproc.return_value = (np.zeros((164, 164)), {})

        result = eng.infer_tile(tile, offset_x=0, offset_y=0, mpp=0.25)
        assert isinstance(result, InferenceResult)

    def test_progress_callback(self, loaded_engine):
        """Progress callback should be called for each batch."""
        eng = loaded_engine
        tile = np.random.randint(0, 255, (164, 164, 3), dtype=np.uint8)

        eng._model.infer_batch.return_value = (
            np.zeros((1, 164, 164, 2)),
            np.zeros((1, 164, 164, 2)),
            np.zeros((1, 164, 164, 6)),
        )
        eng._model.postproc.return_value = (np.zeros((164, 164)), {})

        callback_calls = []

        def progress_fn(current, total, message):
            callback_calls.append((current, total, message))

        result = eng.infer_tile(tile, offset_x=0, offset_y=0, mpp=0.25, progress_callback=progress_fn)

        # Should be called at start (0, N) and then once per batch (1, N)
        assert len(callback_calls) >= 2
        assert callback_calls[0][0] == 0  # Initial call
        assert callback_calls[-1][0] == callback_calls[-1][1]  # Final call, current == total

    def test_no_progress_callback(self, loaded_engine):
        """Inference should work fine without a progress callback."""
        eng = loaded_engine
        tile = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)

        eng._model.infer_batch.return_value = (
            np.zeros((1, 164, 164, 2)),
            np.zeros((1, 164, 164, 2)),
            np.zeros((1, 164, 164, 6)),
        )
        eng._model.postproc.return_value = (np.zeros((164, 164)), {})

        result = eng.infer_tile(tile, offset_x=0, offset_y=0, mpp=0.25, progress_callback=None)
        assert isinstance(result, InferenceResult)

    def test_multiple_nuclei_across_patches(self, loaded_engine):
        """Multiple nuclei from different patches are merged correctly."""
        eng = loaded_engine
        tile = np.random.randint(0, 255, (164, 164, 3), dtype=np.uint8)

        eng._model.infer_batch.return_value = (
            np.zeros((1, 164, 164, 2)),
            np.zeros((1, 164, 164, 2)),
            np.zeros((1, 164, 164, 6)),
        )

        inst_dict = {
            1: {"centroid": [10.0, 10.0], "contour": [[5, 5], [15, 5], [15, 15]], "type": 1, "prob": 0.9},
            2: {"centroid": [80.0, 80.0], "contour": [[75, 75], [85, 75], [85, 85]], "type": 2, "prob": 0.8},
            3: {"centroid": [50.0, 50.0], "contour": [[45, 45], [55, 45], [55, 55]], "type": 0, "prob": 0.7},
        }
        eng._model.postproc.return_value = (np.zeros((164, 164)), inst_dict)

        result = eng.infer_tile(tile, offset_x=1000, offset_y=2000, mpp=0.5)
        assert result.count == 3
        # Verify offsets applied correctly
        for nuc in result.nuclei:
            assert nuc.centroid_x >= 1000
            assert nuc.centroid_y >= 2000
