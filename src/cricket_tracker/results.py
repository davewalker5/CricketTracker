"""Structured result calculation for supported cricket formats."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CalculatedResult:
    """Represent a result derived from match and innings facts."""

    status: str
    winner_team_id: int | None
    result_type: str
    margin: int | None = None
    method: str = "Standard"

    def as_match_fields(self) -> dict[str, Any]:
        """Convert the result into fields stored on a match row.

        :return: Calculated match result and provenance fields.
        """
        # Margin type follows the result type only for numeric victories.
        margin_type = (
            "Runs" if self.result_type == "Innings and Runs" else
            self.result_type if self.result_type in {"Runs", "Wickets"} else None
        )
        return {
            "winning_team_id": self.winner_team_id,
            "result_type": self.result_type,
            "result_margin_value": self.margin,
            "result_margin_type": margin_type,
            "result_method": self.method,
            "result_source": "Calculated",
            "result_override_reason": None,
        }


def calculate_limited_overs_result(
    *,
    match: dict[str, Any],
    innings: list[dict[str, Any]],
    wickets_per_innings: int,
    effective_balls: int,
) -> CalculatedResult | None:
    """Calculate a structured result for one-innings limited-overs cricket.

    :param match: Match fields including status and any authoritative targets.
    :param innings: Innings rows ordered by innings number.
    :param wickets_per_innings: Maximum wickets available to the chasing team.
    :param effective_balls: Effective legal-ball allocation after any reduction.
    :return: A calculated result, or ``None`` when facts are insufficient.
    """
    status = str(match["match_status"])
    if status in {"No Result", "Abandoned"}:
        # Exceptional terminal statuses do not require innings summaries.
        return CalculatedResult(
            status=status,
            winner_team_id=None,
            result_type=status,
        )
    if status != "Completed":
        return None
    if len(innings) != 2 or [
        row["innings_number"] for row in innings
    ] != [1, 2]:
        return None

    first, second = innings
    participants = {match["home_team_id"], match["away_team_id"]}
    if (
        {first["batting_team_id"], second["batting_team_id"]} != participants
        or not bool(first["completed"])
        or first["runs"] is None
        or second["runs"] is None
        or second["wickets"] is None
        or second["balls"] is None
    ):
        return None

    # A revised target is authoritative; the innings target preserves legacy imports.
    target = int(
        match.get("revised_target_runs")
        or second.get("target")
        or match.get("target_runs")
        or (int(first["runs"]) + 1)
    )
    method = (
        str(match.get("result_method") or "Standard")
        if match.get("revised_target_runs") is not None
        else "Standard"
    )
    target_reached = int(second["runs"]) >= target
    second_concluded = (
        target_reached
        or bool(second["completed"])
        or int(second["balls"]) >= effective_balls
        or int(second["wickets"]) >= wickets_per_innings
    )
    if not second_concluded:
        return None

    if target_reached:
        # A successful chase is expressed through the wickets still available.
        margin = wickets_per_innings - int(second["wickets"])
        if margin <= 0:
            return None
        return CalculatedResult(
            status="Completed",
            winner_team_id=int(second["batting_team_id"]),
            result_type="Wickets",
            margin=margin,
            method=method,
        )

    # The score one below the target is the par score for ties and run margins.
    par_score = target - 1
    if int(second["runs"]) == par_score:
        return CalculatedResult(
            status="Completed",
            winner_team_id=None,
            result_type="Tie",
            method=method,
        )
    margin = par_score - int(second["runs"])
    if margin <= 0:
        return None
    return CalculatedResult(
        status="Completed",
        winner_team_id=int(first["batting_team_id"]),
        result_type="Runs",
        margin=margin,
        method=method,
    )


TEST_CLOSED_INNINGS = {
    "Completed", "All Out", "Declared", "Forfeited", "Target Reached",
}


def calculate_test_result(
    *,
    match: dict[str, Any],
    innings: list[dict[str, Any]],
    wickets_per_innings: int,
) -> CalculatedResult | None:
    """Calculate a Test result from chronological innings summaries.

    Draws remain explicit because the summary model does not track elapsed playing
    time. Wins and ties are derived only from closed innings and aggregate scores.
    """
    status = str(match["match_status"])
    if status in {"Abandoned", "No Result"}:
        return CalculatedResult(status=status, winner_team_id=None, result_type=status)
    if status == "Drawn" or match.get("result_type") == "Draw":
        return CalculatedResult(status="Drawn", winner_team_id=None, result_type="Draw")
    if status != "Completed" or not 2 <= len(innings) <= 4:
        return None
    if [int(row["innings_number"]) for row in innings] != list(range(1, len(innings) + 1)):
        return None
    if any(row.get("batting_team_id") is None or row.get("runs") is None for row in innings):
        return None

    participants = {int(match["home_team_id"]), int(match["away_team_id"])}
    if {int(row["batting_team_id"]) for row in innings} - participants:
        return None
    team_innings = {
        team_id: [row for row in innings if int(row["batting_team_id"]) == team_id]
        for team_id in participants
    }
    if any(not rows or len(rows) > 2 for rows in team_innings.values()):
        return None
    aggregates = {
        team_id: sum(int(row["runs"]) for row in rows)
        for team_id, rows in team_innings.items()
    }

    # An innings victory occurs after both losing innings close while the winner
    # has batted only once, irrespective of whether the follow-on was enforced.
    for winner, winner_rows in team_innings.items():
        loser = next(team_id for team_id in participants if team_id != winner)
        loser_rows = team_innings[loser]
        if (
            len(winner_rows) == 1
            and len(loser_rows) == 2
            and all(row.get("innings_status") in TEST_CLOSED_INNINGS for row in loser_rows)
            and aggregates[winner] > aggregates[loser]
        ):
            return CalculatedResult(
                status="Completed",
                winner_team_id=winner,
                result_type="Innings and Runs",
                margin=aggregates[winner] - aggregates[loser],
            )

    last = innings[-1]
    last_team = int(last["batting_team_id"])
    other_team = next(team_id for team_id in participants if team_id != last_team)
    target = aggregates[other_team] - (
        aggregates[last_team] - int(last["runs"])
    ) + 1
    if int(last["runs"]) >= target:
        wickets = last.get("wickets")
        if wickets is None:
            return None
        margin = wickets_per_innings - int(wickets)
        if margin <= 0:
            return None
        return CalculatedResult(
            status="Completed", winner_team_id=last_team,
            result_type="Wickets", margin=margin,
        )

    if last.get("innings_status") not in TEST_CLOSED_INNINGS:
        return None
    difference = aggregates[other_team] - aggregates[last_team]
    if difference > 0 and len(team_innings[last_team]) == 2:
        return CalculatedResult(
            status="Completed", winner_team_id=other_team,
            result_type="Runs", margin=difference,
        )
    if difference == 0 and all(len(rows) == 2 for rows in team_innings.values()):
        return CalculatedResult(
            status="Completed", winner_team_id=None, result_type="Tie",
        )
    return None
