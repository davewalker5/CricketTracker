"""Remove the obsolete team short-name field from existing databases."""

from typing import Any

from yoyo import step


def remove_short_name(connection: Any) -> None:
    """Drop the team short-name column when upgrading an existing database.

    Fresh databases already receive the revised initial schema, so this
    migration deliberately becomes a no-op when the column is absent.

    :param connection: Yoyo-managed SQLite connection.
    :return: None.
    """
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(teams)").fetchall()
    }
    if "short_name" in columns:
        connection.execute("ALTER TABLE teams DROP COLUMN short_name")


def restore_short_name(connection: Any) -> None:
    """Restore the optional column when rolling back this migration.

    :param connection: Yoyo-managed SQLite connection.
    :return: None.
    """
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(teams)").fetchall()
    }
    if "short_name" not in columns:
        connection.execute("ALTER TABLE teams ADD COLUMN short_name TEXT COLLATE NOCASE")


steps = [step(remove_short_name, restore_short_name)]
