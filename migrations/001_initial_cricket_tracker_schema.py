"""Create the complete Cricket Tracker v0.1 database schema."""

from yoyo import step


steps = [
    step(
        """
        CREATE TABLE countries (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (trim(name) <> ''),
            code TEXT UNIQUE COLLATE NOCASE CHECK (code IS NULL OR length(trim(code)) BETWEEN 2 AND 3)
        )
        """,
        "DROP TABLE countries",
    ),
    step(
        """
        CREATE TABLE venues (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE CHECK (trim(name) <> ''),
            city TEXT,
            country_id INTEGER REFERENCES countries(id) ON DELETE RESTRICT,
            capacity INTEGER CHECK (capacity IS NULL OR capacity >= 0),
            UNIQUE (name, city)
        )
        """,
        "DROP TABLE venues",
    ),
    step(
        """
        CREATE TABLE teams (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE CHECK (trim(name) <> ''),
            country_id INTEGER REFERENCES countries(id) ON DELETE RESTRICT,
            gender TEXT NOT NULL CHECK (gender IN ('Men', 'Women')),
            home_venue_id INTEGER REFERENCES venues(id) ON DELETE RESTRICT,
            UNIQUE (name, gender)
        )
        """,
        "DROP TABLE teams",
    ),
    step(
        """
        CREATE TABLE competition_rulesets (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (trim(name) <> ''),
            points_for_win INTEGER NOT NULL DEFAULT 2 CHECK (points_for_win >= 0),
            points_for_tie INTEGER NOT NULL DEFAULT 1 CHECK (points_for_tie >= 0),
            points_for_no_result INTEGER NOT NULL DEFAULT 1 CHECK (points_for_no_result >= 0),
            points_for_loss INTEGER NOT NULL DEFAULT 0 CHECK (points_for_loss >= 0),
            uses_net_run_rate INTEGER NOT NULL DEFAULT 1 CHECK (uses_net_run_rate IN (0, 1)),
            include_knockout_matches_in_table INTEGER NOT NULL DEFAULT 0
                CHECK (include_knockout_matches_in_table IN (0, 1)),
            table_sort_order TEXT NOT NULL DEFAULT 'points,net_run_rate,wins'
                CHECK (trim(table_sort_order) <> ''),
            balls_per_innings INTEGER NOT NULL DEFAULT 100 CHECK (balls_per_innings > 0),
            wickets_per_innings INTEGER NOT NULL DEFAULT 10 CHECK (wickets_per_innings > 0)
        )
        """,
        "DROP TABLE competition_rulesets",
    ),
    step(
        """
        CREATE TABLE competitions (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE CHECK (trim(name) <> ''),
            gender TEXT NOT NULL CHECK (gender IN ('Men', 'Women')),
            format TEXT NOT NULL DEFAULT 'The Hundred' CHECK (trim(format) <> ''),
            country_id INTEGER REFERENCES countries(id) ON DELETE RESTRICT,
            season TEXT NOT NULL CHECK (trim(season) <> ''),
            ruleset_id INTEGER NOT NULL REFERENCES competition_rulesets(id) ON DELETE RESTRICT,
            UNIQUE (name, season)
        )
        """,
        "DROP TABLE competitions",
    ),
    step(
        """
        CREATE TABLE matches (
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
                    'Scheduled', 'In Progress', 'Completed', 'Postponed',
                    'Abandoned', 'Cancelled', 'No Result'
                )),
            toss_winner_team_id INTEGER REFERENCES teams(id) ON DELETE RESTRICT,
            toss_decision TEXT CHECK (toss_decision IS NULL OR toss_decision IN ('Bat', 'Field')),
            winning_team_id INTEGER REFERENCES teams(id) ON DELETE RESTRICT,
            result_type TEXT CHECK (
                result_type IS NULL OR result_type IN (
                    'Runs', 'Wickets', 'Tie', 'No Result', 'Abandoned', 'Walkover'
                )
            ),
            result_margin_value INTEGER CHECK (
                result_margin_value IS NULL OR result_margin_value >= 0
            ),
            result_margin_type TEXT CHECK (
                result_margin_type IS NULL OR result_margin_type IN ('Runs', 'Wickets')
            ),
            notes TEXT,
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
                (result_type IN ('Runs', 'Wickets') AND result_margin_value IS NOT NULL
                    AND result_margin_type = result_type)
                OR
                (result_type IS NULL OR result_type NOT IN ('Runs', 'Wickets'))
            ),
            UNIQUE (competition_id, match_date, home_team_id, away_team_id)
        )
        """,
        "DROP TABLE matches",
    ),
    step(
        """
        CREATE TABLE innings (
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
        """,
        "DROP TABLE innings",
    ),
    step(
        """
        INSERT INTO competition_rulesets (
            name, points_for_win, points_for_tie, points_for_no_result,
            points_for_loss, uses_net_run_rate,
            include_knockout_matches_in_table, table_sort_order,
            balls_per_innings, wickets_per_innings
        ) VALUES (
            'The Hundred', 2, 1, 1, 0, 1, 0,
            'points,net_run_rate,wins', 100, 10
        )
        """,
        "DELETE FROM competition_rulesets WHERE name = 'The Hundred'",
    ),
    step(
        "CREATE INDEX matches_competition_date_idx ON matches(competition_id, match_date)",
        "DROP INDEX matches_competition_date_idx",
    ),
    step(
        "CREATE INDEX innings_match_idx ON innings(match_id, innings_number)",
        "DROP INDEX innings_match_idx",
    ),
]
