from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Every field that can change the output of a run is snapshotted into
    analysis_runs.config_snapshot, so old runs stay interpretable after the
    defaults move.
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="REPOSCOPE_", extra="ignore")

    database_url: str = "postgresql+psycopg://reposcope:reposcope@localhost:5432/reposcope"

    # --- Jev / Decisions API -------------------------------------------------
    # Set JEV_API_KEY in .env. Never commit it.
    jev_api_key: str = ""
    jev_base_url: str = "https://api.venice.ai/api/v1"
    jev_model: str = "jev-latest"

    # --- Ingestion -----------------------------------------------------------
    workdir: Path = Path("/tmp/reposcope")
    clone_timeout_s: int = 300
    max_repo_mb: int = 500
    # Files larger than this are recorded but never parsed or classified.
    max_file_bytes: int = 1_000_000
    # A file with more than this many lines gets a truncated FileState.
    max_file_lines: int = 20_000

    def snapshot(self) -> dict:
        """Config as it affects analysis output. Secrets excluded."""
        return {
            "jev_model": self.jev_model,
            "max_file_bytes": self.max_file_bytes,
            "max_file_lines": self.max_file_lines,
            "max_repo_mb": self.max_repo_mb,
        }


settings = Settings()
