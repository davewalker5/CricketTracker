"""Add Test cricket, multi-innings matches, and draw-aware rules."""

from typing import Any

from yoyo import step


def apply_test_support(connection: Any) -> None:
    """Rebuild constrained tables and seed the Test format and ruleset."""
    connection.execute("PRAGMA defer_foreign_keys = ON")
    connection.execute(
        """
        CREATE TABLE match_formats_new (
            id INTEGER PRIMARY KEY,
            code TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (trim(code) <> ''),
            name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (trim(name) <> ''),
            innings_per_team INTEGER NOT NULL CHECK (innings_per_team > 0),
            limit_unit TEXT CHECK (limit_unit IS NULL OR limit_unit IN ('balls', 'overs')),
            innings_limit INTEGER CHECK (innings_limit IS NULL OR innings_limit > 0),
            balls_per_over INTEGER CHECK (balls_per_over IS NULL OR balls_per_over > 0),
            draw_allowed INTEGER NOT NULL DEFAULT 0 CHECK (draw_allowed IN (0, 1)),
            tie_allowed INTEGER NOT NULL DEFAULT 1 CHECK (tie_allowed IN (0, 1)),
            revised_target_supported INTEGER NOT NULL DEFAULT 1
                CHECK (revised_target_supported IN (0, 1)),
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            CHECK (
                (limit_unit = 'balls' AND innings_limit IS NOT NULL AND balls_per_over IS NULL)
                OR (limit_unit = 'overs' AND innings_limit IS NOT NULL AND balls_per_over IS NOT NULL)
                OR (limit_unit IS NULL AND innings_limit IS NULL AND balls_per_over IS NOT NULL)
            )
        )
        """
    )
    connection.execute(
        """
        INSERT INTO match_formats_new
        SELECT * FROM match_formats
        """
    )
    connection.execute(
        """
        INSERT INTO match_formats_new (
            id, code, name, innings_per_team, limit_unit, innings_limit,
            balls_per_over, draw_allowed, tie_allowed,
            revised_target_supported, active
        ) VALUES (4, 'TEST', 'Test', 2, NULL, NULL, 6, 1, 1, 0, 1)
        """
    )
    connection.execute("DROP TABLE match_formats")
    connection.execute("ALTER TABLE match_formats_new RENAME TO match_formats")

    for statement in (
        "ALTER TABLE competition_rulesets ADD COLUMN points_for_draw INTEGER NOT NULL DEFAULT 0 CHECK (points_for_draw >= 0)",
        "ALTER TABLE competition_rulesets ADD COLUMN scheduled_days INTEGER CHECK (scheduled_days IS NULL OR scheduled_days > 0)",
        "ALTER TABLE competition_rulesets ADD COLUMN follow_on_allowed INTEGER NOT NULL DEFAULT 0 CHECK (follow_on_allowed IN (0, 1))",
        "ALTER TABLE competition_rulesets ADD COLUMN follow_on_lead INTEGER CHECK (follow_on_lead IS NULL OR follow_on_lead > 0)",
        "ALTER TABLE competition_rulesets ADD COLUMN declarations_allowed INTEGER NOT NULL DEFAULT 0 CHECK (declarations_allowed IN (0, 1))",
        "ALTER TABLE competition_rulesets ADD COLUMN forfeitures_allowed INTEGER NOT NULL DEFAULT 0 CHECK (forfeitures_allowed IN (0, 1))",
    ):
        connection.execute(statement)

    connection.execute(
        """
        INSERT INTO competition_rulesets (
            name, points_for_win, points_for_tie, points_for_no_result,
            points_for_loss, uses_net_run_rate,
            include_knockout_matches_in_table, table_sort_order,
            balls_per_innings, wickets_per_innings, balls_per_rate_unit,
            combine_gender_tables, match_format_id, points_for_abandonment,
            has_standings, ties_may_stand, tie_break_winner_allowed,
            revised_targets_allowed, points_for_draw, scheduled_days,
            follow_on_allowed, follow_on_lead, declarations_allowed,
            forfeitures_allowed
        ) VALUES (
            'Test Match', 12, 6, 0, 0, 0, 0, 'points,wins,name',
            1, 10, 6, 0, 4, 0, 0, 1, 0, 0, 4, 5, 1, 200, 1, 1
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE matches_new (
            id INTEGER PRIMARY KEY,
            competition_id INTEGER NOT NULL REFERENCES competitions(id) ON DELETE RESTRICT,
            match_date TEXT NOT NULL CHECK (trim(match_date) <> ''),
            start_time TEXT,
            venue_id INTEGER REFERENCES venues(id) ON DELETE RESTRICT,
            home_team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            away_team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            match_stage TEXT NOT NULL DEFAULT 'League'
                CHECK (match_stage IN ('League', 'Eliminator', 'Semi-final', 'Final')),
            match_status TEXT NOT NULL DEFAULT 'Scheduled'
                CHECK (match_status IN (
                    'Scheduled', 'In Progress', 'Completed', 'Drawn',
                    'Abandoned', 'Cancelled', 'No Result'
                )),
            toss_winner_team_id INTEGER REFERENCES teams(id) ON DELETE RESTRICT,
            toss_decision TEXT CHECK (toss_decision IS NULL OR toss_decision IN ('Bat', 'Field')),
            winning_team_id INTEGER REFERENCES teams(id) ON DELETE RESTRICT,
            result_type TEXT CHECK (
                result_type IS NULL OR result_type IN (
                    'Runs', 'Wickets', 'Innings and Runs', 'Tie', 'Draw',
                    'No Result', 'Abandoned', 'Walkover'
                )
            ),
            result_margin_value INTEGER CHECK (result_margin_value IS NULL OR result_margin_value >= 0),
            result_margin_type TEXT CHECK (
                result_margin_type IS NULL OR result_margin_type IN ('Runs', 'Wickets')
            ),
            result_method TEXT,
            result_source TEXT CHECK (result_source IS NULL OR result_source IN ('Calculated', 'Manual')),
            result_override_reason TEXT,
            scheduled_balls INTEGER CHECK (scheduled_balls IS NULL OR scheduled_balls > 0),
            revised_balls INTEGER CHECK (revised_balls IS NULL OR revised_balls > 0),
            target_runs INTEGER CHECK (target_runs IS NULL OR target_runs > 0),
            revised_target_runs INTEGER CHECK (revised_target_runs IS NULL OR revised_target_runs > 0),
            scheduled_days INTEGER CHECK (scheduled_days IS NULL OR scheduled_days > 0),
            follow_on_enforced INTEGER NOT NULL DEFAULT 0 CHECK (follow_on_enforced IN (0, 1)),
            effective_follow_on_lead INTEGER CHECK (
                effective_follow_on_lead IS NULL OR effective_follow_on_lead > 0
            ),
            CHECK (home_team_id <> away_team_id),
            CHECK (toss_winner_team_id IS NULL OR toss_winner_team_id IN (home_team_id, away_team_id)),
            CHECK (winning_team_id IS NULL OR winning_team_id IN (home_team_id, away_team_id)),
            CHECK (
                (result_type IN ('Runs', 'Wickets', 'Innings and Runs')
                    AND result_margin_value IS NOT NULL)
                OR (result_type IS NULL OR result_type NOT IN ('Runs', 'Wickets', 'Innings and Runs'))
            ),
            UNIQUE (competition_id, match_date, home_team_id, away_team_id)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO matches_new (
            id, competition_id, match_date, start_time, venue_id,
            home_team_id, away_team_id, match_stage, match_status,
            toss_winner_team_id, toss_decision, winning_team_id, result_type,
            result_margin_value, result_margin_type, result_method,
            result_source, result_override_reason, scheduled_balls, revised_balls,
            target_runs, revised_target_runs
        )
        SELECT id, competition_id, match_date, start_time, venue_id,
            home_team_id, away_team_id, match_stage, match_status,
            toss_winner_team_id, toss_decision, winning_team_id, result_type,
            result_margin_value, result_margin_type, result_method,
            result_source, result_override_reason, scheduled_balls, revised_balls,
            target_runs, revised_target_runs
        FROM matches
        """
    )
    connection.execute("DROP TABLE matches")
    connection.execute("ALTER TABLE matches_new RENAME TO matches")
    connection.execute("CREATE INDEX matches_competition_date_idx ON matches(competition_id, match_date)")

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
            innings_status TEXT NOT NULL DEFAULT 'Not Started'
                CHECK (innings_status IN (
                    'Not Started', 'In Progress', 'Completed', 'All Out',
                    'Declared', 'Forfeited', 'Target Reached',
                    'Match Ended', 'Abandoned'
                )),
            CHECK (batting_team_id <> bowling_team_id),
            UNIQUE (match_id, innings_number),
            UNIQUE (match_id, batting_team_id, innings_number)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO innings_new
        SELECT * FROM innings
        """
    )
    connection.execute("DROP TABLE innings")
    connection.execute("ALTER TABLE innings_new RENAME TO innings")
    connection.execute("CREATE INDEX innings_match_idx ON innings(match_id, innings_number)")


def rollback_test_support(connection: Any) -> None:
    """Remove Test seed data when rolling back an otherwise unused migration."""
    connection.execute("DELETE FROM competition_rulesets WHERE name = 'Test Match'")
    connection.execute("DELETE FROM match_formats WHERE code = 'TEST'")


steps = [step(apply_test_support, rollback_test_support)]
