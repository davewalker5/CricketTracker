"""Shared limited-overs match analysis and report calculations."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from statistics import median
from typing import Any


TERMINAL_STATUSES = {"Completed", "No Result", "Abandoned"}
FINISHED_INNINGS_STATUSES = {
    "completed",
    "all_out",
    "target_reached",
    "innings_limit_reached",
}


def scoring_rate(runs: int | None, balls: int | None, format_code: str) -> float | None:
    """Calculate the format-aware scoring rate for an innings.

    :param runs: Runs scored in the innings.
    :param balls: Legal balls faced in the innings.
    :param format_code: Stable match-format code.
    :return: Runs per 100 balls for The Hundred, otherwise runs per over.
    """
    # Missing or zero ball counts cannot produce a meaningful rate.
    if runs is None or balls is None or balls <= 0:
        return None
    rate_unit = 100 if format_code == "HUNDRED" else 6
    return runs / balls * rate_unit


def rate_label(format_code: str) -> str:
    """Return the display label for a format's scoring rate.

    :param format_code: Stable match-format code.
    :return: Human-readable scoring-rate label.
    """
    # The Hundred convention differs from over-based limited-overs formats.
    return "Runs per 100 balls" if format_code == "HUNDRED" else "Runs per over"


def format_innings(innings: dict[str, Any] | None) -> str:
    """Format an innings using conventional cricket score notation.

    :param innings: Normalised innings row, or ``None``.
    :return: Score such as ``145/6``, or an em dash when unavailable.
    """
    # Never invent a wicket count when only runs are known.
    if not innings or innings.get("runs") is None:
        return "—"
    runs = str(innings["runs"])
    wickets = innings.get("wickets")
    return runs if wickets is None else f"{runs}/{wickets}"


def format_margin(match: dict[str, Any]) -> str:
    """Format a stored result margin without combining unlike result types.

    :param match: Normalised match row.
    :return: Display-ready result margin.
    """
    # Exceptional results have no numeric margin.
    result_type = match.get("result_type")
    margin = match.get("result_margin_value")
    if result_type not in {"Runs", "Wickets"} or margin is None:
        return str(result_type or "—")
    unit = result_type.lower()
    if margin == 1:
        unit = "run" if result_type == "Runs" else "wicket"
    return f"{margin} {unit}"


def load_analysis_matches(
    connection: sqlite3.Connection, competition_id: int
) -> list[dict[str, Any]]:
    """Load terminal matches and their innings for one competition-season row.

    :param connection: Open SQLite connection.
    :param competition_id: Competition-season identifier.
    :return: Normalised matches ordered chronologically.
    """
    # One joined query keeps data access out of individual report calculations.
    rows = connection.execute(
        """
        SELECT m.*, c.name AS competition_name, c.season,
               v.name AS venue_name, h.name AS home_team_name,
               a.name AS away_team_name, w.name AS winning_team_name,
               f.code AS match_format_code, f.name AS match_format_name,
               i.id AS innings_id, i.innings_number, i.batting_team_id,
               i.bowling_team_id, i.runs, i.wickets, i.balls,
               i.completed AS innings_completed, i.innings_status,
               b.name AS batting_team_name
        FROM matches m
        JOIN competitions c ON c.id = m.competition_id
        JOIN competition_rulesets r ON r.id = c.ruleset_id
        JOIN match_formats f ON f.id = r.match_format_id
        JOIN teams h ON h.id = m.home_team_id
        JOIN teams a ON a.id = m.away_team_id
        LEFT JOIN teams w ON w.id = m.winning_team_id
        LEFT JOIN venues v ON v.id = m.venue_id
        LEFT JOIN innings i ON i.match_id = m.id
        LEFT JOIN teams b ON b.id = i.batting_team_id
        WHERE m.competition_id = ?
          AND m.match_status IN ('Completed', 'No Result', 'Abandoned')
        ORDER BY m.match_date, COALESCE(m.start_time, ''), m.id, i.innings_number
        """,
        (competition_id,),
    ).fetchall()
    matches: dict[int, dict[str, Any]] = {}
    for source in rows:
        row = dict(source)
        match_id = int(row["id"])
        if match_id not in matches:
            # Copy match fields once and attach a report-friendly innings list.
            matches[match_id] = {
                key: value
                for key, value in row.items()
                if key not in {
                    "innings_id", "innings_number", "batting_team_id",
                    "bowling_team_id", "runs", "wickets", "balls",
                    "innings_completed", "innings_status", "batting_team_name",
                }
            }
            matches[match_id]["innings"] = []
        if row["innings_id"] is not None:
            matches[match_id]["innings"].append(
                {
                    "id": row["innings_id"],
                    "innings_number": row["innings_number"],
                    "batting_team_id": row["batting_team_id"],
                    "bowling_team_id": row["bowling_team_id"],
                    "batting_team_name": row["batting_team_name"],
                    "runs": row["runs"],
                    "wickets": row["wickets"],
                    "balls": row["balls"],
                    "completed": bool(row["innings_completed"]),
                    "innings_status": row["innings_status"],
                }
            )
    return list(matches.values())


def competition_teams(
    connection: sqlite3.Connection, competition_id: int
) -> list[dict[str, Any]]:
    """List teams appearing in fixtures for one competition-season.

    :param connection: Open SQLite connection.
    :param competition_id: Competition-season identifier.
    :return: Team identifiers and names in alphabetical order.
    """
    # A union includes both home and away participants without duplicates.
    rows = connection.execute(
        """
        SELECT t.id, t.name, t.gender
        FROM teams t
        WHERE t.id IN (
            SELECT home_team_id FROM matches WHERE competition_id = ?
            UNION
            SELECT away_team_id FROM matches WHERE competition_id = ?
        )
        ORDER BY t.name COLLATE NOCASE, t.gender, t.id
        """,
        (competition_id, competition_id),
    ).fetchall()
    return [dict(row) for row in rows]


def _ordered_innings(match: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return an unambiguous pair of innings in batting order.

    :param match: Normalised match row.
    :return: First and second innings, or ``None`` when order is unsuitable.
    """
    # Analysis never guesses order from home/away or the winning team.
    innings = sorted(match["innings"], key=lambda row: row["innings_number"])
    participants = {match["home_team_id"], match["away_team_id"]}
    if (
        len(innings) != 2
        or [row["innings_number"] for row in innings] != [1, 2]
        or {row["batting_team_id"] for row in innings} != participants
    ):
        return None
    return innings[0], innings[1]


