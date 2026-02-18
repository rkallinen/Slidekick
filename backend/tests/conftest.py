"""
Shared fixtures for the Slidekick test suite.

This conftest provides:
- Async session mocking
- Test client (httpx.AsyncClient) with a mock DB override
- Reusable sample data factories
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Force asyncio mode for all async tests (avoids per-file markers)
# ---------------------------------------------------------------------------
pytest_plugins = []


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------
SAMPLE_SLIDE_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
SAMPLE_BOX_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def make_slide_row(
    *,
    id: uuid.UUID | None = None,
    filename: str = "test.svs",
    filepath: str = "/slides/test.svs",
    mpp: float = 0.25,
    width_px: int = 10000,
    height_px: int = 8000,
) -> MagicMock:
    """Return a mock that behaves like a Slide ORM object."""
    slide = MagicMock()
    slide.id = id or SAMPLE_SLIDE_ID
    slide.filename = filename
    slide.filepath = filepath
    slide.mpp = mpp
    slide.width_px = width_px
    slide.height_px = height_px
    slide.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    slide.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    slide.metadata_ = {}
    return slide


def make_box_row(
    *,
    id: uuid.UUID | None = None,
    slide_id: uuid.UUID | None = None,
    label: str = "Analysis 1",
    x_min: float = 0.0,
    y_min: float = 0.0,
    x_max: float = 1000.0,
    y_max: float = 1000.0,
    total_nuclei: int = 100,
    area_mm2: float = 0.0625,
    density_per_mm2: float = 1600.0,
    neoplastic_ratio: float = 0.3,
    cell_type_counts: dict | None = None,
) -> MagicMock:
    """Return a mock that behaves like an AnalysisBox ORM object."""
    box = MagicMock()
    box.id = id or SAMPLE_BOX_ID
    box.slide_id = slide_id or SAMPLE_SLIDE_ID
    box.label = label
    box.x_min = x_min
    box.y_min = y_min
    box.x_max = x_max
    box.y_max = y_max
    box.total_nuclei = total_nuclei
    box.area_mm2 = area_mm2
    box.density_per_mm2 = density_per_mm2
    box.neoplastic_ratio = neoplastic_ratio
    box.cell_type_counts = cell_type_counts or {
        "1": {"count": 30, "name": "Neoplastic"},
        "2": {"count": 70, "name": "Inflammatory"},
    }
    box.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    box.geom = "POLYGON((0 0, 1000 0, 1000 1000, 0 1000, 0 0))"
    return box
