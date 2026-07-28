"""Use team name and gender together as the team's unique key."""

from typing import Any

from yoyo import step


def _team_table_sql(connection: Any) -> str:
    """Return the SQL used to create the teams table.

    :param connection: Yoyo-managed SQLite connection.
    :return: Normalised teams table SQL.
    """
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'teams'"
    ).fetchone()
    return str(row[0] if row else "").casefold().replace(" ", "")


def use_composite_team_key(connection: Any) -> None:
    """Replace the name-only team key with a name-and-gender key.

    The table rebuild preserves team identifiers, so existing match and innings
    references continue to point to the same records.

    :param connection: Yoyo-managed SQLite connection.
    :return: None.
    """
    if "unique(name,gender)" in _team_table_sql(connection):
        return

    # Defer foreign-key checks while the referenced teams table is replaced.
    connection.execute("PRAGMA defer_foreign_keys = ON")
    connection.execute(
        """
        CREATE TABLE teams_new (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE CHECK (trim(name) <> ''),
            country_id INTEGER REFERENCES countries(id) ON DELETE RESTRICT,
            gender TEXT NOT NULL CHECK (gender IN ('Men', 'Women')),
            home_venue_id INTEGER REFERENCES venues(id) ON DELETE RESTRICT,
            UNIQUE (name, gender)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO teams_new (id, name, country_id, gender, home_venue_id)
        SELECT id, name, country_id, gender, home_venue_id FROM teams
        """
    )
    connection.execute("DROP TABLE teams")
    connection.execute("ALTER TABLE teams_new RENAME TO teams")


def restore_name_only_team_key(connection: Any) -> None:
    """Restore the former name-only unique key when rolling back.

    :param connection: Yoyo-managed SQLite connection.
    :return: None.
    """
    if "nameTEXTNOTNULLUNIQUE".casefold() in _team_table_sql(connection):
        return

    # The copy deliberately lets SQLite reject an unsafe rollback containing
    # equal team names in different genders.
    connection.execute("PRAGMA defer_foreign_keys = ON")
    connection.execute(
        """
        CREATE TABLE teams_old (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (trim(name) <> ''),
            country_id INTEGER REFERENCES countries(id) ON DELETE RESTRICT,
            gender TEXT NOT NULL CHECK (gender IN ('Men', 'Women')),
            home_venue_id INTEGER REFERENCES venues(id) ON DELETE RESTRICT
        )
        """
    )
    connection.execute(
        """
        INSERT INTO teams_old (id, name, country_id, gender, home_venue_id)
        SELECT id, name, country_id, gender, home_venue_id FROM teams
        """
    )
    connection.execute("DROP TABLE teams")
    connection.execute("ALTER TABLE teams_old RENAME TO teams")


steps = [step(use_composite_team_key, restore_name_only_team_key)]