def _outcome(match: dict[str, Any], team_id: int) -> str:
    """Describe a terminal result from one team's perspective.

    :param match: Normalised match row.
    :param team_id: Team whose perspective is required.
    :return: ``Won``, ``Lost``, ``Tied``, or ``No result``.
    """
    # Abandonments and no-results remain distinct from decisive matches.
    if match["match_status"] in {"No Result", "Abandoned"} or match.get(
        "result_type"
    ) in {"No Result", "Abandoned"}:
        return "No result"
    if match.get("result_type") == "Tie" and match.get("winning_team_id") is None:
        return "Tied"
    return "Won" if match.get("winning_team_id") == team_id else "Lost"


def _is_complete_innings(innings: dict[str, Any]) -> bool:
    """Determine whether an innings is complete enough for low-score analysis.

    :param innings: Normalised innings row.
    :return: Whether the innings is recorded as concluded.
    """
    # Successful chases and all-out innings are concluded even with legacy flags.
    return bool(innings.get("completed")) or innings.get(
        "innings_status"
    ) in FINISHED_INNINGS_STATUSES


def _average(values: list[int | float]) -> float | None:
    """Calculate a mean while preserving unavailable values.

    :param values: Numeric observations.
    :return: Arithmetic mean, or ``None`` for an empty sample.
    """
    # Reports show an unavailable marker rather than a misleading zero.
    return sum(values) / len(values) if values else None


def _win_percentage(outcomes: list[str]) -> float | None:
    """Calculate wins among decisive or tied matches.

    :param outcomes: Team-perspective result labels.
    :return: Win percentage excluding no-results, or ``None`` without a denominator.
    """
    # This follows the brief's recommended consistent denominator.
    eligible = [outcome for outcome in outcomes if outcome != "No result"]
    return 100 * eligible.count("Won") / len(eligible) if eligible else None


def _margin_extremes(
    matches: list[dict[str, Any]], outcome: str | None = None
) -> dict[str, int | None]:
    """Find largest and narrowest run and wicket margins.

    :param matches: Normalised matches, optionally carrying ``team_outcome``.
    :param outcome: Optional team-perspective outcome filter.
    :return: Separate run and wicket extrema.
    """
    # Run and wicket margins remain separate because their units are incomparable.
    filtered = [
        match
        for match in matches
        if outcome is None or match.get("team_outcome") == outcome
    ]
    result: dict[str, int | None] = {}
    for result_type in ("Runs", "Wickets"):
        margins = [
            int(match["result_margin_value"])
            for match in filtered
            if match.get("result_type") == result_type
            and match.get("result_margin_value") is not None
        ]
        key = result_type.lower()
        result[f"largest_{key}"] = max(margins) if margins else None
        result[f"narrowest_{key}"] = min(margins) if margins else None
    return result


