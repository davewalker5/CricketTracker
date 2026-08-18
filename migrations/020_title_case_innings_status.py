"""Use user-facing title case for innings status values."""

from typing import Any

from yoyo import step


def _rebuild_innings(connection: Any, title_case: bool) -> None:
    """Rebuild innings with either title-case or legacy status values."""
    if title_case:
        default = "Not Started"
        statuses = "'Not Started', 'In Progress', 'Completed', 'Abandoned'"
    else:
        default = "not_started"
        statuses = "'not_started', 'in_progress', 'completed', 'abandoned'"
    connection.execute("PRAGMA defer_foreign_keys = ON")
    connection.execute(
        f"""
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
            innings_status TEXT NOT NULL DEFAULT '{default}'
                CHECK (innings_status IN ({statuses})),
            CHECK (batting_team_id <> bowling_team_id),
            UNIQUE (match_id, innings_number),
            UNIQUE (match_id, batting_team_id)
        )
        """
    )
    status_expression = (
        """CASE innings_status
            WHEN 'not_started' THEN 'Not Started'
            WHEN 'in_progress' THEN 'In Progress'
            WHEN 'completed' THEN 'Completed'
            WHEN 'abandoned' THEN 'Abandoned'
        END"""
        if title_case
        else """CASE innings_status
            WHEN 'Not Started' THEN 'not_started'
            WHEN 'In Progress' THEN 'in_progress'
            WHEN 'Completed' THEN 'completed'
            WHEN 'Abandoned' THEN 'abandoned'
        END"""
    )
    connection.execute(
        f"""
        INSERT INTO innings_new (
            id, match_id, innings_number, batting_team_id, bowling_team_id,
            runs, wickets, balls, extras, target, completed, innings_status
        )
        SELECT
            id, match_id, innings_number, batting_team_id, bowling_team_id,
            runs, wickets, balls, extras, target, completed, {status_expression}
        FROM innings
        """
    )
    connection.execute("DROP TABLE innings")
    connection.execute("ALTER TABLE innings_new RENAME TO innings")


def title_case_innings_status(connection: Any) -> None:
    """Convert existing statuses to their user-facing labels."""
    _rebuild_innings(connection, title_case=True)


def restore_lowercase_innings_status(connection: Any) -> None:
    """Restore legacy machine-style status values."""
    _rebuild_innings(connection, title_case=False)


steps = [step(title_case_innings_status, restore_lowercase_innings_status)]
