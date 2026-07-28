"""Cricket league-table calculations driven by season rulesets."""

from __future__ import annotations

import csv
import io
import sqlite3
from dataclasses import asdict, dataclass
from typing import Any

from cricket_tracker.formats import legal_balls_for_limit


@dataclass
class Standing:
    """Hold one team's calculated league-table values."""

    team_id: int
    team: str
    played: int = 0
    won: int = 0
    lost: int = 0
    tied: int = 0
    no_result: int = 0
    points: int = 0
    net_run_rate: float | None = None
    runs_for: int = 0
    balls_faced: int = 0
    runs_against: int = 0
    balls_bowled: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a display-ready dictionary.

        :return: All public table fields.
        """
        return asdict(self)


def _competition_configuration(
    connection: sqlite3.Connection, competition_id: int
) -> dict[str, Any]:
    """Load a competition and its selected ruleset.

    :param connection: Open SQLite connection.
    :param competition_id: Competition identifier.
    :return: Combined competition and ruleset values.
    :raises LookupError: If the competition does not exist.
    """
    row = connection.execute(
        """
        SELECT c.*, r.points_for_win, r.points_for_tie, r.points_for_no_result,
               r.points_for_abandonment, r.points_for_loss,
               r.uses_net_run_rate, r.has_standings,
               r.include_knockout_matches_in_table, r.table_sort_order,
               r.balls_per_innings, r.wickets_per_innings,
               r.balls_per_rate_unit, r.combine_gender_tables,
               r.ties_may_stand, r.tie_break_winner_allowed,
               r.revised_targets_allowed, f.limit_unit, f.innings_limit,
               f.balls_per_over
        FROM competitions c
        JOIN competition_rulesets r ON r.id = c.ruleset_id
        JOIN match_formats f ON f.id = r.match_format_id
        WHERE c.id = ?
        """,
        (competition_id,),
    ).fetchone()
    if not row:
        raise LookupError(f"No competition exists with ID {competition_id}.")
    return dict(row)


def _competition_teams(
    connection: sqlite3.Connection, competition_id: int
) -> dict[int, Standing]:
    """Load fixture-derived teams for a competition.

    :param connection: Open SQLite connection.
    :param competition_id: Competition identifier.
    :return: Standings keyed by team identifier.
    """
    rows = connection.execute(
        """
        SELECT DISTINCT t.id, t.name
        FROM teams t
        WHERE t.id IN (
            SELECT home_team_id FROM matches WHERE competition_id = ?
            UNION
            SELECT away_team_id FROM matches WHERE competition_id = ?
        )
        ORDER BY t.name COLLATE NOCASE
        """,
        (competition_id, competition_id),
    ).fetchall()
    return {int(row["id"]): Standing(int(row["id"]), str(row["name"])) for row in rows}


def _credited_balls(
    innings: sqlite3.Row,
    ruleset: dict[str, Any],
    innings_allocation: int,
) -> int:
    """Return balls used for net-run-rate calculation.

    Cricket convention credits an all-out batting side with its full allocation.

    :param innings: Raw innings row.
    :param ruleset: Governing competition ruleset.
    :param innings_allocation: Applicable full innings allocation in legal balls.
    :return: Balls used in the rate denominator.
    """
    if int(innings["wickets"]) >= int(ruleset["wickets_per_innings"]):
        # All-out teams are credited with the match's allocation, not time actually used.
        return innings_allocation
    return int(innings["balls"])


def _innings_count_for_nrr(innings_rows: list[sqlite3.Row]) -> bool:
    """Check whether two innings contain complete NRR source data.

    :param innings_rows: Match innings ordered by innings number.
    :return: Whether the first two innings are safe to include in NRR.
    """
    if len(innings_rows) < 2:
        return False
    required_fields = (
        "batting_team_id", "bowling_team_id", "runs", "wickets", "balls",
    )
    # Abandoned fixtures may retain two blank planning rows that must not affect rates.
    return all(
        bool(innings["completed"])
        and all(innings[field] is not None for field in required_fields)
        for innings in innings_rows[:2]
    )


def _rank_standings(
    standings: dict[str | int, Standing],
    ruleset: dict[str, Any],
) -> list[dict[str, Any]]:
    """Calculate NRR and rank accumulated standing records.

    :param standings: Standing records keyed by team or franchise identity.
    :param ruleset: Rules governing rates and table ordering.
    :return: Ordered display-ready standing rows.
    """
    for row in standings.values():
        if (
            ruleset["uses_net_run_rate"]
            and row.balls_faced > 0
            and row.balls_bowled > 0
        ):
            # NRR is a rate per ruleset unit: five balls in The Hundred, six in most formats.
            scale = int(ruleset["balls_per_rate_unit"])
            scoring_rate = row.runs_for * scale / row.balls_faced
            conceding_rate = row.runs_against * scale / row.balls_bowled
            row.net_run_rate = round(scoring_rate - conceding_rate, 3)

    sort_fields = [
        field.strip()
        for field in str(ruleset["table_sort_order"]).split(",")
        if field.strip()
    ]

    def sort_key(row: Standing) -> tuple[Any, ...]:
        """Build an ascending key with descending numeric table fields.

        :param row: Standing being ordered.
        :return: Composite sort key.
        """
        values: list[Any] = []
        for field in sort_fields:
            if field == "name":
                values.append(row.team.casefold())
            elif field == "net_run_rate":
                values.append(
                    -(row.net_run_rate if row.net_run_rate is not None else float("-inf"))
                )
            else:
                # Rulesets use the supporter-facing "wins" label; the model stores "won".
                attribute = "won" if field == "wins" else field
                values.append(-getattr(row, attribute))
        values.append(row.team.casefold())
        return tuple(values)

    return [row.to_dict() for row in sorted(standings.values(), key=sort_key)]


def calculate_standings(
    connection: sqlite3.Connection, competition_id: int
) -> list[dict[str, Any]]:
    """Calculate a competition's league table.

    Scheduled/incomplete fixtures and, by default, knockout matches are excluded.
    Ties and no-results use their separately configured points values.

    :param connection: Open SQLite connection.
    :param competition_id: Competition identifier.
    :return: Ordered standings rows.
    """
    ruleset = _competition_configuration(connection, competition_id)
    if not bool(ruleset["has_standings"]):
        # Knockout-only competitions deliberately have no league table.
        return []
    standings = _competition_teams(connection, competition_id)
    stage_clause = (
        ""
        if ruleset["include_knockout_matches_in_table"]
        else "AND m.match_stage = 'League'"
    )
    matches = connection.execute(
        f"""
        SELECT m.*
        FROM matches m
        WHERE m.competition_id = ?
          AND (
              m.match_status IN ('Completed', 'No Result', 'Abandoned')
              OR m.result_type IN ('No Result', 'Abandoned')
          )
          AND m.result_type IS NOT NULL
          {stage_clause}
        ORDER BY m.match_date, m.id
        """,
        (competition_id,),
    ).fetchall()
    for match in matches:
        home = standings.get(int(match["home_team_id"]))
        away = standings.get(int(match["away_team_id"]))
        if home is None or away is None:
            continue
        home.played += 1
        away.played += 1
        result_type = match["result_type"]
        if (
            result_type == "Tie"
            and match["winning_team_id"] in (home.team_id, away.team_id)
        ):
            # A recorded tie-break winner receives the ordinary win/loss allocation.
            winner = home if match["winning_team_id"] == home.team_id else away
            loser = away if winner is home else home
            winner.won += 1
            loser.lost += 1
            winner.points += int(ruleset["points_for_win"])
            loser.points += int(ruleset["points_for_loss"])
        elif result_type == "Tie":
            home.tied += 1
            away.tied += 1
            home.points += int(ruleset["points_for_tie"])
            away.points += int(ruleset["points_for_tie"])
        elif result_type == "No Result":
            home.no_result += 1
            away.no_result += 1
            home.points += int(ruleset["points_for_no_result"])
            away.points += int(ruleset["points_for_no_result"])
        elif result_type == "Abandoned":
            home.no_result += 1
            away.no_result += 1
            home.points += int(ruleset["points_for_abandonment"])
            away.points += int(ruleset["points_for_abandonment"])
        elif match["winning_team_id"] in (home.team_id, away.team_id):
            winner = home if match["winning_team_id"] == home.team_id else away
            loser = away if winner is home else home
            winner.won += 1
            loser.lost += 1
            winner.points += int(ruleset["points_for_win"])
            loser.points += int(ruleset["points_for_loss"])

        innings_rows = connection.execute(
            "SELECT * FROM innings WHERE match_id = ? ORDER BY innings_number",
            (match["id"],),
        ).fetchall()
        ordinary_rate_match = (
            bool(ruleset["uses_net_run_rate"])
            and result_type not in {"No Result", "Abandoned"}
            and match["revised_balls"] is None
            and match["revised_target_runs"] is None
        )
        # Revised and exceptional matches are excluded until their NRR rules are known.
        if ordinary_rate_match and _innings_count_for_nrr(innings_rows):
            format_allocation = legal_balls_for_limit(
                int(ruleset["innings_limit"]),
                limit_unit=str(ruleset["limit_unit"]),
                balls_per_over=ruleset["balls_per_over"],
            )
            innings_allocation = int(
                match["scheduled_balls"] or format_allocation
            )
            for innings in innings_rows[:2]:
                batting = standings.get(int(innings["batting_team_id"]))
                bowling = standings.get(int(innings["bowling_team_id"]))
                if batting is None or bowling is None:
                    continue
                credited_balls = _credited_balls(
                    innings, ruleset, innings_allocation
                )
                batting.runs_for += int(innings["runs"])
                batting.balls_faced += credited_balls
                bowling.runs_against += int(innings["runs"])
                bowling.balls_bowled += credited_balls

    return _rank_standings(standings, ruleset)


def combined_competition_ids(
    connection: sqlite3.Connection,
    competition_id: int,
) -> list[int]:
    """Find same-season gender competitions eligible for one combined table.

    :param connection: Open SQLite connection.
    :param competition_id: Any competition in the desired combined group.
    :return: Ordered competition identifiers, or an empty list when unavailable.
    """
    competition = _competition_configuration(connection, competition_id)
    if not competition.get("combine_gender_tables"):
        return []
    rows = connection.execute(
        """
        SELECT id
        FROM competitions
        WHERE season = ?
          AND ruleset_id = ?
          AND format = ?
          AND country_id IS ?
        ORDER BY gender, id
        """,
        (
            competition["season"],
            competition["ruleset_id"],
            competition["format"],
            competition["country_id"],
        ),
    ).fetchall()
    # A combined table is meaningful only when at least two gender tables exist.
    identifiers = [int(row["id"]) for row in rows]
    return identifiers if len(identifiers) >= 2 else []


def calculate_combined_standings(
    connection: sqlite3.Connection,
    competition_id: int,
) -> list[dict[str, Any]]:
    """Combine same-franchise standings across paired gender competitions.

    :param connection: Open SQLite connection.
    :param competition_id: Any competition in the combined group.
    :return: Ordered combined franchise standings.
    :raises LookupError: If a combined table is not available.
    """
    competition_ids = combined_competition_ids(connection, competition_id)
    if not competition_ids:
        raise LookupError("This competition does not provide a combined gender table.")
    ruleset = _competition_configuration(connection, competition_id)
    combined: dict[str, Standing] = {}
    for source_competition_id in competition_ids:
        for source in calculate_standings(connection, source_competition_id):
            franchise_key = str(source["team"]).casefold()
            if franchise_key not in combined:
                # Team names are the shared franchise identity across gender records.
                combined[franchise_key] = Standing(
                    team_id=int(source["team_id"]),
                    team=str(source["team"]),
                )
            destination = combined[franchise_key]
            for field in (
                "played", "won", "lost", "tied", "no_result", "points",
                "runs_for", "balls_faced", "runs_against", "balls_bowled",
            ):
                setattr(
                    destination,
                    field,
                    int(getattr(destination, field)) + int(source[field]),
                )
    return _rank_standings(combined, ruleset)


def table_to_csv(table: list[dict[str, Any]]) -> str:
    """Serialise display columns from a standings table.

    :param table: Calculated standings rows.
    :return: UTF-8 compatible CSV text.
    """
    output = io.StringIO()
    fieldnames = [
        "team", "played", "won", "lost", "tied", "no_result", "points"
    ]
    if any(row.get("net_run_rate") is not None for row in table):
        # CSV output mirrors the UI and omits a rate the ruleset does not calculate.
        fieldnames.append("net_run_rate")
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in table:
        writer.writerow({field: row.get(field) for field in fieldnames})
    return output.getvalue()