def team_summary(matches: list[dict[str, Any]], team_id: int) -> dict[str, Any]:
    """Build a selected team's season summary and chronological history.

    :param matches: Terminal matches from one competition-season.
    :param team_id: Selected team identifier.
    :return: Report metrics, margin extrema, and match history.
    """
    # Result records can remain eligible even when optional innings facts are absent.
    relevant = [
        match
        for match in matches
        if team_id in {match["home_team_id"], match["away_team_id"]}
    ]
    team_innings: list[dict[str, Any]] = []
    opposition_innings: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    roles = defaultdict(int)
    outcomes: list[str] = []
    perspective_matches: list[dict[str, Any]] = []
    for match in relevant:
        outcome = _outcome(match, team_id)
        outcomes.append(outcome)
        perspective = dict(match, team_outcome=outcome)
        perspective_matches.append(perspective)
        ordered = _ordered_innings(match)
        own = next(
            (row for row in match["innings"] if row["batting_team_id"] == team_id),
            None,
        )
        opponent = next(
            (
                row
                for row in match["innings"]
                if row["batting_team_id"] not in {None, team_id}
            ),
            None,
        )
        if own and own.get("runs") is not None:
            team_innings.append(own)
        if opponent and opponent.get("runs") is not None:
            opposition_innings.append(opponent)
        role = "Unknown"
        if ordered:
            role = "Batted first" if ordered[0]["batting_team_id"] == team_id else "Chased"
            if outcome in {"Won", "Lost"}:
                roles[f"{outcome.lower()}_{'first' if role == 'Batted first' else 'chasing'}"] += 1
        opponent_id = (
            match["away_team_id"]
            if match["home_team_id"] == team_id
            else match["home_team_id"]
        )
        opponent_name = (
            match["away_team_name"]
            if match["home_team_id"] == team_id
            else match["home_team_name"]
        )
        history.append(
            {
                "Date": match["match_date"],
                "Opponent": opponent_name,
                "Venue": match.get("venue_name") or "—",
                "Batting position": role,
                "Team innings": format_innings(own),
                "Opposition innings": format_innings(opponent),
                "Result": outcome,
                "Margin": format_margin(match),
                "_opponent_id": opponent_id,
            }
        )
    team_rates = [
        rate
        for innings in team_innings
        if (rate := scoring_rate(
            innings.get("runs"), innings.get("balls"),
            relevant[0]["match_format_code"] if relevant else "",
        )) is not None
    ]
    opposition_rates = [
        rate
        for innings in opposition_innings
        if (rate := scoring_rate(
            innings.get("runs"), innings.get("balls"),
            relevant[0]["match_format_code"] if relevant else "",
        )) is not None
    ]
    complete_team = [row for row in team_innings if _is_complete_innings(row)]
    complete_opposition = [
        row for row in opposition_innings if _is_complete_innings(row)
    ]
    metrics = {
        "matches_played": len(relevant),
        "wins": outcomes.count("Won"),
        "losses": outcomes.count("Lost"),
        "ties": outcomes.count("Tied"),
        "no_results": outcomes.count("No result"),
        "win_percentage": _win_percentage(outcomes),
        "total_runs_scored": sum(row["runs"] for row in team_innings),
        "total_runs_conceded": sum(row["runs"] for row in opposition_innings),
        "average_runs_scored": _average([row["runs"] for row in team_innings]),
        "average_runs_conceded": _average([row["runs"] for row in opposition_innings]),
        "average_wickets_lost": _average(
            [row["wickets"] for row in team_innings if row.get("wickets") is not None]
        ),
        "average_wickets_taken": _average(
            [
                row["wickets"]
                for row in opposition_innings
                if row.get("wickets") is not None
            ]
        ),
        "highest_team_innings": max(
            (row["runs"] for row in team_innings), default=None
        ),
        "lowest_team_innings": min(
            (row["runs"] for row in complete_team), default=None
        ),
        "highest_opposition_innings": max(
            (row["runs"] for row in opposition_innings), default=None
        ),
        "lowest_opposition_innings": min(
            (row["runs"] for row in complete_opposition), default=None
        ),
        "average_scoring_rate": _average(team_rates),
        "average_opposition_scoring_rate": _average(opposition_rates),
        **roles,
    }
    win_margins = _margin_extremes(perspective_matches, "Won")
    defeat_margins = _margin_extremes(perspective_matches, "Lost")
    return {
        "metrics": metrics,
        "win_margins": win_margins,
        "defeat_margins": defeat_margins,
        "history": history,
        "format_code": relevant[0]["match_format_code"] if relevant else None,
    }


