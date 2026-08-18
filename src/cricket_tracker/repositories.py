"""Database repositories and enriched Cricket Tracker read models."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any


class Repository:
    """Provide safe CRUD operations for one known table."""

    def __init__(self, connection: sqlite3.Connection, table: str, columns: Iterable[str]):
        """Initialise a repository.

        :param connection: Open connection shared by the current transaction.
        :param table: Trusted table name.
        :param columns: Trusted writable columns.
        :return: None.
        """
        self.connection = connection
        self.table = table
        self.columns = tuple(columns)

    def list_all(self) -> list[dict[str, Any]]:
        """Return all rows in a stable display order.

        :return: Rows represented as dictionaries.
        """
        order_column = "name" if "name" in self.columns else "id"
        rows = self.connection.execute(
            f"SELECT * FROM {self.table} ORDER BY {order_column} COLLATE NOCASE, id"
        ).fetchall()
        return [dict(row) for row in rows]

    def get(self, entity_id: int) -> dict[str, Any] | None:
        """Return one row by identifier.

        :param entity_id: Primary-key identifier.
        :return: The row dictionary, or ``None`` when absent.
        """
        row = self.connection.execute(
            f"SELECT * FROM {self.table} WHERE id = ?", (entity_id,)
        ).fetchone()
        return dict(row) if row else None

    def insert(self, values: Mapping[str, Any]) -> int:
        """Insert a row using allowed values.

        :param values: Column values for the new row.
        :return: The new primary-key identifier.
        """
        columns = [column for column in self.columns if column in values]
        placeholders = ", ".join("?" for _ in columns)
        cursor = self.connection.execute(
            f"INSERT INTO {self.table} ({', '.join(columns)}) VALUES ({placeholders})",
            [values[column] for column in columns],
        )
        return int(cursor.lastrowid)

    def update(self, entity_id: int, values: Mapping[str, Any]) -> None:
        """Update a row using allowed values.

        :param entity_id: Primary-key identifier.
        :param values: Replacement column values.
        :return: None.
        :raises LookupError: If the row does not exist.
        """
        columns = [column for column in self.columns if column in values]
        if not columns:
            return
        assignments = ", ".join(f"{column} = ?" for column in columns)
        cursor = self.connection.execute(
            f"UPDATE {self.table} SET {assignments} WHERE id = ?",
            [values[column] for column in columns] + [entity_id],
        )
        if cursor.rowcount == 0:
            raise LookupError(f"No {self.table.rstrip('s')} exists with ID {entity_id}.")

    def delete(self, entity_id: int) -> None:
        """Delete a row by identifier.

        :param entity_id: Primary-key identifier.
        :return: None.
        :raises LookupError: If the row does not exist.
        """
        cursor = self.connection.execute(
            f"DELETE FROM {self.table} WHERE id = ?", (entity_id,)
        )
        if cursor.rowcount == 0:
            raise LookupError(f"No {self.table.rstrip('s')} exists with ID {entity_id}.")


class CricketRepository:
    """Expose Cricket Tracker repositories over one transaction."""

    def __init__(self, connection: sqlite3.Connection):
        """Initialise all entity repositories.

        :param connection: Open SQLite connection.
        :return: None.
        """
        self.connection = connection
        self.match_formats = Repository(
            connection,
            "match_formats",
            (
                "code", "name", "innings_per_team", "limit_unit",
                "innings_limit", "balls_per_over", "draw_allowed",
                "tie_allowed", "revised_target_supported", "active",
            ),
        )
        self.countries = Repository(connection, "countries", ("name", "code"))
        self.venues = Repository(
            connection, "venues", ("name", "city", "country_id", "capacity")
        )
        self.teams = Repository(
            connection,
            "teams",
            ("name", "country_id", "gender", "home_venue_id"),
        )
        self.rulesets = Repository(
            connection,
            "competition_rulesets",
            (
                "name", "points_for_win", "points_for_tie", "points_for_no_result",
                "points_for_loss", "uses_net_run_rate", "include_knockout_matches_in_table",
                "table_sort_order", "balls_per_innings", "wickets_per_innings",
                "balls_per_rate_unit", "combine_gender_tables", "match_format_id",
                "points_for_abandonment", "has_standings", "ties_may_stand",
                "tie_break_winner_allowed", "revised_targets_allowed",
                "points_for_draw", "scheduled_days", "follow_on_allowed",
                "follow_on_lead", "declarations_allowed", "forfeitures_allowed",
            ),
        )
        self.competitions = Repository(
            connection,
            "competitions",
            ("name", "gender", "format", "country_id", "season", "ruleset_id"),
        )
        self.matches = Repository(
            connection,
            "matches",
            (
                "competition_id", "match_date", "start_time", "venue_id",
                "home_team_id", "away_team_id", "match_stage", "match_status",
                "toss_winner_team_id", "toss_decision", "winning_team_id", "result_type",
                "result_margin_value", "result_margin_type", "result_method",
                "result_source", "result_override_reason",
                "scheduled_balls", "revised_balls",
                "target_runs", "revised_target_runs",
                "scheduled_days", "follow_on_enforced", "effective_follow_on_lead",
            ),
        )
        self.innings = Repository(
            connection,
            "innings",
            (
                "match_id", "innings_number", "batting_team_id", "bowling_team_id",
                "runs", "wickets", "balls", "extras", "target", "completed",
                "innings_status",
            ),
        )

    def list_venues(self) -> list[dict[str, Any]]:
        """Return venues with their country names.

        :return: Enriched venue rows.
        """
        rows = self.connection.execute(
            """
            SELECT v.*, c.name AS country_name
            FROM venues v
            LEFT JOIN countries c ON c.id = v.country_id
            ORDER BY v.name COLLATE NOCASE, v.id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def list_teams(self) -> list[dict[str, Any]]:
        """Return teams with their country and home venue names.

        :return: Enriched team rows.
        """
        rows = self.connection.execute(
            """
            SELECT t.*, c.name AS country_name, v.name AS home_venue_name
            FROM teams t
            LEFT JOIN countries c ON c.id = t.country_id
            LEFT JOIN venues v ON v.id = t.home_venue_id
            ORDER BY t.name COLLATE NOCASE, t.id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def list_rulesets(self) -> list[dict[str, Any]]:
        """Return rulesets with their match-format labels.

        :return: Enriched competition-ruleset rows.
        """
        # Joining here keeps foreign-key identifiers out of presentation code.
        rows = self.connection.execute(
            """
            SELECT r.*, f.code AS match_format_code, f.name AS match_format_name
            FROM competition_rulesets r
            JOIN match_formats f ON f.id = r.match_format_id
            ORDER BY f.id, r.name COLLATE NOCASE, r.id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def list_competitions(self) -> list[dict[str, Any]]:
        """Return competitions with country and ruleset labels.

        :return: Enriched competition rows.
        """
        rows = self.connection.execute(
            """
            SELECT c.*, x.name AS country_name, r.name AS ruleset_name,
                   f.code AS match_format_code, f.name AS match_format_name,
                   f.innings_per_team, f.limit_unit, f.innings_limit,
                   f.balls_per_over, r.has_standings, r.uses_net_run_rate,
                   r.scheduled_days, r.follow_on_allowed, r.follow_on_lead,
                   r.declarations_allowed, r.forfeitures_allowed
            FROM competitions c
            LEFT JOIN countries x ON x.id = c.country_id
            JOIN competition_rulesets r ON r.id = c.ruleset_id
            JOIN match_formats f ON f.id = r.match_format_id
            ORDER BY c.season DESC, c.name COLLATE NOCASE
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def list_matches(self, competition_id: int | None = None) -> list[dict[str, Any]]:
        """Return matches with display-ready reference names.

        :param competition_id: Optional competition filter.
        :return: Enriched fixture/result rows.
        """
        where = "WHERE m.competition_id = ?" if competition_id is not None else ""
        parameters = (competition_id,) if competition_id is not None else ()
        rows = self.connection.execute(
            f"""
            SELECT m.*, c.name AS competition_name, c.season,
                   v.name AS venue_name, h.name AS home_team_name,
                   a.name AS away_team_name, w.name AS winning_team_name,
                   f.code AS match_format_code, f.name AS match_format_name,
                   f.limit_unit, f.innings_limit, f.balls_per_over,
                   f.innings_per_team, f.draw_allowed,
                   r.scheduled_days AS ruleset_scheduled_days,
                   r.follow_on_allowed, r.follow_on_lead,
                   r.declarations_allowed, r.forfeitures_allowed
            FROM matches m
            JOIN competitions c ON c.id = m.competition_id
            JOIN competition_rulesets r ON r.id = c.ruleset_id
            JOIN match_formats f ON f.id = r.match_format_id
            LEFT JOIN venues v ON v.id = m.venue_id
            JOIN teams h ON h.id = m.home_team_id
            JOIN teams a ON a.id = m.away_team_id
            LEFT JOIN teams w ON w.id = m.winning_team_id
            {where}
            ORDER BY m.match_date, COALESCE(m.start_time, ''), m.id
            """,
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def list_innings(self, match_id: int | None = None) -> list[dict[str, Any]]:
        """Return innings with batting and bowling team names.

        :param match_id: Optional match filter.
        :return: Enriched innings rows.
        """
        where = "WHERE i.match_id = ?" if match_id is not None else ""
        parameters = (match_id,) if match_id is not None else ()
        rows = self.connection.execute(
            f"""
            SELECT i.*, b.name AS batting_team_name, o.name AS bowling_team_name,
                   f.limit_unit, f.balls_per_over,
                   f.code AS match_format_code, f.innings_per_team
            FROM innings i
            JOIN matches m ON m.id = i.match_id
            JOIN competitions c ON c.id = m.competition_id
            JOIN competition_rulesets r ON r.id = c.ruleset_id
            JOIN match_formats f ON f.id = r.match_format_id
            LEFT JOIN teams b ON b.id = i.batting_team_id
            LEFT JOIN teams o ON o.id = i.bowling_team_id
            {where}
            ORDER BY i.match_id, i.innings_number
            """,
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]
