"""Remove notes from venues, teams, and competitions."""

from typing import Any

from yoyo import step


TABLES = ("venues", "teams", "competitions")


def remove_notes(connection: Any) -> None:
    """Drop notes from the three simplified reference entities.

    Fresh databases already receive the revised initial schema, so each table
    operation becomes a no-op when its notes column is absent.

    :param connection: Yoyo-managed SQLite connection.
    :return: None.
    """
    for table in TABLES:
        columns = {
            row[1]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if "notes" in columns:
            connection.execute(f"ALTER TABLE {table} DROP COLUMN notes")


def restore_notes(connection: Any) -> None:
    """Restore optional notes columns when rolling back the migration.

    :param connection: Yoyo-managed SQLite connection.
    :return: None.
    """
    for table in TABLES:
        columns = {
            row[1]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if "notes" not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN notes TEXT")


steps = [step(remove_notes, restore_notes)]