def batting_order_summary(
    matches: list[dict[str, Any]], team_id: int | None = None
) -> dict[str, Any]:
    """Compare results for teams batting first and chasing.

    :param matches: Terminal matches from one competition-season.
    :param team_id: Optional selected team identifier.
    :return: Competition metrics, optional team splits, and match detail.
    """
    # Only unambiguous innings pairs contribute to batting-order calculations.
    analysed: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    no_results = ties = 0
    for match in matches:
        if team_id is not None and team_id not in {
            match["home_team_id"], match["away_team_id"]
        }:
            continue
        outcome = _outcome(match, team_id or match["home_team_id"])
        if outcome == "No result":
            no_results += 1
        elif match.get("result_type") == "Tie" and match.get("winning_team_id") is None:
            ties += 1
        ordered = _ordered_innings(match)
        if ordered and all(row.get("runs") is not None for row in ordered):
            analysed.append((match, ordered[0], ordered[1]))
    first_wins = sum(
        match.get("winning_team_id") == first["batting_team_id"]
        for match, first, second in analysed
    )
    chase_wins = sum(
        match.get("winning_team_id") == second["batting_team_id"]
        for match, first, second in analysed
    )
    decided = first_wins + chase_wins + ties
    first_scores = [first["runs"] for match, first, second in analysed]
    successful_chases = [
        second["runs"]
        for match, first, second in analysed
        if match.get("winning_team_id") == second["batting_team_id"]
    ]
    defended = [
        first["runs"]
        for match, first, second in analysed
        if match.get("winning_team_id") == first["batting_team_id"]
    ]
    format_code = matches[0]["match_format_code"] if matches else None
    first_rates = [
        rate
        for match, first, second in analysed
        if (rate := scoring_rate(first["runs"], first.get("balls"), format_code or "")) is not None
    ]
    successful_rates = [
        rate
        for match, first, second in analysed
        if match.get("winning_team_id") == second["batting_team_id"]
        and (rate := scoring_rate(second["runs"], second.get("balls"), format_code or "")) is not None
    ]
    losing_rates = [
        rate
        for match, first, second in analysed
        if match.get("winning_team_id") == first["batting_team_id"]
        and (rate := scoring_rate(second["runs"], second.get("balls"), format_code or "")) is not None
    ]
    competition = {
        "completed_matches_analysed": len(analysed),
        "batting_first_wins": first_wins,
        "chasing_wins": chase_wins,
        "ties": ties,
        "no_results": no_results,
        "batting_first_win_percentage": 100 * first_wins / decided if decided else None,
        "chasing_win_percentage": 100 * chase_wins / decided if decided else None,
        "average_first_innings_score": _average(first_scores),
        "median_first_innings_score": median(first_scores) if first_scores else None,
        "highest_first_innings_score": max(first_scores, default=None),
        "lowest_completed_first_innings_score": min(
            (
                first["runs"]
                for match, first, second in analysed
                if _is_complete_innings(first)
            ),
            default=None,
        ),
        "highest_successful_chase": max(successful_chases, default=None),
        "lowest_successfully_defended_total": min(defended, default=None),
        "average_first_innings_rate": _average(first_rates),
        "average_successful_chase_rate": _average(successful_rates),
        "average_losing_chase_rate": _average(losing_rates),
    }
    detail = [
        {
            "Date": match["match_date"],
            "Team batting first": first["batting_team_name"],
            "First innings": format_innings(first),
            "Chasing team": second["batting_team_name"],
            "Chasing innings": format_innings(second),
            "Outcome": match.get("winning_team_name")
            or ("Tie" if match.get("result_type") == "Tie" else "No result"),
            "Method": match.get("result_method") or "Standard",
            "Margin": format_margin(match),
        }
        for match, first, second in analysed
    ]
    team = _team_order_metrics(analysed, team_id) if team_id is not None else None
    return {
        "competition": competition,
        "team": team,
        "detail": detail,
        "format_code": format_code,
    }


