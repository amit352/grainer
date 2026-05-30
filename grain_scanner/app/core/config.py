from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_name: str = "Grain Scanner"
    app_version: str = "1.0.0"
    debug: bool = False

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./grain_scanner.db"

    # ── Paths ─────────────────────────────────────────────────────────────────
    upload_dir: Path = Path("data/uploads")
    output_dir: Path = Path("outputs")
    calibration_file: Path = Path("data/calibration.json")

    # ── Scanner defaults ─────────────────────────────────────────────────────
    default_dpi: int = 300

    # ── Vision pipeline knobs ─────────────────────────────────────────────────
    min_grain_area_px: int = 50
    max_grain_area_px: int = 5_000_000
    gaussian_blur_kernel: int = 5        # must be odd
    adaptive_block_size: int = 51        # must be odd
    adaptive_c: int = 10
    morph_kernel_size: int = 3
    watershed_min_distance: int = 20

    # ── API ───────────────────────────────────────────────────────────────────
    api_prefix: str = "/api/v1"
    max_upload_size_mb: int = 100
    allowed_origins: list[str] = ["http://localhost:8501", "http://localhost:3000"]

    # ── Frontend ──────────────────────────────────────────────────────────────
    backend_url: str = "http://localhost:8000"

    @field_validator("gaussian_blur_kernel", "adaptive_block_size", mode="before")
    @classmethod
    def must_be_odd(cls, v: int) -> int:
        v = int(v)
        return v if v % 2 == 1 else v + 1

    def ensure_dirs(self) -> None:
        """Create runtime directories if they don't exist."""
        for path in (self.upload_dir, self.output_dir, Path("logs")):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
