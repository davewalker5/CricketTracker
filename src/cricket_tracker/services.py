"""Validation and transactional business operations for Cricket Tracker."""

from __future__ import annotations

import sqlite3
from datetime import date, time
from typing import Any

from cricket_tracker.formats import format_delivery_count, legal_balls_for_limit
from cricket_tracker.repositories import CricketRepository, Repository
from cricket_tracker.results import calculate_limited_overs_result


GENDERS = ("Men", "Women")
FORMATS = ("The Hundred", "T20", "One-Day", "Test", "Multi-format")
MATCH_STAGES = ("League", "Eliminator", "Semi-final", "Final")
MATCH_STATUSES = (
    "Scheduled", "In Progress", "Completed", "Postponed",
    "Abandoned", "Cancelled", "No Result",
)
TOSS_DECISIONS = ("Bat", "Field")
RESULT_TYPES = (
    "Runs", "Wickets", "Tie", "No Result", "Abandoned", "Walkover",
)
RESULT_METHODS = ("Standard", "DLS", "Super Five", "Super Over", "Forfeit", "Walkover", "Other")
INNINGS_STATUSES = (
    "not_started",
    "in_progress",
    "completed",
    "all_out",
    "target_reached",
    "innings_limit_reached",
    "abandoned",
)
COMPLETED_INNINGS_STATUSES = {
    "completed", "all_out", "target_reached", "innings_limit_reached",
}


class ValidationError(ValueError):
    """Represent an input problem that is safe to show to a user."""


def required_text(value: Any, label: str) -> str:
    """Normalise mandatory text.

    :param value: Candidate input.
    :param label: User-facing field label.
    :return: Stripped non-empty text.
    :raises ValidationError: If the input is blank.
    """
    cleaned = str(value).strip() if value is not None else ""
    if not cleaned:
        raise ValidationError(f"{label} is required.")
    return cleaned


def optional_text(value: Any) -> str | None:
    """Normalise optional text.

    :param value: Candidate input.
    :return: Stripped text or ``None``.
    """
    cleaned = str(value).strip() if value is not None else ""
    return cleaned or None


def non_negative(value: Any, label: str) -> int:
    """Convert input to a non-negative whole number.

    :param value: Candidate numeric input.
    :param label: User-facing field label.
    :return: Validated integer.
    :raises ValidationError: If input is not a non-negative whole number.
    """
    if isinstance(value, bool):
        raise ValidationError(f"{label} must be a whole number of zero or more.")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{label} must be a whole number of zero or more.") from error
    if number < 0 or (isinstance(value, float) and not value.is_integer()):
        raise ValidationError(f"{label} must be a whole number of zero or more.")
    return number


def optional_non_negative(value: Any, label: str) -> int | None:
    """Validate an optional non-negative number.

    :param value: Candidate numeric input.
    :param label: User-facing field label.
    :return: Validated integer or ``None``.
    """
    return None if value in (None, "") else non_negative(value, label)


def valid_choice(value: Any, choices: tuple[str, ...], label: str) -> str:
    """Validate a case-insensitive enumerated choice.

    :param value: Candidate input.
    :param choices: Supported canonical values.
    :param label: User-facing field label.
    :return: Canonical choice.
    :raises ValidationError: If the input is unsupported.
    """
    candidate = required_text(value, label)
    for choice in choices:
        if candidate.casefold() == choice.casefold():
            return choice
    raise ValidationError(f"{label} must be one of: {', '.join(choices)}.")


def valid_date(value: Any, label: str, required: bool = True) -> str | None:
    """Validate an ISO date.

    :param value: Date object or ISO text.
    :param label: User-facing field label.
    :param required: Whether blank input is rejected.
    :return: ISO date text or ``None``.
    :raises ValidationError: If the date is absent or malformed.
    """
    if value in (None, ""):
        if required:
            raise ValidationError(f"{label} is required.")
        return None
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as error:
        raise ValidationError(f"{label} must use YYYY-MM-DD.") from error


def valid_time(value: Any, label: str = "Start time") -> str | None:
    """Validate an optional time.

    :param value: Time object or ISO text.
    :param label: User-facing field label.
    :return: Normalised HH:MM text or ``None``.
    :raises ValidationError: If input is malformed.
    """
    if value in (None, ""):
        return None
    if isinstance(value, time):
        return value.strftime("%H:%M")
    try:
        return time.fromisoformat(str(value)).strftime("%H:%M")
    except ValueError as error:
        raise ValidationError(f"{label} must use HH:MM.") from error


