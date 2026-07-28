"""Application configuration and runtime path resolution."""

from __future__ import annotations

import os
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION_NAME = "cricket-tracker"
DEFAULT_READ_ONLY_DOMAINS = ("streamlit.app",)


def application_version() -> str:
    """Return the version used in application branding.

    :return: The source project or installed distribution version.
    """
    project_metadata = PROJECT_ROOT / "pyproject.toml"
    if project_metadata.is_file():
        with project_metadata.open("rb") as project_file:
            project = tomllib.load(project_file)
        return str(project["project"]["version"])
    try:
        return version(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return "0.1.0"


def project_root() -> Path:
    """Return the runtime root containing migrations and application data.

    :return: The configured root or the source project root.
    """
    configured = os.environ.get("CRICKET_TRACKER_ROOT")
    return Path(configured).expanduser() if configured else PROJECT_ROOT


def database_path() -> Path:
    """Resolve the SQLite database path using the documented precedence.

    :return: The environment override or Cricket Tracker fallback path.
    """
    configured = os.environ.get("CRICKET_TRACKER_DB")
    return (
        Path(configured).expanduser()
        if configured
        else project_root() / "data" / "crickettracker.db"
    )


def migrations_path() -> Path:
    """Return the directory containing Cricket Tracker migrations.

    :return: The migrations directory below the runtime root.
    """
    return project_root() / "migrations"


def read_only_domains() -> tuple[str, ...]:
    """Return normalised domains on which data changes are disabled.

    :return: Configured domain names without ports or leading dots.
    """
    configured = os.environ.get("CRICKET_TRACKER_READ_ONLY_DOMAINS")
    values = configured.split(",") if configured is not None else DEFAULT_READ_ONLY_DOMAINS
    return tuple(
        value.strip().lower().strip(".")
        for value in values
        if value.strip().strip(".")
    )


def is_read_only_domain(hostname: str | None) -> bool:
    """Return whether a host belongs to a configured read-only domain.

    :param hostname: Request hostname, optionally including a port.
    :return: ``True`` when changes should be disabled.
    """
    host = (hostname or "").split(":", 1)[0].strip().lower().rstrip(".")
    return any(host == domain or host.endswith(f".{domain}") for domain in read_only_domains())

