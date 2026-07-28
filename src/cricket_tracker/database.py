"""SQLite connection and migration management."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from cricket_tracker.config import database_path, migrations_path


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with referential integrity enabled.

    :param path: Optional database path; configuration is used when omitted.
    :return: An open connection whose rows allow name-based access.
    :raises RuntimeError: If the database directory or connection cannot be created.
    """
    target = Path(path).expanduser() if path is not None else database_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(target)
    except (OSError, sqlite3.Error) as error:
        raise RuntimeError(f"Cannot open or create Cricket Tracker database at {target}.") from error
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def session(path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Yield a transaction that commits or rolls back automatically.

    :param path: Optional database path; configuration is used when omitted.
    :return: An iterator yielding one open SQLite connection.
    """
    connection = connect(path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def apply_migrations(path: Path | str | None = None) -> None:
    """Apply all pending Cricket Tracker migrations.

    :param path: Optional database path; configuration is used when omitted.
    :return: None.
    """
    from yoyo import get_backend, read_migrations

    target = Path(path).expanduser() if path is not None else database_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        backend = get_backend(f"sqlite:///{target.resolve()}")
        migrations = read_migrations(str(migrations_path()))
        with backend.lock():
            backend.apply_migrations(backend.to_apply(migrations))
    except (OSError, sqlite3.Error) as error:
        raise RuntimeError(f"Cannot migrate Cricket Tracker database at {target}.") from error

