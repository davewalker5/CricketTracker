"""Represent postponed fixtures as scheduled matches."""

from typing import Any

from yoyo import step


MATCH_COLUMNS = """
    id, competition_id, match_date, start_time, venue_id,
    home_team_id, away_team_id, match_stage, match_status,
    toss_winner_team_id, toss_decision, winning_team_id, result_type,
    result_margin_value, result_margin_type, result_method, result_source,
    result_override_reason, scheduled_balls, revised_balls,
    target_runs, revised_target_runs
"""


def _rebuild_matches(connection: Any, include_postponed: bool) -> None:
    """Rebuild matches with the requested status constraint."""
    postponed_value = "'Postponed'," if include_postponed else ""
    connection.execute("PRAGMA defer_foreign_keys = ON")
    connection.execute(
        f"""
        CREATE TABLE matches_new (
            id INTEGER PRIMARY KEY,
            competition_id INTEGER NOT NULL
                REFERENCES competitions(id) ON DELETE RESTRICT,
            match_date TEXT NOT NULL CHECK (trim(match_date) <> ''),
            start_time TEXT,
            venue_id INTEGER REFERENCES venues(id) ON DELETE RESTRICT,
            home_team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            away_team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            match_stage TEXT NOT NULL DEFAULT 'League'
                CHECK (match_stage IN ('League', 'Eliminator', 'Semi-final', 'Final')),
            match_status TEXT NOT NULL DEFAULT 'Scheduled'
                CHECK (match_status IN (
                    'Scheduled', 'In Progress', 'Completed', {postponed_value}
                    'Abandoned', 'Cancelled', 'No Result'
                )),
            toss_winner_team_id INTEGER REFERENCES teams(id) ON DELETE RESTRICT,
            toss_decision TEXT
                CHECK (toss_decision IS NULL OR toss_decision IN ('Bat', 'Field')),
            winning_team_id INTEGER REFERENCES teams(id) ON DELETE RESTRICT,
            result_type TEXT CHECK (
                result_type IS NULL OR result_type IN (
                    'Runs', 'Wickets', 'Tie', 'No Result', 'Abandoned', 'Walkover'
                )
            ),
            result_margin_value INTEGER
                CHECK (result_margin_value IS NULL OR result_margin_value >= 0),
            result_margin_type TEXT CHECK (
                result_margin_type IS NULL
                OR result_margin_type IN ('Runs', 'Wickets')
            ),
            result_method TEXT,
            result_source TEXT CHECK (
                result_source IS NULL OR result_source IN ('Calculated', 'Manual')
            ),
            result_override_reason TEXT,
            scheduled_balls INTEGER
                CHECK (scheduled_balls IS NULL OR scheduled_balls > 0),
            revised_balls INTEGER
                CHECK (revised_balls IS NULL OR revised_balls > 0),
            target_runs INTEGER CHECK (target_runs IS NULL OR target_runs > 0),
            revised_target_runs INTEGER
                CHECK (revised_target_runs IS NULL OR revised_target_runs > 0),
            CHECK (home_team_id <> away_team_id),
            CHECK (
                toss_winner_team_id IS NULL
                OR toss_winner_team_id IN (home_team_id, away_team_id)
            ),
            CHECK (
                winning_team_id IS NULL
                OR winning_team_id IN (home_team_id, away_team_id)
            ),
            CHECK (
                (
                    result_type IN ('Runs', 'Wickets')
                    AND result_margin_value IS NOT NULL
                    AND result_margin_type = result_type
                )
                OR (result_type IS NULL OR result_type NOT IN ('Runs', 'Wickets'))
            ),
            UNIQUE (competition_id, match_date, home_team_id, away_team_id)
        )
        """
    )
    connection.execute(
        f"INSERT INTO matches_new ({MATCH_COLUMNS}) SELECT {MATCH_COLUMNS} FROM matches"
    )
    connection.execute("DROP TABLE matches")
    connection.execute("ALTER TABLE matches_new RENAME TO matches")
    connection.execute(
        "CREATE INDEX matches_competition_date_idx "
        "ON matches(competition_id, match_date)"
    )


def remove_postponed_status(connection: Any) -> None:
    """Convert postponed fixtures to scheduled and remove the old value."""
    connection.execute(
        "UPDATE matches SET match_status = 'Scheduled' WHERE match_status = 'Postponed'"
    )
    _rebuild_matches(connection, include_postponed=False)


def restore_postponed_status_constraint(connection: Any) -> None:
    """Restore Postponed as an allowed value without reconstructing history."""
    _rebuild_matches(connection, include_postponed=True)


steps = [step(remove_postponed_status, restore_postponed_status_constraint)]
