"""Application settings from environment (.env supported via pydantic-settings)."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_port: int = Field(default=8383, ge=1, le=65535)
    app_public_host: str = "localhost"
    app_version: str = Field(default="1.0.0", min_length=1, max_length=64)

    config_path: str = ""
    database_path: str = ""

    library_tv_path: str = ""
    library_movies_path: str = ""

    tmdb_read_access_token: str = ""
    tmdb_api_key: str = ""
    tvdb_api_key: str = ""
    tvdb_pin: str = ""

    scan_interval_minutes: str = "360"

    sql_echo: bool = False

    @field_validator("sql_echo", mode="before")
    @classmethod
    def _parse_sql_echo(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def repo_root(self) -> Path:
        return Path(__file__).resolve().parent

    def resolved_database_path(self) -> str:
        explicit = self.database_path.strip()
        if explicit:
            return explicit
        cfg = self.config_path.strip()
        if cfg:
            return str(Path(cfg) / "open_media_tracker.db")
        return str(self.repo_root() / "data" / "open_media_tracker.db")

    def resolved_poster_dir(self) -> Path:
        if self.config_path.strip():
            return Path(self.config_path) / "cache" / "posters"
        return self.repo_root() / "data" / "cache" / "posters"

    def runtime_directories_to_create(self) -> list[Path]:
        """Writable dirs used by the app (database parent, thumbnails, logs)."""
        paths: list[Path] = [
            Path(self.resolved_database_path()).resolve().parent,
            self.resolved_poster_dir(),
        ]
        if self.config_path.strip():
            paths.append(Path(self.config_path) / "logs")
        else:
            paths.append(self.repo_root() / "data" / "logs")
        return paths


settings = AppSettings()


def validate_api_credentials(settings_obj: AppSettings, logger: logging.Logger) -> bool:
    """Log configuration errors. Returns True when TMDB and TVDB requirements are met."""
    ok = True
    if not settings_obj.tmdb_api_key.strip() and not settings_obj.tmdb_read_access_token.strip():
        logger.error(
            "[Open Media Tracker] Configuration error: Missing TMDB credentials — "
            "set TMDB_API_KEY or TMDB_READ_ACCESS_TOKEN in the environment.",
        )
        ok = False
    if not settings_obj.tvdb_api_key.strip():
        logger.error(
            "[Open Media Tracker] Configuration error: Missing TVDB_API_KEY in the environment.",
        )
        ok = False
    return ok
