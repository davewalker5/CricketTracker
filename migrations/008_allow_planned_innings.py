"""Allow incomplete innings records to be loaded before a match starts."""

from typing import Any

from yoyo import step


def allow_planned_innings(connection: Any) -> None:
    """Make innings teams and score fields nullable.

    The table rebuild preserves innings identifiers and all existing data.

    :param connection: Yoyo-managed SQLite connection.
    :return: None.
    """
    columns = {
        row[1]: bool(row[3])
        for row in connection.execute("PRAGMA table_info(innings)").fetchall()
    }
    if not columns.get("batting_team_id", False):
        return

    # Defer reference checks while replacing the innings table in place.
    connection.execute("PRAGMA defer_foreign_keys = ON")
    connection.execute(
        """
        CREATE TABLE innings_new (
            id INTEGER PRIMARY KEY,
            match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
            innings_number INTEGER NOT NULL CHECK (innings_number > 0),
            batting_team_id INTEGER REFERENCES teams(id) ON DELETE RESTRICT,
            bowling_team_id INTEGER REFERENCES teams(id) ON DELETE RESTRICT,
            runs INTEGER CHECK (runs IS NULL OR runs >= 0),
            wickets INTEGER CHECK (wickets IS NULL OR wickets BETWEEN 0 AND 10),
            balls INTEGER CHECK (balls IS NULL OR balls >= 0),
            extras INTEGER CHECK (extras IS NULL OR extras >= 0),
            target INTEGER CHECK (target IS NULL OR target > 0),
            completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
            notes TEXT,
            CHECK (batting_team_id <> bowling_team_id),
            UNIQUE (match_id, innings_number),
            UNIQUE (match_id, batting_team_id)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO innings_new (
            id, match_id, innings_number, batting_team_id, bowling_team_id,
            runs, wickets, balls, extras, target, completed, notes
        )
        SELECT
            id, match_id, innings_number, batting_team_id, bowling_team_id,
            runs, wickets, balls, extras, target, completed, notes
        FROM innings
        """
    )
    connection.execute("DROP TABLE innings")
    connection.execute("ALTER TABLE innings_new RENAME TO innings")


def require_started_innings(connection: Any) -> None:
    """Restore mandatory teams and score fields when rolling back.

    :param connection: Yoyo-managed SQLite connection.
    :return: None.
    """
    # A rollback is unsafe while planned innings contain blank required fields.
    blank = connection.execute(
        """
        SELECT 1 FROM innings
        WHERE batting_team_id IS NULL OR bowling_team_id IS NULL
           OR runs IS NULL OR wickets IS NULL OR balls IS NULL
        LIMIT 1
        """
    ).fetchone()
    if blank:
        raise ValueError(
            "Cannot restore mandatory innings fields while planned innings exist."
        )

    connection.execute("PRAGMA defer_foreign_keys = ON")
    connection.execute(
        """
        CREATE TABLE innings_old (
            id INTEGER PRIMARY KEY,
            match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
            innings_number INTEGER NOT NULL CHECK (innings_number > 0),
            batting_team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            bowling_team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            runs INTEGER NOT NULL CHECK (runs >= 0),
            wickets INTEGER NOT NULL CHECK (wickets BETWEEN 0 AND 10),
            balls INTEGER NOT NULL CHECK (balls >= 0),
            extras INTEGER CHECK (extras IS NULL OR extras >= 0),
            target INTEGER CHECK (target IS NULL OR target > 0),
            completed INTEGER NOT NULL DEFAULT 1 CHECK (completed IN (0, 1)),
            notes TEXT,
            CHECK (batting_team_id <> bowling_team_id),
            UNIQUE (match_id, innings_number),
            UNIQUE (match_id, batting_team_id)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO innings_old
        SELECT * FROM innings
        """
    )
    connection.execute("DROP TABLE innings")
    connection.execute("ALTER TABLE innings_old RENAME TO innings")


steps = [step(allow_planned_innings, require_started_innings)]
