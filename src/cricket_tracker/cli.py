"""Command-line launcher for the Cricket Tracker application."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from cricket_tracker.database import apply_migrations


def streamlit_entrypoint() -> Path:
    """Return the Streamlit script installed with the application package.

    :return: Absolute path to the packaged Streamlit application module.
    """
    # Keep the entry point inside the package so wheel installations include it.
    return Path(__file__).resolve().with_name("app.py")


def main() -> int:
    """Migrate the database and launch Streamlit.

    :return: Streamlit's process exit status.
    """
    apply_migrations()
    entrypoint = streamlit_entrypoint()
    # Forward Streamlit server options supplied by Docker or a local caller.
    command = [sys.executable, "-m", "streamlit", "run", str(entrypoint), *sys.argv[1:]]
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
