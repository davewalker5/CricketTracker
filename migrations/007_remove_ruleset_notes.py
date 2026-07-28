"""Remove the obsolete notes field from competition rulesets."""

from typing import Any

from yoyo import step


def remove_ruleset_notes(connection: Any) -> None:
    """Drop ruleset notes when upgrading an existing database.

    :param connection: Yoyo-managed SQLite connection.
    :return: None.
    """
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(competition_rulesets)"
        ).fetchall()
    }
    if "notes" in columns:
        connection.execute("ALTER TABLE competition_rulesets DROP COLUMN notes")


def restore_ruleset_notes(connection: Any) -> None:
    """Restore the optional ruleset notes field when rolling back.

    :param connection: Yoyo-managed SQLite connection.
    :return: None.
    """
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(competition_rulesets)"
        ).fetchall()
    }
    if "notes" not in columns:
        connection.execute(
            "ALTER TABLE competition_rulesets ADD COLUMN notes TEXT"
        )


steps = [step(remove_ruleset_notes, restore_ruleset_notes)]
