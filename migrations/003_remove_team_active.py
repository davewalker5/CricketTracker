"""Remove the obsolete team active flag from existing databases."""

from typing import Any

from yoyo import step


def remove_active(connection: Any) -> None:
    """Drop the team active column when upgrading an existing database.

    Fresh databases already receive the revised initial schema, so this
    migration becomes a no-op when the column is absent.

    :param connection: Yoyo-managed SQLite connection.
    :return: None.
    """
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(teams)").fetchall()
    }
    if "active" in columns:
        connection.execute("ALTER TABLE teams DROP COLUMN active")


def restore_active(connection: Any) -> None:
    """Restore the active column when rolling back this migration.

    :param connection: Yoyo-managed SQLite connection.
    :return: None.
    """
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(teams)").fetchall()
    }
    if "active" not in columns:
        connection.execute(
            "ALTER TABLE teams ADD COLUMN active INTEGER NOT NULL DEFAULT 1 "
            "CHECK (active IN (0, 1))"
        )


steps = [step(remove_active, restore_active)]
