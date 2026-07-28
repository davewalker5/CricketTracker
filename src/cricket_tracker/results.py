"""Structured result calculation for one-innings limited-overs cricket."""

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
