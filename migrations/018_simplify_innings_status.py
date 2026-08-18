"""Collapse derived innings conclusions into a single completed status."""

from typing import Any

from yoyo import step


def simplify_innings_status(connection: Any) -> None:
    """Normalise existing statuses and narrow the database constraint."""
    connection.execute("PRAGMA defer_foreign_keys = ON")
    connection.execute(
        """
        UPDATE innings
        SET innings_status = 'completed', completed = 1
        WHERE innings_status IN (
            'all_out', 'target_reached', 'innings_limit_reached'
        )
        """
    )
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
            innings_status TEXT NOT NULL DEFAULT 'not_started'
                CHECK (innings_status IN (
                    'not_started', 'in_progress', 'completed', 'abandoned'
                )),
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
            runs, wickets, balls, extras, target, completed, innings_status
        )
        SELECT
            id, match_id, innings_number, batting_team_id, bowling_team_id,
            runs, wickets, balls, extras, target, completed, innings_status
        FROM innings
        """
    )
    connection.execute("DROP TABLE innings")
    connection.execute("ALTER TABLE innings_new RENAME TO innings")


def restore_detailed_innings_status_constraint(connection: Any) -> None:
    """Restore the former allowed values without reconstructing derived history."""
    connection.execute("PRAGMA defer_foreign_keys = ON")
    connection.execute(
        """
        CREATE TABLE innings_old (
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
            innings_status TEXT NOT NULL DEFAULT 'not_started'
                CHECK (innings_status IN (
                    'not_started', 'in_progress', 'completed', 'all_out',
                    'target_reached', 'innings_limit_reached', 'abandoned'
                )),
            CHECK (batting_team_id <> bowling_team_id),
            UNIQUE (match_id, innings_number),
            UNIQUE (match_id, batting_team_id)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO innings_old (
            id, match_id, innings_number, batting_team_id, bowling_team_id,
            runs, wickets, balls, extras, target, completed, innings_status
        )
        SELECT
            id, match_id, innings_number, batting_team_id, bowling_team_id,
            runs, wickets, balls, extras, target, completed, innings_status
        FROM innings
        """
    )
    connection.execute("DROP TABLE innings")
    connection.execute("ALTER TABLE innings_old RENAME TO innings")


steps = [step(simplify_innings_status, restore_detailed_innings_status_constraint)]