def _team_order_metrics(
    analysed: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]],
    team_id: int,
) -> dict[str, dict[str, Any]]:
    """Build batting-first and chasing metrics for one team.

    :param analysed: Matches paired with ordered innings.
    :param team_id: Selected team identifier.
    :return: Separate batting-first and chasing metric dictionaries.
    """
    # Build the two role samples once so every metric uses identical eligibility.
    samples: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {
        "batting_first": [],
        "chasing": [],
    }
    for match, first, second in analysed:
        role = "batting_first" if first["batting_team_id"] == team_id else "chasing"
        own = first if role == "batting_first" else second
        samples[role].append((match, own))
    result: dict[str, dict[str, Any]] = {}
    for role, rows in samples.items():
        outcomes = [_outcome(match, team_id) for match, own in rows]
        scores = [own["runs"] for match, own in rows]
        wins = [match for match, own in rows if _outcome(match, team_id) == "Won"]
        margin_type = "Runs" if role == "batting_first" else "Wickets"
        margins = [
            match["result_margin_value"]
            for match in wins
            if match.get("result_type") == margin_type
            and match.get("result_margin_value") is not None
        ]
        successful_scores = [
            own["runs"]
            for match, own in rows
            if _outcome(match, team_id) == "Won"
        ]
        result[role] = {
            "matches": len(rows),
            "wins": outcomes.count("Won"),
            "losses": outcomes.count("Lost"),
            "ties": outcomes.count("Tied"),
            "win_percentage": _win_percentage(outcomes),
            "average_score": _average(scores),
            "highest_score": max(scores, default=None),
            "lowest_completed_score": min(
                (
                    own["runs"]
                    for match, own in rows
                    if _is_complete_innings(own)
                ),
                default=None,
            ),
            "lowest_successful_score": min(successful_scores, default=None),
            "largest_margin": max(margins, default=None),
            "narrowest_margin": min(margins, default=None),
        }
    return result


def head_to_head(
    matches: list[dict[str, Any]], first_team_id: int, second_team_id: int
) -> dict[str, Any]:
    """Compare two teams' meetings within one competition-season.

    :param matches: Terminal matches from one competition-season.
    :param first_team_id: First selected team identifier.
    :param second_team_id: Distinct second selected team identifier.
    :return: Team summaries, notable matches, and chronological history.
    :raises ValueError: If both selected identifiers are the same.
    """
    # Prevent a nonsensical self-comparison in both service and presentation layers.
    if first_team_id == second_team_id:
        raise ValueError("Head-to-head analysis requires two distinct teams.")
    meetings = [
        match
        for match in matches
        if {match["home_team_id"], match["away_team_id"]}
        == {first_team_id, second_team_id}
    ]
    first = team_summary(meetings, first_team_id)
    second = team_summary(meetings, second_team_id)
    ordered = [
        (match, pair[0], pair[1])
        for match in meetings
        if (pair := _ordered_innings(match)) is not None
        and pair[0].get("runs") is not None
        and pair[1].get("runs") is not None
    ]
    successful_chases = [
        second_innings["runs"]
        for match, first_innings, second_innings in ordered
        if match.get("winning_team_id") == second_innings["batting_team_id"]
    ]
    defended = [
        first_innings["runs"]
        for match, first_innings, second_innings in ordered
        if match.get("winning_team_id") == first_innings["batting_team_id"]
    ]
    aggregates = [
        (first_innings["runs"] + second_innings["runs"], match)
        for match, first_innings, second_innings in ordered
        if _is_complete_innings(first_innings) and _is_complete_innings(second_innings)
    ]
    margins = _margin_extremes(meetings)
    history = [
        {
            "Date": match["match_date"],
            "Venue": match.get("venue_name") or "—",
            "First innings": (
                f"{first_innings['batting_team_name']} "
                f"{format_innings(first_innings)}"
            ),
            "Second innings": (
                f"{second_innings['batting_team_name']} "
                f"{format_innings(second_innings)}"
            ),
            "Winner": match.get("winning_team_name") or "—",
            "Result": match.get("result_type") or "—",
            "Margin": format_margin(match),
        }
        for match, first_innings, second_innings in ordered
    ]
    return {
        "matches_played": len(meetings),
        "first_team": first,
        "second_team": second,
        "ties": first["metrics"]["ties"],
        "no_results": first["metrics"]["no_results"],
        "notable": {
            **margins,
            "highest_successful_chase": max(successful_chases, default=None),
            "lowest_successfully_defended_total": min(defended, default=None),
            "highest_aggregate": max((item[0] for item in aggregates), default=None),
            "lowest_aggregate": min((item[0] for item in aggregates), default=None),
        },
        "history": history,
        "format_code": meetings[0]["match_format_code"] if meetings else None,
    }
