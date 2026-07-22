import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _project_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str(PROJECT_ROOT / path)


def _sqlite_url(path: str) -> str:
    return f"sqlite:///{Path(path).as_posix()}"


def resolve_database_url(value: str | None) -> str:
    raw = value or "sqlite:///./cloud_expert_dev.sqlite"
    if raw == "sqlite:///:memory:":
        return raw
    if raw.startswith("sqlite:///"):
        sqlite_path = raw.removeprefix("sqlite:///")
        if sqlite_path.startswith("/") or (len(sqlite_path) >= 2 and sqlite_path[1] == ":"):
            return raw
        return _sqlite_url(_project_path(sqlite_path))
    return raw


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    database_url: str
    env: str
    raw_data_dir: str
    source_registry_dir: str
    http_timeout_seconds: int
    http_max_retries: int
    http_min_interval_seconds: float
    max_download_bytes: int
    max_concurrency: int
    enable_network_tests: bool
    allow_localhost_for_tests: bool


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=resolve_database_url(os.getenv("DATABASE_URL")),
        env=os.getenv("CLOUD_EXPERT_ENV", "development"),
        raw_data_dir=_project_path(os.getenv("CLOUD_EXPERT_RAW_DATA_DIR", "./data/raw")),
        source_registry_dir=_project_path(
            os.getenv("CLOUD_EXPERT_SOURCE_REGISTRY_DIR", "./data/source_registry")
        ),
        http_timeout_seconds=int(os.getenv("CLOUD_EXPERT_HTTP_TIMEOUT_SECONDS", "30")),
        http_max_retries=int(os.getenv("CLOUD_EXPERT_HTTP_MAX_RETRIES", "3")),
        http_min_interval_seconds=float(os.getenv("CLOUD_EXPERT_HTTP_MIN_INTERVAL_SECONDS", "2")),
        max_download_bytes=int(os.getenv("CLOUD_EXPERT_MAX_DOWNLOAD_BYTES", "10485760")),
        max_concurrency=int(os.getenv("CLOUD_EXPERT_MAX_CONCURRENCY", "1")),
        enable_network_tests=os.getenv("CLOUD_EXPERT_ENABLE_NETWORK_TESTS", "false").lower()
        == "true",
        allow_localhost_for_tests=os.getenv(
            "CLOUD_EXPERT_ALLOW_LOCALHOST_FOR_TESTS",
            "false",
        ).lower()
        == "true",
    )
