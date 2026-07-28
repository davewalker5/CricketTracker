"""Move season and ruleset onto competitions and remove season entities."""

from typing import Any

from yoyo import step


MATCH_COLUMNS = """
    id, match_date, start_time, venue_id, home_team_id, away_team_id,
    match_stage, match_status, toss_winner_team_id, toss_decision,
    winning_team_id, result_type, result_margin_value, result_margin_type, notes
"""

INNINGS_COLUMNS = """
    id, match_id, innings_number, batting_team_id, bowling_team_id, runs,
    wickets, balls, extras, target, completed, notes
"""


def _table_exists(connection: Any, table: str) -> bool:
    """Return whether a table exists.

    :param connection: Yoyo-managed SQLite connection.
    :param table: Table name to inspect.
    :return: ``True`` when the table exists.
    """
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def collapse_seasons(connection: Any) -> None:
    """Convert competition-season rows into self-contained competitions.

    Competition IDs adopt the former season IDs, which preserves the match
    mapping without losing historical season distinctions.

    :param connection: Yoyo-managed SQLite connection.
    :return: None.
    """
    if not _table_exists(connection, "competition_seasons"):
        return
    connection.execute(
        """
        CREATE TABLE competitions_new (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE CHECK (trim(name) <> ''),
            gender TEXT NOT NULL CHECK (gender IN ('Men', 'Women')),
            format TEXT NOT NULL DEFAULT 'The Hundred' CHECK (trim(format) <> ''),
            country_id INTEGER REFERENCES countries(id) ON DELETE RESTRICT,
            season TEXT NOT NULL CHECK (trim(season) <> ''),
            ruleset_id INTEGER NOT NULL REFERENCES competition_rulesets(id) ON DELETE RESTRICT,
            UNIQUE (name, season)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO competitions_new (
            id, name, gender, format, country_id, season, ruleset_id
        )
        SELECT s.id, c.name, c.gender, c.format, c.country_id, s.season, s.ruleset_id
        FROM competition_seasons s
        JOIN competitions c ON c.id = s.competition_id
        """
    )
    connection.execute(
        f"""
        CREATE TABLE matches_new (
            id INTEGER PRIMARY KEY,
            competition_id INTEGER NOT NULL REFERENCES competitions_new(id) ON DELETE RESTRICT,
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
            result_type TEXT,
            result_margin_value INTEGER,
            result_margin_type TEXT,
            notes TEXT,
            CHECK (home_team_id <> away_team_id),
            UNIQUE (competition_id, match_date, home_team_id, away_team_id)
        )
        """
    )
    connection.execute(
        f"""
        INSERT INTO matches_new (id, competition_id, {MATCH_COLUMNS.replace('id, ', '', 1)})
        SELECT id, competition_season_id, {MATCH_COLUMNS.replace('id, ', '', 1)}
        FROM matches
        """
    )
    connection.execute(
        """
        CREATE TABLE innings_new (
            id INTEGER PRIMARY KEY,
            match_id INTEGER NOT NULL REFERENCES matches_new(id) ON DELETE CASCADE,
            innings_number INTEGER NOT NULL CHECK (innings_number > 0),
            batting_team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            bowling_team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            runs INTEGER NOT NULL CHECK (runs >= 0),
            wickets INTEGER NOT NULL CHECK (wickets BETWEEN 0 AND 10),
            balls INTEGER NOT NULL CHECK (balls >= 0),
            extras INTEGER,
            target INTEGER,
            completed INTEGER NOT NULL DEFAULT 1 CHECK (completed IN (0, 1)),
            notes TEXT,
            CHECK (batting_team_id <> bowling_team_id),
            UNIQUE (match_id, innings_number),
            UNIQUE (match_id, batting_team_id)
        )
        """
    )
    connection.execute(
        f"INSERT INTO innings_new ({INNINGS_COLUMNS}) SELECT {INNINGS_COLUMNS} FROM innings"
    )
    connection.execute("DROP TABLE innings")
    connection.execute("DROP TABLE matches")
    if _table_exists(connection, "competition_season_teams"):
        connection.execute("DROP TABLE competition_season_teams")
    connection.execute("DROP TABLE competition_seasons")
    connection.execute("DROP TABLE competitions")
    connection.execute("ALTER TABLE competitions_new RENAME TO competitions")
    connection.execute("ALTER TABLE matches_new RENAME TO matches")
    connection.execute("ALTER TABLE innings_new RENAME TO innings")
    connection.execute(
        "CREATE INDEX matches_competition_date_idx ON matches(competition_id, match_date)"
    )
    connection.execute("CREATE INDEX innings_match_idx ON innings(match_id, innings_number)")
    connection.execute(
        "CREATE TABLE _competition_season_collapse_state (applied INTEGER NOT NULL)"
    )
    connection.execute(
        "INSERT INTO _competition_season_collapse_state (applied) VALUES (1)"
    )


def restore_seasons(connection: Any) -> None:
    """Restore the former one-season-per-competition representation.

    :param connection: Yoyo-managed SQLite connection.
    :return: None.
    """
    if not _table_exists(connection, "_competition_season_collapse_state"):
        return
    connection.execute(
        """
        CREATE TABLE competitions_old (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (trim(name) <> ''),
            short_name TEXT COLLATE NOCASE,
            gender TEXT NOT NULL CHECK (gender IN ('Men', 'Women')),
            format TEXT NOT NULL,
            country_id INTEGER REFERENCES countries(id) ON DELETE RESTRICT,
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
        )
        """
    )
    connection.execute(
        """
        INSERT INTO competitions_old (id, name, gender, format, country_id, active)
        SELECT id, name || ' ' || season, gender, format, country_id, 1
        FROM competitions
        """
    )
    connection.execute(
        """
        CREATE TABLE competition_seasons (
            id INTEGER PRIMARY KEY,
            competition_id INTEGER NOT NULL REFERENCES competitions_old(id) ON DELETE RESTRICT,
            season TEXT NOT NULL,
            ruleset_id INTEGER NOT NULL REFERENCES competition_rulesets(id) ON DELETE RESTRICT,
            start_date TEXT,
            end_date TEXT,
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            UNIQUE (competition_id, season)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO competition_seasons (id, competition_id, season, ruleset_id, active)
        SELECT id, id, season, ruleset_id, 1 FROM competitions
        """
    )
    connection.execute(
        f"""
        CREATE TABLE matches_old AS
        SELECT id, competition_id AS competition_season_id,
               {MATCH_COLUMNS.replace('id, ', '', 1)}
        FROM matches
        """
    )
    connection.execute(
        f"CREATE TABLE innings_old AS SELECT {INNINGS_COLUMNS} FROM innings"
    )
    connection.execute("DROP TABLE innings")
    connection.execute("DROP TABLE matches")
    connection.execute("DROP TABLE competitions")
    connection.execute("ALTER TABLE competitions_old RENAME TO competitions")
    connection.execute("ALTER TABLE matches_old RENAME TO matches")
    connection.execute("ALTER TABLE innings_old RENAME TO innings")
    connection.execute(
        """
        CREATE TABLE competition_season_teams (
            competition_season_id INTEGER NOT NULL
                REFERENCES competition_seasons(id) ON DELETE CASCADE,
            team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            PRIMARY KEY (competition_season_id, team_id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX matches_season_date_idx "
        "ON matches(competition_season_id, match_date)"
    )
    connection.execute("CREATE INDEX innings_match_idx ON innings(match_id, innings_number)")
    connection.execute("DROP TABLE _competition_season_collapse_state")


steps = [step(collapse_seasons, restore_seasons)]
