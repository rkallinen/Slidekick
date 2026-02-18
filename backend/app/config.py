"""
Slidekick — Configuration via pydantic-settings.

Environment variables override defaults.  The MPP (Microns-Per-Pixel) value is
the critical bridge between pixel coordinates and physical units.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import os
from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    env_path: ClassVar[str] = str(Path(__file__).resolve().parents[2] / ".env")
    model_config = SettingsConfigDict(
        env_file=env_path,
        env_file_encoding="utf-8",
        env_prefix="SLIDEKICK_",
        # Ignore unrelated environment variables (for example the
        # POSTGRES_* variables used by Docker) so loading the env_file
        # does not cause validation errors for unknown keys.
        extra="ignore",
    )

    # ── Application ────────────────────────────────────────────────
    app_name: str = "Slidekick"
    debug: bool = False

    # ── Database (PostGIS) ─────────────────────────────────────────
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "slidekick"
    db_password: str = "slidekick_secret"
    db_name: str = "slidekick"

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy connection string (asyncpg driver)."""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    # ── Slide Storage ──────────────────────────────────────────────
    slides_dir: Path = Path("slides")

    # ── HoVerNet ──────────────────────────────────────────────────
    # Model selection: "hovernet_fast-pannuke" for HoVerNet pretrained on PanNuke
    hovernet_model: str = "hovernet_fast-pannuke"
    # Torch device override (auto-detected when empty: mps → cuda → cpu).
    device: str = ""
    # Default tile size for HoVerNet inference (px).
    tile_size: int = 256
    # Batch size for GPU inference.
    batch_size: int = 8

    # If true, allow model weights to be loaded even when the loader
    # used an unsafe ``torch.load`` invocation (i.e. without
    # ``weights_only=True``).  Only set this if you explicitly trust the
    # author of the model / cached weight files.  Default: False.
    allow_untrusted_model_load: bool = False


    # ── WSI Defaults ───────────────────────────────────────────────
    # Microns-Per-Pixel (MPP) at Level 0.
    # 0.25 μm/px ≈ 40× objective; overridden per-slide from metadata.
    default_mpp: float = 0.25

    # ── CORS ───────────────────────────────────────────────────────
    # Allowed CORS origins.
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse the comma-separated CORS origins into a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # ── Cell Type Labels (CoNSeP / PanNuke compatible) ─────────────
    cell_type_map: dict[int, str] = {
        0: "Background",
        1: "Neoplastic",
        2: "Inflammatory",
        3: "Connective",
        4: "Dead",
        5: "Non-Neoplastic Epithelial",
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # Create Settings instance and support legacy env var name
    s = Settings()
    return s
