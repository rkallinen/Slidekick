"""
HoVerNet Inference Engine
==========================
Wraps TIAToolbox's HoVerNet (``hovernet_fast-pannuke``) for nuclear
instance segmentation and classification on PanNuke taxonomy.

Pipeline (single-tile / viewport):
    1. ``get_pretrained_model("hovernet_fast-pannuke")`` → ``(model, ioconfig)``.
    2. Pad input tile to ``ioconfig.patch_input_shape`` (256 × 256).
    3. ``model.infer_batch(model, tensor, device)`` → 3 heads (NP, HV, TP).
    4. ``model.postproc([np_map, hv_map, tp_map])`` → ``(inst_map, inst_dict)``.
    5. Translate local pixel coords → Level-0 slide coords.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from math import ceil
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import torch
from typing import Callable

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Progress tracking ──────────────────────────────────────────────
class ProgressTracker:
    """Thread-safe progress tracker for inference operations.

    Written by the inference thread (via ``run_in_executor``) and read
    by the SSE coroutine on the asyncio event loop thread.  A
    ``threading.Lock`` serializes access to prevent torn reads.
    """
    
    def __init__(self):
        import threading
        self._lock = threading.Lock()
        self.current = 0
        self.total = 0
        self.message = ""
    
    def update(self, current: int, total: int, message: str = ""):
        with self._lock:
            self.current = current
            self.total = total
            self.message = message
    
    def get_progress(self) -> dict[str, Any]:
        with self._lock:
            current = self.current
            total = self.total
            message = self.message
        return {
            "current": current,
            "total": total,
            "percentage": int((current / total * 100) if total > 0 else 0),
            "message": message,
        }


# ── Inference Result ──────────────────────────────────────────────
@dataclass
class DetectedNucleus:
    """A single detected nucleus."""

    # Centroid in Level-0 pixel coordinates
    centroid_x: float
    centroid_y: float
    # Contour vertices (N, 2) in Level-0 pixel coordinates
    contour: np.ndarray
    # Cell type (PanNuke: 0-Background … 5-Epithelial)
    cell_type: int
    cell_type_name: str
    # Softmax probability for the assigned class
    probability: float
    # Morphometrics (in μm)
    area_um2: float = 0.0
    perimeter_um: float = 0.0


@dataclass
class InferenceResult:
    """Collection of detected nuclei for a tile or viewport."""

    nuclei: list[DetectedNucleus] = field(default_factory=list)
    # The Level-0 bounding box that was processed
    tile_x: int = 0
    tile_y: int = 0
    tile_w: int = 0
    tile_h: int = 0

    @property
    def count(self) -> int:
        return len(self.nuclei)


# ── Device helpers ────────────────────────────────────────────────

def _select_device(requested: str | None = None) -> str:
    """Pick the best available device (MPS → CUDA → CPU)."""
    if requested:
        return requested
    # Respect BRONCHO_DEVICE from settings / .env
    cfg_device = settings.device
    if cfg_device:
        return cfg_device
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


# ── HoVerNet Engine ─────────────────────────────────────────────
class HoVerNetEngine:
    """
    Real HoVerNet inference engine backed by TIAToolbox 1.5+.

    Uses ``get_pretrained_model("hovernet_fast-pannuke")`` to obtain the
    ``HoVerNet(num_types=6, mode="fast")`` architecture with PanNuke
    pretrained weights.  Inference on individual tiles goes through
    ``model.infer_batch`` + ``model.postproc`` (no file I/O required).

    Usage
    -----
    >>> engine = HoVerNetEngine()
    >>> result = engine.infer_tile(rgb_array, offset_x=1024, offset_y=2048, mpp=0.25)
    >>> for nuc in result.nuclei:
    ...     print(nuc.centroid_x, nuc.centroid_y, nuc.cell_type_name)
    """

    # PanNuke class labels (matches tiatoolbox type_info output)
    CELL_TYPES = settings.cell_type_map

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
    ) -> None:
        self._model_name = model_name or settings.hovernet_model
        self.device = _select_device(device)
        self._model: Any = None
        self._ioconfig: Any = None
        self._loaded = False
        logger.info(
            "HoVerNetEngine created (model=%s, device=%s)",
            self._model_name,
            self.device,
        )

    # ── Model loading ─────────────────────────────────────────

    def load_model(self) -> None:
        """
        Load the HoVerNet model + IOConfig via TIAToolbox.

        ``get_pretrained_model`` downloads / caches PanNuke weights
        automatically on first call.
        """
        try:
            from tiatoolbox.models.architecture import get_pretrained_model

            logger.info(
                "Loading pretrained model '%s' …", self._model_name,
            )
            model, ioconfig = get_pretrained_model(
                pretrained_model=self._model_name,
            )
            model = model.to(self.device)
            model.eval()

            self._model = model
            self._ioconfig = ioconfig
            self._loaded = True

            logger.info(
                "Model loaded — input=%s  output=%s  device=%s",
                ioconfig.patch_input_shape,
                ioconfig.patch_output_shape,
                self.device,
            )
        except Exception:
            logger.exception("Failed to load HoVerNet model")
            raise

    def ensure_loaded(self) -> None:
        """Lazy-load on first inference call."""
        if not self._loaded:
            self.load_model()

    # ── Single-tile inference ─────────────────────────────────

    def infer_tile(
        self,
        tile_rgb: np.ndarray,
        offset_x: int = 0,
        offset_y: int = 0,
        mpp: float = 0.25,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> InferenceResult:
        """
    Run HoVerNet on a single RGB tile.

        Parameters
        ----------
        tile_rgb : np.ndarray
            Shape ``(H, W, 3)``, dtype ``uint8``, RGB colour space.
        offset_x, offset_y : int
            Top-left corner of this tile in Level-0 pixel coordinates.
        mpp : float
            Microns-per-pixel for morphometric calculations.
        progress_callback : callable, optional
            Callback function(current, total, message) for progress updates.

        Returns
        -------
        InferenceResult
            Detected nuclei with coordinates in Level-0 space.
        """
        self.ensure_loaded()
        h, w = tile_rgb.shape[:2]

        # ── TIAToolbox inference path ────────────────────────
        patch_in = list(self._ioconfig.patch_input_shape)   # [256, 256]
        patch_out = list(self._ioconfig.patch_output_shape)  # [164, 164]

        # Stride through the tile in patch_output_shape steps,
        # with context padding of (input-output)//2 on each side.
        pad = (patch_in[0] - patch_out[0]) // 2  # 46 px each side

        # Pad the tile so every output pixel is backed by full context
        padded = np.pad(
            tile_rgb,
            ((pad, pad), (pad, pad), (0, 0)),
            mode="reflect",
        )

        # Collect patches
        patches: list[np.ndarray] = []
        origins: list[tuple[int, int]] = []  # output-space origin of each patch

        stride_h, stride_w = patch_out
        for y0 in range(0, h, stride_h):
            for x0 in range(0, w, stride_w):
                # Extract patch_input_shape from the padded image
                py = y0  # already offset by pad in padded coords
                px = x0
                patch = padded[py : py + patch_in[0], px : px + patch_in[1]]

                # Handle right/bottom boundary — pad if needed
                if patch.shape[0] < patch_in[0] or patch.shape[1] < patch_in[1]:
                    canvas = np.zeros(
                        (patch_in[0], patch_in[1], 3), dtype=tile_rgb.dtype,
                    )
                    canvas[: patch.shape[0], : patch.shape[1]] = patch
                    patch = canvas

                patches.append(patch)
                origins.append((x0, y0))

        # Run through the model in batches
        all_nuclei: dict[int, dict[str, Any]] = {}
        global_id = 0
        batch_size = settings.batch_size

        total_batches = ceil(len(patches) / batch_size)
        
        # Report initial progress
        if progress_callback:
            progress_callback(0, total_batches, "Starting analysis...")
        
        # Iterate batches and optionally report progress via callback / logs.
        for b_idx, b_start in enumerate(range(0, len(patches), batch_size)):
                b_end = min(b_start + batch_size, len(patches))
                batch_np = np.stack(patches[b_start:b_end])  # (N, 256, 256, 3)
                batch_tensor = torch.from_numpy(batch_np)

                with torch.no_grad():
                    heads = self._model.infer_batch(
                        self._model, batch_tensor, device=self.device,
                    )
                # heads: (np_map, hv_map, tp_map) each (N, H_out, W_out, C)

                for idx in range(b_end - b_start):
                    single = [head[idx] for head in heads]
                    inst_map, inst_dict = self._model.postproc(single)
                    ox, oy = origins[b_start + idx]

                    for iid, data in inst_dict.items():
                        cx_local, cy_local = data["centroid"]
                        contour_local = np.array(data["contour"], dtype=np.float64)
                        # Shift from patch-output space to tile space
                        all_nuclei[global_id] = {
                            "centroid": [cx_local + ox, cy_local + oy],
                            "contour": (contour_local + np.array([ox, oy])).tolist(),
                            "type": int(data.get("type", 0)),
                            "prob": float(data.get("prob", 0.0)),
                        }
                        global_id += 1

                # Report progress: log and call callback if provided.
                logger.debug("Processed batch %d/%d", b_idx + 1, total_batches)
                if progress_callback:
                    progress_callback(b_idx + 1, total_batches, f"Processing batch {b_idx + 1}/{total_batches}")

        return self._parse_raw_output(
            all_nuclei, offset_x, offset_y, mpp, h, w,
        )

    # ── Batch convenience ─────────────────────────────────────

    def infer_batch(
        self,
        tiles: Sequence[np.ndarray],
        offsets: Sequence[tuple[int, int]],
        mpp: float = 0.25,
    ) -> list[InferenceResult]:
        """
        Run inference on multiple tiles sequentially.

        Parameters
        ----------
        tiles : sequence of np.ndarray
            Each ``(H, W, 3)`` uint8 RGB.
        offsets : sequence of ``(offset_x, offset_y)``
            L0 pixel offsets per tile.
        mpp : float

        Returns
        -------
        list[InferenceResult]
        """
        return [
            self.infer_tile(tile, ox, oy, mpp)
            for tile, (ox, oy) in zip(tiles, offsets)
        ]

    # ── Output parsing ────────────────────────────────────────

    def _parse_raw_output(
        self,
        raw: dict[int, dict[str, Any]],
        offset_x: int,
        offset_y: int,
        mpp: float,
        tile_h: int,
        tile_w: int,
    ) -> InferenceResult:
        """
        Parse the instance dict produced by ``HoVerNet.postproc``.

        Expected per-instance format::

            {
                inst_id: {
                    "centroid": [cx, cy],
                    "contour": [[x1,y1], …],
                    "type": int,
                    "prob": float,
                }
            }

        Coordinates in *raw* are tile-local; they are shifted by
        ``(offset_x, offset_y)`` to Level-0 slide coordinates.
        """
        nuclei: list[DetectedNucleus] = []
        mpp_sq = mpp ** 2

        for _inst_id, data in raw.items():
            cx_local, cy_local = data["centroid"]
            contour_local = np.array(data["contour"], dtype=np.float64)

            cx_global = cx_local + offset_x
            cy_global = cy_local + offset_y
            contour_global = contour_local + np.array(
                [offset_x, offset_y], dtype=np.float64,
            )

            cell_type = int(data.get("type", 0))
            cell_type_name = self.CELL_TYPES.get(cell_type, "Unknown")
            prob = float(data.get("prob", 0.0))

            area_px = self._polygon_area(contour_local)
            perimeter_px = self._polygon_perimeter(contour_local)
            area_um2 = area_px * mpp_sq
            perimeter_um = perimeter_px * mpp

            nuclei.append(
                DetectedNucleus(
                    centroid_x=cx_global,
                    centroid_y=cy_global,
                    contour=contour_global,
                    cell_type=cell_type,
                    cell_type_name=cell_type_name,
                    probability=prob,
                    area_um2=area_um2,
                    perimeter_um=perimeter_um,
                )
            )

        return InferenceResult(
            nuclei=nuclei,
            tile_x=offset_x,
            tile_y=offset_y,
            tile_w=tile_w,
            tile_h=tile_h,
        )

    # ── Geometry helpers ──────────────────────────────────────

    @staticmethod
    def _polygon_area(vertices: np.ndarray) -> float:
        """Shoelace formula for polygon area (px²)."""
        if len(vertices) < 3:
            return 0.0
        x = vertices[:, 0]
        y = vertices[:, 1]
        return 0.5 * abs(
            np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))
        )

    @staticmethod
    def _polygon_perimeter(vertices: np.ndarray) -> float:
        """Sum of edge lengths (px)."""
        if len(vertices) < 2:
            return 0.0
        diffs = np.diff(vertices, axis=0, append=vertices[:1])
        return float(np.sum(np.linalg.norm(diffs, axis=1)))


# ── Singleton engine ──────────────────────────────────────────────
_engine_instance: HoVerNetEngine | None = None


def get_inference_engine() -> HoVerNetEngine:
    """Return a singleton ``HoVerNetEngine``."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = HoVerNetEngine()
    return _engine_instance