class CricketService:
    """Validate and coordinate Cricket Tracker data operations."""

    def __init__(self, connection: sqlite3.Connection):
        """Initialise the service over an open transaction.

        :param connection: Open SQLite connection.
        :return: None.
        """
        self.repo = CricketRepository(connection)

    def _save(
        self, repository: Repository, entity_id: int | None, values: dict[str, Any]
    ) -> int:
        """Insert or update one entity.

        :param repository: Entity repository to use.
        :param entity_id: Existing identifier or ``None``.
        :param values: Validated column values.
        :return: Saved entity identifier.
        """
        if entity_id is None:
            return repository.insert(values)
        repository.update(entity_id, values)
        return entity_id

    def list_countries(self) -> list[dict[str, Any]]:
        """List countries.

        :return: Country rows.
        """
        return self.repo.countries.list_all()

    def save_country(self, entity_id: int | None = None, **values: Any) -> int:
        """Create or update a country.

        :param entity_id: Existing identifier or ``None``.
        :param values: Country name and optional code.
        :return: Saved identifier.
        """
        data = {
            "name": required_text(values.get("name"), "Country name"),
            "code": optional_text(values.get("code")),
        }
        if data["code"] and not 2 <= len(data["code"]) <= 3:
            raise ValidationError("Country code must contain two or three characters.")
        if data["code"]:
            data["code"] = data["code"].upper()
        return self._save(self.repo.countries, entity_id, data)

    def delete_country(self, entity_id: int) -> None:
        """Delete an unreferenced country.

        :param entity_id: Country identifier.
        :return: None.
        """
        self.repo.countries.delete(entity_id)

    def list_venues(self) -> list[dict[str, Any]]:
        """List venues.

        :return: Enriched venue rows.
        """
        return self.repo.list_venues()

    def save_venue(self, entity_id: int | None = None, **values: Any) -> int:
        """Create or update a venue.

        :param entity_id: Existing identifier or ``None``.
        :param values: Venue fields.
        :return: Saved identifier.
        """
        data = {
            "name": required_text(values.get("name"), "Venue name"),
            "city": optional_text(values.get("city")),
            "country_id": values.get("country_id"),
            "capacity": optional_non_negative(values.get("capacity"), "Capacity"),
        }
        return self._save(self.repo.venues, entity_id, data)

    def delete_venue(self, entity_id: int) -> None:
        """Delete an unreferenced venue.

        :param entity_id: Venue identifier.
        :return: None.
        """
        self.repo.venues.delete(entity_id)

    def list_teams(self) -> list[dict[str, Any]]:
        """List teams.

        :return: Enriched team rows.
        """
        return self.repo.list_teams()

    def save_team(self, entity_id: int | None = None, **values: Any) -> int:
        """Create or update a men's or women's team.

        :param entity_id: Existing identifier or ``None``.
        :param values: Team fields.
        :return: Saved identifier.
        """
        data = {
            "name": required_text(values.get("name"), "Team name"),
            "country_id": values.get("country_id"),
            "gender": valid_choice(values.get("gender"), GENDERS, "Gender"),
            "home_venue_id": values.get("home_venue_id"),
        }
        return self._save(self.repo.teams, entity_id, data)

    def delete_team(self, entity_id: int) -> None:
        """Delete an unreferenced team.

        :param entity_id: Team identifier.
        :return: None.
        """
        self.repo.teams.delete(entity_id)

    def list_rulesets(self) -> list[dict[str, Any]]:
        """List competition rulesets.

        :return: Ruleset rows.
        """
        return self.repo.list_rulesets()

    def list_match_formats(self, active_only: bool = False) -> list[dict[str, Any]]:
        """List the reusable match formats.

        :param active_only: Whether to omit formats unavailable to new rulesets.
        :return: Match-format rows in display order.
        """
        # Editors normally need active formats while existing records may need all formats.
        formats = self.repo.match_formats.list_all()
        if active_only:
            return [match_format for match_format in formats if match_format["active"]]
        return formats

    def save_ruleset(self, entity_id: int | None = None, **values: Any) -> int:
        """Create or update a competition ruleset.

        :param entity_id: Existing identifier or ``None``.
        :param values: Points, table behavior, and innings allocation.
        :return: Saved identifier.
        """
        allowed_sort_fields = {"points", "net_run_rate", "wins", "name"}
        sort_order = required_text(
            values.get("table_sort_order", "points,net_run_rate,wins"),
            "Table sort order",
        )
        fields = [field.strip() for field in sort_order.split(",") if field.strip()]
        if not fields or set(fields) - allowed_sort_fields:
            raise ValidationError(
                "Table sort order may contain points, net_run_rate, wins, and name."
            )
        uses_net_run_rate = bool(values.get("uses_net_run_rate", True))
        has_standings = bool(values.get("has_standings", True))
        if not uses_net_run_rate:
            # Disabled calculations cannot remain as a misleading ranking criterion.
            fields = [field for field in fields if field != "net_run_rate"]
            if not fields:
                fields = ["points", "wins", "name"]
        data = {
            "name": required_text(values.get("name"), "Ruleset name"),
            "points_for_win": non_negative(values.get("points_for_win", 2), "Points for win"),
            "points_for_tie": non_negative(values.get("points_for_tie", 1), "Points for tie"),
            "points_for_no_result": non_negative(
                values.get("points_for_no_result", 1), "Points for no result"
            ),
            "points_for_abandonment": non_negative(
                values.get(
                    "points_for_abandonment",
                    values.get("points_for_no_result", 1),
                ),
                "Points for abandonment",
            ),
            "points_for_loss": non_negative(values.get("points_for_loss", 0), "Points for loss"),
            "uses_net_run_rate": int(uses_net_run_rate and has_standings),
            "include_knockout_matches_in_table": int(
                bool(values.get("include_knockout_matches_in_table", False))
            ),
            "table_sort_order": ",".join(fields),
            "balls_per_innings": non_negative(
                values.get("balls_per_innings", 100), "Balls per innings"
            ),
            "wickets_per_innings": non_negative(
                values.get("wickets_per_innings", 10), "Wickets per innings"
            ),
            "balls_per_rate_unit": non_negative(
                values.get("balls_per_rate_unit", 6), "Balls per rate unit"
            ),
            "combine_gender_tables": int(
                bool(values.get("combine_gender_tables", False))
            ),
            "has_standings": int(has_standings),
            "ties_may_stand": int(bool(values.get("ties_may_stand", True))),
            "tie_break_winner_allowed": int(
                bool(values.get("tie_break_winner_allowed", True))
            ),
            "revised_targets_allowed": int(
                bool(values.get("revised_targets_allowed", True))
            ),
            "match_format_id": int(values.get("match_format_id", 1)),
        }
        if (
            not data["balls_per_innings"]
            or not data["wickets_per_innings"]
            or not data["balls_per_rate_unit"]
        ):
            raise ValidationError(
                "Balls, wickets, and balls per rate unit must be greater than zero."
            )
        # Resolve the reference here so callers receive a domain error rather than SQL text.
        match_format = self.repo.match_formats.get(data["match_format_id"])
        if not match_format:
            raise ValidationError("Select a valid match format.")
        return self._save(self.repo.rulesets, entity_id, data)

    def delete_ruleset(self, entity_id: int) -> None:
        """Delete an unreferenced competition ruleset.

        :param entity_id: Ruleset identifier.
        :return: None.
        """
        self.repo.rulesets.delete(entity_id)

    def list_competitions(self) -> list[dict[str, Any]]:
        """List competitions.

        :return: Enriched competition rows.
        """
        return self.repo.list_competitions()

    def save_competition(self, entity_id: int | None = None, **values: Any) -> int:
        """Create or update a competition definition.

        :param entity_id: Existing identifier or ``None``.
        :param values: Competition fields.
        :return: Saved identifier.
        """
        data = {
            "name": required_text(values.get("name"), "Competition name"),
            "gender": valid_choice(values.get("gender"), GENDERS, "Gender"),
            "format": required_text(values.get("format", "The Hundred"), "Format"),
            "country_id": values.get("country_id"),
            "season": required_text(values.get("season"), "Season"),
            "ruleset_id": int(values["ruleset_id"]),
        }
        return self._save(self.repo.competitions, entity_id, data)

    def delete_competition(self, entity_id: int) -> None:
        """Delete an unreferenced competition.

        :param entity_id: Competition identifier.
        :return: None.
        """
        self.repo.competitions.delete(entity_id)

    def list_matches(self, competition_id: int | None = None) -> list[dict[str, Any]]:
        """List fixtures and results.

        :param competition_id: Optional competition filter.
        :return: Enriched match rows.
        """
        matches = self.repo.list_matches(competition_id)
        for match in matches:
            # Null overrides inherit the canonical allocation from the match format.
            format_balls = legal_balls_for_limit(
                int(match["innings_limit"]),
                limit_unit=str(match["limit_unit"]),
                balls_per_over=match["balls_per_over"],
            )
            scheduled_balls = int(match["scheduled_balls"] or format_balls)
            effective_balls = int(match["revised_balls"] or scheduled_balls)
            match["scheduled_delivery_display"] = format_delivery_count(
                scheduled_balls,
                limit_unit=str(match["limit_unit"]),
                balls_per_over=match["balls_per_over"],
            )
            match["effective_delivery_display"] = format_delivery_count(
                effective_balls,
                limit_unit=str(match["limit_unit"]),
                balls_per_over=match["balls_per_over"],
            )
        return matches

    def _playing_conditions_for_competition(
        self, competition_id: int
    ) -> dict[str, Any]:
        """Return ruleset and format properties for a competition.

        :param competition_id: Competition identifier.
        :return: Combined ruleset and match-format properties.
        :raises ValidationError: If the competition references are invalid.
        """
        # A single join keeps match allocation validation driven by persisted metadata.
        row = self.repo.connection.execute(
            """
            SELECT r.wickets_per_innings, r.ties_may_stand,
                   r.tie_break_winner_allowed, r.revised_targets_allowed, f.*
            FROM competitions c
            JOIN competition_rulesets r ON r.id = c.ruleset_id
            JOIN match_formats f ON f.id = r.match_format_id
            WHERE c.id = ?
            """,
            (competition_id,),
        ).fetchone()
        if not row:
            raise ValidationError("Select a valid competition.")
        return dict(row)

    def effective_innings_balls(self, match_id: int) -> int:
        """Return the effective legal-ball allocation for a match innings.

        :param match_id: Match identifier.
        :return: Revised, scheduled, or format-default legal balls.
        :raises ValidationError: If the match or its playing conditions are invalid.
        """
        match = self.repo.matches.get(match_id)
        if not match:
            raise ValidationError("Select a valid match.")
        conditions = self._playing_conditions_for_competition(
            int(match["competition_id"])
        )
        # Match overrides are canonical balls; only the format default needs conversion.
        default_balls = legal_balls_for_limit(
            int(conditions["innings_limit"]),
            limit_unit=str(conditions["limit_unit"]),
            balls_per_over=conditions["balls_per_over"],
        )
        return int(match["revised_balls"] or match["scheduled_balls"] or default_balls)

    def resolve_chasing_target(
        self, match_id: int, supplied_target: int | None = None
    ) -> int | None:
        """Resolve the authoritative target for a match's chasing innings.

        :param match_id: Match identifier.
        :param supplied_target: Optional legacy target stored with the innings.
        :return: Revised, supplied, original, or derived target; otherwise ``None``.
        :raises ValidationError: If the match does not exist.
        """
        match = self.repo.matches.get(match_id)
        if not match:
            raise ValidationError("Select a valid match.")
        # Revised targets override legacy innings values and original targets.
        if match.get("revised_target_runs") is not None:
            return int(match["revised_target_runs"])
        if supplied_target is not None:
            return supplied_target
        if match.get("target_runs") is not None:
            return int(match["target_runs"])
        first = self.repo.connection.execute(
            """
            SELECT runs
            FROM innings
            WHERE match_id = ? AND innings_number = 1
            """,
            (match_id,),
        ).fetchone()
        # An ordinary target is one run more than the first-innings score.
        return int(first["runs"]) + 1 if first and first["runs"] is not None else None

    def _match_teams(self, match_id: int) -> tuple[int, int]:
        """Return the two teams participating in a match.

        :param match_id: Match identifier.
        :return: Home and away team identifiers.
        :raises ValidationError: If the match does not exist.
        """
        match = self.repo.matches.get(match_id)
        if not match:
            raise ValidationError("Select a valid match.")
        return int(match["home_team_id"]), int(match["away_team_id"])

    def save_match(self, entity_id: int | None = None, **values: Any) -> int:
        """Create or update a fixture or result.

        :param entity_id: Existing identifier or ``None``.
        :param values: Fixture, toss and result fields.
        :return: Saved identifier.
        :raises ValidationError: If teams or result fields are inconsistent.
        """
        home_team_id = int(values["home_team_id"])
        away_team_id = int(values["away_team_id"])
        if home_team_id == away_team_id:
            raise ValidationError("A team cannot play itself.")
        participants = {home_team_id, away_team_id}
        toss_winner = values.get("toss_winner_team_id")
        winning_team = values.get("winning_team_id")
        explicit_result_source = optional_text(values.get("result_source"))
        result_source = explicit_result_source
        # Supplying a result explicitly is treated as an override for backward-compatible imports.
        if not result_source and any(
            values.get(field) not in (None, "")
            for field in ("winning_team_id", "result_type", "result_margin_value")
        ):
            result_source = "Manual"
        if result_source and result_source not in {"Calculated", "Manual"}:
            raise ValidationError("Result source must be Calculated or Manual.")
        if toss_winner not in (None, "") and int(toss_winner) not in participants:
            raise ValidationError("Toss winner must be one of the match teams.")
        if winning_team not in (None, "") and int(winning_team) not in participants:
            raise ValidationError("Winner must be one of the match teams.")
        toss_decision = optional_text(values.get("toss_decision"))
        result_type = optional_text(values.get("result_type"))
        if toss_decision:
            toss_decision = valid_choice(toss_decision, TOSS_DECISIONS, "Toss decision")
        if result_type:
            result_type = valid_choice(result_type, RESULT_TYPES, "Result type")
        margin = optional_non_negative(values.get("result_margin_value"), "Result margin")
        margin_type = optional_text(values.get("result_margin_type"))
        if result_type in {"Runs", "Wickets"}:
            if winning_team in (None, "") or margin is None:
                raise ValidationError("A run or wicket result requires a winner and margin.")
            margin_type = result_type
        elif margin is not None or margin_type is not None:
            raise ValidationError("Only run or wicket results have a margin.")
        if result_type in {"No Result", "Abandoned"} and winning_team not in (None, ""):
            raise ValidationError(f"A {result_type.lower()} cannot have a winner.")
        result_method = optional_text(values.get("result_method"))
        override_reason = optional_text(values.get("result_override_reason"))
        if result_method:
            result_method = valid_choice(result_method, RESULT_METHODS, "Result method")
        if (
            result_type == "Tie"
            and winning_team not in (None, "")
            and not (
                result_source == "Manual"
                and result_method in {"Super Five", "Super Over", "Other"}
            )
        ):
            raise ValidationError(
                "A tied match can only have a manual tie-break winner and method."
            )
        if explicit_result_source == "Manual" and not override_reason:
            raise ValidationError("A manual result override requires an override reason.")
        if result_source == "Manual" and not override_reason:
            # Legacy callers receive a durable provenance reason instead of losing their result.
            override_reason = "Result entered manually."
        if result_source == "Manual" and not result_type:
            raise ValidationError("A manual result override requires a result type.")
        if result_source == "Manual" and not result_method:
            result_method = "Standard"
        status = valid_choice(
            values.get("match_status", "Scheduled"), MATCH_STATUSES, "Match status"
        )
        if result_type in {"Abandoned", "No Result"}:
            # Exceptional result types conclusively determine their matching status.
            status = result_type
        competition_id = int(values["competition_id"])
        competition = self.repo.competitions.get(competition_id)
        if not competition:
            raise ValidationError("Select a valid competition.")
        team_rows = [
            self.repo.teams.get(team_id)
            for team_id in (home_team_id, away_team_id)
        ]
        if any(team is None for team in team_rows):
            raise ValidationError("Select valid home and away teams.")
        if any(team["gender"] != competition["gender"] for team in team_rows):
            raise ValidationError(
                "Home and away teams must match the competition gender."
            )
        conditions = self._playing_conditions_for_competition(competition_id)
        format_balls = legal_balls_for_limit(
            int(conditions["innings_limit"]),
            limit_unit=str(conditions["limit_unit"]),
            balls_per_over=conditions["balls_per_over"],
        )
        scheduled_balls = optional_non_negative(
            values.get("scheduled_balls"), "Scheduled allocation"
        )
        revised_balls = optional_non_negative(
            values.get("revised_balls"), "Revised allocation"
        )
        target_runs = optional_non_negative(
            values.get("target_runs"), "Original target"
        )
        revised_target_runs = optional_non_negative(
            values.get("revised_target_runs"), "Revised target"
        )
        if scheduled_balls == 0 or revised_balls == 0:
            raise ValidationError("Match innings allocations must be greater than zero.")
        if target_runs == 0 or revised_target_runs == 0:
            raise ValidationError("Match targets must be greater than zero.")
        if scheduled_balls is not None and scheduled_balls > format_balls:
            raise ValidationError(
                "Scheduled allocation cannot exceed the match-format innings limit."
            )
        if revised_balls is not None and revised_balls > (scheduled_balls or format_balls):
            raise ValidationError(
                "Revised allocation cannot exceed the scheduled innings allocation."
            )
        if (
            revised_target_runs is not None
            and (
                not bool(conditions["revised_target_supported"])
                or not bool(conditions["revised_targets_allowed"])
            )
        ):
            raise ValidationError(
                "The selected ruleset does not support revised targets."
            )
        if (
            result_type == "Tie"
            and winning_team not in (None, "")
            and not bool(conditions["tie_break_winner_allowed"])
        ):
            raise ValidationError("This ruleset does not allow a tie-break winner.")
        if (
            result_source == "Manual"
            and result_type == "Tie"
            and winning_team in (None, "")
            and not bool(conditions["ties_may_stand"])
        ):
            raise ValidationError("This ruleset does not allow a tie to stand.")
        data = {
            "competition_id": competition_id,
            "match_date": valid_date(values.get("match_date"), "Match date"),
            "start_time": valid_time(values.get("start_time")),
            "venue_id": values.get("venue_id"),
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "match_stage": valid_choice(
                values.get("match_stage", "League"), MATCH_STAGES, "Match stage"
            ),
            "match_status": status,
            "toss_winner_team_id": None if toss_winner in (None, "") else int(toss_winner),
            "toss_decision": toss_decision,
            "winning_team_id": None if winning_team in (None, "") else int(winning_team),
            "result_type": result_type,
            "result_margin_value": margin,
            "result_margin_type": margin_type,
            "result_method": result_method,
            "result_source": result_source,
            "result_override_reason": override_reason,
            "scheduled_balls": scheduled_balls,
            "revised_balls": revised_balls,
            "target_runs": target_runs,
            "revised_target_runs": revised_target_runs,
        }
        saved_id = self._save(self.repo.matches, entity_id, data)
        # Rebuild ordinary result fields after a status or participant change.
        self.recalculate_match_result(saved_id)
        # Bulk import loads matches before its separate innings dataset.
        if (
            status == "Completed"
            and result_source == "Manual"
            and result_method == "Standard"
            and not values.get("_defer_completion_validation", False)
        ):
            self.validate_completed_match(saved_id)
        return saved_id

    def delete_match(self, entity_id: int) -> None:
        """Delete a match and its innings.

        :param entity_id: Match identifier.
        :return: None.
        """
        self.repo.matches.delete(entity_id)

    def list_innings(self, match_id: int | None = None) -> list[dict[str, Any]]:
        """List innings summaries.

        :param match_id: Optional match filter.
        :return: Enriched innings rows.
        """
        innings = self.repo.list_innings(match_id)
        for row in innings:
            # Draft innings without a delivery count retain a blank progress value.
            row["delivery_display"] = (
                format_delivery_count(
                    int(row["balls"]),
                    limit_unit=str(row["limit_unit"]),
                    balls_per_over=row["balls_per_over"],
                )
                if row["balls"] is not None
                else None
            )
        return innings

    def save_innings(self, entity_id: int | None = None, **values: Any) -> int:
        """Create or update an innings summary.

        :param entity_id: Existing identifier or ``None``.
        :param values: Innings teams and totals.
        :return: Saved identifier.
        :raises ValidationError: If the innings is inconsistent with its match.
        """
        match_id = int(values["match_id"])
        batting_team = (
            int(values["batting_team_id"])
            if values.get("batting_team_id") is not None
            else None
        )
        bowling_team = (
            int(values["bowling_team_id"])
            if values.get("bowling_team_id") is not None
            else None
        )
        participants = set(self._match_teams(match_id))
        if batting_team is not None and batting_team not in participants:
            raise ValidationError("The batting team must belong to the match.")
        if bowling_team is not None and bowling_team not in participants:
            raise ValidationError("The bowling team must belong to the match.")
        if batting_team is not None and batting_team == bowling_team:
            raise ValidationError("Batting and bowling teams must differ.")
        if (
            batting_team is not None
            and bowling_team is not None
            and {batting_team, bowling_team} != participants
        ):
            raise ValidationError("Both innings teams must belong to the match.")
        innings_number = non_negative(values.get("innings_number"), "Innings number")
        conditions = self._ruleset_for_match(match_id)
        maximum_innings = int(conditions["innings_per_team"]) * 2
        if innings_number < 1 or innings_number > maximum_innings:
            raise ValidationError(
                f"Innings number must be between 1 and {maximum_innings}."
            )
        wickets = optional_non_negative(values.get("wickets"), "Wickets")
        if wickets is not None and wickets > 10:
            raise ValidationError("Wickets cannot exceed 10.")
        balls = optional_non_negative(values.get("balls"), "Balls")
        allocation = self.effective_innings_balls(match_id)
        if balls is not None and balls > allocation:
            raise ValidationError(
                f"Legal balls cannot exceed the match allocation of {allocation}."
            )
        supplied_totals = (
            values.get("runs"), values.get("wickets"), values.get("balls")
        )
        completed_value = values.get("completed")
        supplied_status = optional_text(values.get("innings_status"))
        if supplied_status:
            innings_status = valid_choice(
                supplied_status, INNINGS_STATUSES, "Innings status"
            )
        elif completed_value is not None:
            # Legacy callers continue to control conclusion through the boolean field.
            innings_status = (
                "completed"
                if bool(completed_value)
                else (
                    "in_progress"
                    if any(value is not None for value in supplied_totals)
                    else "not_started"
                )
            )
        elif any(value is not None for value in supplied_totals):
            innings_status = (
                "completed"
                if batting_team is not None
                and bowling_team is not None
                and all(value is not None for value in supplied_totals)
                else "in_progress"
            )
        else:
            innings_status = "not_started"
        completed = innings_status in COMPLETED_INNINGS_STATUSES
        if completed and None in (
            batting_team, bowling_team, values.get("runs"),
            wickets, balls,
        ):
            raise ValidationError(
                "Completed innings require both teams, runs, wickets, and balls."
            )
        if innings_status == "not_started" and any(
            value not in (None, 0) for value in supplied_totals
        ):
            raise ValidationError("A not-started innings cannot contain score progress.")
        if innings_status == "all_out" and wickets != int(
            conditions["wickets_per_innings"]
        ):
            raise ValidationError(
                "An all-out innings must have lost every available wicket."
            )
        if innings_status == "innings_limit_reached" and balls != allocation:
            raise ValidationError(
                "An innings-limit-reached innings must use its full allocation."
            )
        if innings_status == "target_reached":
            if innings_number != 2:
                raise ValidationError("Only the chasing innings can reach a target.")
            supplied_target = optional_non_negative(values.get("target"), "Target")
            target = self.resolve_chasing_target(match_id, supplied_target)
            if target in (None, 0):
                raise ValidationError("A target-reached innings requires a target.")
            runs = optional_non_negative(values.get("runs"), "Runs")
            if runs is None or runs < target:
                raise ValidationError(
                    "A target-reached innings must meet or exceed its target."
                )
        data = {
            "match_id": match_id,
            "innings_number": innings_number,
            "batting_team_id": batting_team,
            "bowling_team_id": bowling_team,
            "runs": optional_non_negative(values.get("runs"), "Runs"),
            "wickets": wickets,
            "balls": balls,
            "extras": optional_non_negative(values.get("extras"), "Extras"),
            "target": optional_non_negative(values.get("target"), "Target"),
            "completed": int(completed),
            "innings_status": innings_status,
        }
        if data["target"] == 0:
            raise ValidationError("Target must be greater than zero when supplied.")
        saved_id = self._save(self.repo.innings, entity_id, data)
        # Explicitly incomplete source data invalidates an ordinary generated summary.
        result_invalidated = self._invalidate_result_for_incomplete_innings(match_id)
        if not result_invalidated:
            # Two explicitly completed innings conclusively finish an ordinary match.
            self._complete_match_from_innings(match_id)
            # Keep the query-friendly match summary in sync in this transaction.
            self.recalculate_match_result(match_id)
        return saved_id

    def delete_innings(self, entity_id: int) -> None:
        """Delete an innings summary.

        :param entity_id: Innings identifier.
        :return: None.
        """
        innings = self.repo.innings.get(entity_id)
        if not innings:
            raise LookupError(f"No inning exists with ID {entity_id}.")
        self.repo.innings.delete(entity_id)
        # Removing source data reopens an ordinary match and clears its generated result.
        match_id = int(innings["match_id"])
        if not self._invalidate_result_for_incomplete_innings(match_id):
            self.recalculate_match_result(match_id)

    def _invalidate_result_for_incomplete_innings(self, match_id: int) -> bool:
        """Clear an ordinary result when both innings are not explicitly complete.

        :param match_id: Match identifier.
        :return: ``True`` when incomplete source data withholds recalculation.
        :raises ValidationError: If the match does not exist.
        """
        match = self.repo.matches.get(match_id)
        if not match:
            raise ValidationError("Select a valid match.")
        innings = self.repo.list_innings(match_id)
        both_completed = (
            len(innings) == 2
            and [row["innings_number"] for row in innings] == [1, 2]
            and all(bool(row["completed"]) for row in innings)
        )
        if (
            both_completed
            or match.get("result_source") == "Manual"
            or match["match_status"] in {"No Result", "Abandoned"}
        ):
            return False
        # An explicit uncomplete action takes precedence over score-based conclusion inference.
        empty_result = {
            "winning_team_id": None,
            "result_type": None,
            "result_margin_value": None,
            "result_margin_type": None,
            "result_method": (
                match.get("result_method")
                if match.get("revised_target_runs") is not None
                else None
            ),
            "result_source": None,
            "result_override_reason": None,
        }
        if match["match_status"] == "Completed":
            empty_result["match_status"] = "In Progress"
        self.repo.matches.update(match_id, empty_result)
        return True

    def _complete_match_from_innings(self, match_id: int) -> bool:
        """Mark an ordinary match complete when both expected innings are complete.

        :param match_id: Match identifier.
        :return: ``True`` when the match status was changed, otherwise ``False``.
        :raises ValidationError: If the match does not exist.
        """
        match = self.repo.matches.get(match_id)
        if not match:
            raise ValidationError("Select a valid match.")
        # Preserve statuses that describe interruptions or externally determined outcomes.
        if match["match_status"] not in {"Scheduled", "In Progress"}:
            return False
        innings = self.repo.list_innings(match_id)
        expected_innings = (
            len(innings) == 2
            and [row["innings_number"] for row in innings] == [1, 2]
            and all(bool(row["completed"]) for row in innings)
        )
        if not expected_innings:
            return False
        # Status and generated result are updated within the same caller transaction.
        self.repo.matches.update(match_id, {"match_status": "Completed"})
        return True

    def derive_match_result(self, match_id: int) -> dict[str, Any] | None:
        """Derive a limited-overs result from match status and innings.

        :param match_id: Match identifier.
        :return: Generated result fields, or ``None`` when data is insufficient.
        :raises ValidationError: If the match does not exist.
        """
        match = self.repo.matches.get(match_id)
        if not match:
            raise ValidationError("Select a valid match.")
        innings = self.repo.list_innings(match_id)
        ruleset = self._ruleset_for_match(match_id)
        # The generic entry point delegates all supported one-innings formats.
        calculated = calculate_limited_overs_result(
            match=match,
            innings=innings,
            wickets_per_innings=int(ruleset["wickets_per_innings"]),
            effective_balls=self.effective_innings_balls(match_id),
        )
        return calculated.as_match_fields() if calculated else None

    def recalculate_match_result(self, match_id: int) -> dict[str, Any] | None:
        """Refresh a match's stored generated result without replacing an override.

        :param match_id: Match identifier.
        :return: Newly calculated fields, or ``None`` when no result can be derived.
        """
        match = self.repo.matches.get(match_id)
        if not match:
            raise ValidationError("Select a valid match.")
        calculated = self.derive_match_result(match_id)
        # A manual official result remains authoritative until the user removes it.
        if match.get("result_source") == "Manual":
            return calculated
        ruleset = self._ruleset_for_match(match_id)
        official_result = calculated
        if (
            calculated
            and calculated["result_type"] == "Tie"
            and not bool(ruleset["ties_may_stand"])
        ):
            # Preserve the derived tie for comparison while awaiting an official tie-break.
            official_result = None
        empty_result = {
            "winning_team_id": None,
            "result_type": None,
            "result_margin_value": None,
            "result_margin_type": None,
            "result_method": (
                match.get("result_method")
                if match.get("revised_target_runs") is not None
                else None
            ),
            "result_source": None,
            "result_override_reason": None,
        }
        self.repo.matches.update(match_id, official_result or empty_result)
        return calculated

    def _ruleset_for_match(self, match_id: int) -> dict[str, Any]:
        """Return the competition ruleset governing a match.

        :param match_id: Match identifier.
        :return: Ruleset row.
        :raises ValidationError: If references are invalid.
        """
        row = self.repo.connection.execute(
            """
            SELECT r.*, f.code AS match_format_code,
                   f.name AS match_format_name, f.innings_per_team,
                   f.limit_unit, f.innings_limit, f.balls_per_over,
                   f.draw_allowed, f.tie_allowed, f.revised_target_supported
            FROM matches m
            JOIN competitions c ON c.id = m.competition_id
            JOIN competition_rulesets r ON r.id = c.ruleset_id
            JOIN match_formats f ON f.id = r.match_format_id
            WHERE m.id = ?
            """,
            (match_id,),
        ).fetchone()
        if not row:
            raise ValidationError("The match has no valid competition ruleset.")
        return dict(row)

    def validate_completed_match(self, match_id: int) -> None:
        """Ensure a completed match contains a coherent result.

        :param match_id: Match identifier.
        :return: None.
        :raises ValidationError: If required result or innings data is absent.
        """
        match = self.repo.matches.get(match_id)
        if not match:
            raise ValidationError("Select a valid match.")
        result_type = match["result_type"]
        if not result_type:
            raise ValidationError("A completed match requires a result type.")
        if result_type in {"No Result", "Abandoned", "Walkover"}:
            return
        innings = self.repo.list_innings(match_id)
        if len(innings) < 2:
            raise ValidationError("A completed result requires two innings summaries.")
        first, second = innings[0], innings[1]
        if {first["batting_team_id"], second["batting_team_id"]} != {
            match["home_team_id"], match["away_team_id"]
        }:
            raise ValidationError("Completed innings must cover both match teams.")
        if result_type == "Tie":
            if first["runs"] != second["runs"]:
                raise ValidationError("A tied result requires equal innings scores.")
            return
        winner = match["winning_team_id"]
        if result_type == "Runs":
            expected_winner = first["batting_team_id"]
            expected_margin = first["runs"] - second["runs"]
        else:
            expected_winner = second["batting_team_id"]
            expected_margin = 10 - second["wickets"]
        if expected_margin <= 0 or winner != expected_winner:
            raise ValidationError("Winner is inconsistent with the innings scores.")
        if match["result_margin_value"] != expected_margin:
            raise ValidationError("Result margin is inconsistent with the innings scores.")

    def result_description(self, match: dict[str, Any]) -> str:
        """Build a human-readable result description.

        :param match: Match row, optionally containing ``winning_team_name``.
        :return: Supporter-friendly result text.
        """
        result_type = match.get("result_type")
        if not result_type:
            return str(match.get("match_status", "Scheduled"))
        # Numeric victories include a singularised unit and any exceptional method.
        if result_type in {"Runs", "Wickets"}:
            winner = match.get("winning_team_name") or "Winner"
            margin = int(match["result_margin_value"])
            unit = result_type.lower()
            if margin == 1:
                unit = unit.rstrip("s")
            description = f"{winner} won by {margin} {unit}"
            method = match.get("result_method")
            if method and method != "Standard":
                description = f"{description} using the {method} method"
            return description
        if result_type == "Tie":
            winner = match.get("winning_team_name")
            method = match.get("result_method")
            if winner and method and method != "Standard":
                # A manual tie-break can name an official winner without scorecard data.
                return f"Match tied; {winner} won the {method}"
            return "Match tied"
        if result_type == "No Result":
            return "No result"
        if result_type == "Abandoned":
            return "Match abandoned"
        # Exceptional non-numeric result types are already suitable display labels.
        return str(result_type)
