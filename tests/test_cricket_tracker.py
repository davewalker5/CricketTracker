"""End-to-end tests for Cricket Tracker's initial implementation."""

from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from cricket_tracker import app as tracker_app
from cricket_tracker.cli import streamlit_entrypoint
from cricket_tracker.exports import DATASETS, export_csv
from cricket_tracker.formats import format_delivery_count
from cricket_tracker.imports import CricketImporter
from cricket_tracker.services import CricketService, ValidationError
from cricket_tracker.standings import (
    calculate_combined_standings,
    calculate_standings,
    combined_competition_ids,
    table_to_csv,
)


def test_streamlit_entrypoint_is_packaged() -> None:
    """Resolve the launcher to a Python file included inside the package.

    :return: None.
    """
    entrypoint = streamlit_entrypoint()
    # A wheel contains package modules but excludes the source-root wrapper.
    assert entrypoint.name == "app.py"
    assert entrypoint.parent.name == "cricket_tracker"
    assert entrypoint.is_file()


def complete_match(service: CricketService, core: dict[str, int]) -> None:
    """Enter two innings and a completed run result.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    service.save_innings(
        match_id=core["match"], innings_number=1, batting_team_id=core["home"],
        bowling_team_id=core["away"], runs=150, wickets=6, balls=100,
    )
    service.save_innings(
        match_id=core["match"], innings_number=2, batting_team_id=core["away"],
        bowling_team_id=core["home"], runs=137, wickets=8, balls=100,
    )
    service.save_match(
        entity_id=core["match"], competition_id=core["competition"],
        match_date="2026-07-20", venue_id=core["venue"],
        home_team_id=core["home"], away_team_id=core["away"],
        match_stage="League", match_status="Completed",
        winning_team_id=core["home"], result_type="Runs",
        result_margin_value=13, result_margin_type="Runs",
    )


def test_initial_schema_is_cricket_native(connection: sqlite3.Connection) -> None:
    """Verify fresh installations contain only the intended domain.

    :param connection: Fresh database connection.
    :return: None.
    """
    tables = {
        row["name"] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {"matches", "innings", "competitions", "competition_rulesets"} <= tables
    assert "match_formats" in tables
    assert "competition_seasons" not in tables
    assert "referees" not in tables
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(matches)")}
    assert "home_score" not in columns
    assert {"match_status", "winning_team_id", "result_margin_type"} <= columns
    assert {"scheduled_balls", "revised_balls"} <= columns
    assert {"target_runs", "revised_target_runs"} <= columns
    assert "notes" not in columns
    team_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(teams)")
    }
    assert "short_name" not in team_columns
    assert "active" not in team_columns
    assert "notes" not in team_columns
    innings_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(innings)")
    }
    assert "notes" not in innings_columns
    assert "innings_status" in innings_columns
    for table in ("venues", "competitions"):
        columns = {
            row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        assert "notes" not in columns
    ruleset_columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(competition_rulesets)"
        )
    }
    assert "notes" not in ruleset_columns
    assert "match_format_id" in ruleset_columns


def test_standard_match_formats_are_seeded_and_hundred_is_associated(
    service: CricketService,
) -> None:
    """Verify the format foundation and backward-compatible ruleset association.

    :param service: Cricket service.
    :return: None.
    """
    # Stable codes let later phases select behaviour without inspecting display names.
    formats = {row["code"]: row for row in service.list_match_formats()}

    assert set(formats) == {"HUNDRED", "T20", "ODI"}
    assert formats["HUNDRED"]["limit_unit"] == "balls"
    assert formats["HUNDRED"]["innings_limit"] == 100
    assert formats["HUNDRED"]["balls_per_over"] is None
    assert formats["T20"]["innings_limit"] == 20
    assert formats["T20"]["balls_per_over"] == 6
    assert formats["ODI"]["innings_limit"] == 50
    assert service.list_rulesets()[0]["match_format_id"] == formats["HUNDRED"]["id"]


@pytest.mark.parametrize(
    ("legal_balls", "expected"),
    [
        (0, "0.0 overs"),
        (5, "0.5 overs"),
        (6, "1.0 overs"),
        (17, "2.5 overs"),
        (83, "13.5 overs"),
        (120, "20.0 overs"),
        (300, "50.0 overs"),
    ],
)
def test_format_delivery_count_uses_cricket_over_notation(
    legal_balls: int, expected: str
) -> None:
    """Convert legal balls into six-ball over notation.

    :param legal_balls: Canonical delivery count.
    :param expected: Expected cricket notation.
    :return: None.
    """
    # The remainder after complete overs is displayed after the separator.
    assert format_delivery_count(
        legal_balls, limit_unit="overs", balls_per_over=6
    ) == expected


def test_format_delivery_count_preserves_hundred_display() -> None:
    """Keep The Hundred delivery progress expressed in balls.

    :return: None.
    """
    # Ball-based formats do not require or use an over size.
    assert format_delivery_count(
        69, limit_unit="balls", balls_per_over=None
    ) == "69 balls"


def test_innings_list_uses_its_ruleset_match_format(
    service: CricketService, core: dict[str, int]
) -> None:
    """Expose format-aware delivery progress for innings presentation.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    t20_format = next(
        row for row in service.list_match_formats() if row["code"] == "T20"
    )
    # Reassociate the fixture ruleset to prove display is driven by format metadata.
    service.repo.rulesets.update(
        core["ruleset"], {"match_format_id": t20_format["id"]}
    )
    service.save_innings(
        match_id=core["match"],
        innings_number=1,
        batting_team_id=core["home"],
        bowling_team_id=core["away"],
        runs=100,
        wickets=3,
        balls=83,
        completed=False,
    )

    assert service.list_innings(core["match"])[0]["delivery_display"] == "13.5 overs"


def assign_core_match_format(
    service: CricketService, core: dict[str, int], format_code: str
) -> None:
    """Associate the core fixture's ruleset with a seeded match format.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :param format_code: Stable seeded match-format code.
    :return: None.
    """
    # Ruleset association is the sole source of format behavior for its competition.
    match_format = next(
        row for row in service.list_match_formats() if row["code"] == format_code
    )
    service.repo.rulesets.update(
        core["ruleset"], {"match_format_id": match_format["id"]}
    )


@pytest.mark.parametrize(
    ("format_code", "expected_balls", "expected_display"),
    [
        ("HUNDRED", 100, "100 balls"),
        ("T20", 120, "20.0 overs"),
        ("ODI", 300, "50.0 overs"),
    ],
)
def test_match_format_drives_default_innings_allocation(
    service: CricketService,
    core: dict[str, int],
    format_code: str,
    expected_balls: int,
    expected_display: str,
) -> None:
    """Resolve each standard format's default allocation in canonical balls.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :param format_code: Seeded match-format code.
    :param expected_balls: Expected canonical legal-ball allocation.
    :param expected_display: Expected format-aware allocation display.
    :return: None.
    """
    assign_core_match_format(service, core, format_code)

    # Null match overrides deliberately inherit the selected format definition.
    assert service.effective_innings_balls(core["match"]) == expected_balls
    match = next(
        row for row in service.list_matches() if row["id"] == core["match"]
    )
    assert match["effective_delivery_display"] == expected_display


def test_reduced_match_allocation_controls_innings_validation(
    service: CricketService, core: dict[str, int]
) -> None:
    """Apply a reduced T20 allocation and reject deliveries beyond it.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    assign_core_match_format(service, core, "T20")
    service.save_match(
        entity_id=core["match"],
        competition_id=core["competition"],
        match_date="2026-07-20",
        venue_id=core["venue"],
        home_team_id=core["home"],
        away_team_id=core["away"],
        scheduled_balls=120,
        revised_balls=90,
    )

    assert service.effective_innings_balls(core["match"]) == 90
    with pytest.raises(ValidationError, match="cannot exceed"):
        service.save_innings(
            match_id=core["match"],
            innings_number=1,
            batting_team_id=core["home"],
            bowling_team_id=core["away"],
            runs=80,
            wickets=3,
            balls=91,
            innings_status="in_progress",
        )


def test_revised_allocation_cannot_exceed_scheduled_allocation(
    service: CricketService, core: dict[str, int]
) -> None:
    """Reject a revised allocation that increases the scheduled match length.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    assign_core_match_format(service, core, "T20")

    # A reduced allocation may shorten but never lengthen the scheduled innings.
    with pytest.raises(ValidationError, match="cannot exceed"):
        service.save_match(
            entity_id=core["match"],
            competition_id=core["competition"],
            match_date="2026-07-20",
            venue_id=core["venue"],
            home_team_id=core["home"],
            away_team_id=core["away"],
            scheduled_balls=90,
            revised_balls=96,
        )


def test_all_out_status_requires_every_available_wicket(
    service: CricketService, core: dict[str, int]
) -> None:
    """Validate the wicket condition represented by an all-out status.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    with pytest.raises(ValidationError, match="every available wicket"):
        service.save_innings(
            match_id=core["match"],
            innings_number=1,
            batting_team_id=core["home"],
            bowling_team_id=core["away"],
            runs=95,
            wickets=9,
            balls=72,
            innings_status="all_out",
        )

    innings_id = service.save_innings(
        match_id=core["match"],
        innings_number=1,
        batting_team_id=core["home"],
        bowling_team_id=core["away"],
        runs=95,
        wickets=10,
        balls=72,
        innings_status="all_out",
    )
    # Terminal semantic statuses remain compatible with the legacy completion flag.
    assert service.repo.innings.get(innings_id)["completed"] == 1


def test_target_reached_status_validates_chasing_score(
    service: CricketService, core: dict[str, int]
) -> None:
    """Require the second innings to meet its explicitly recorded target.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    service.save_innings(
        match_id=core["match"],
        innings_number=1,
        batting_team_id=core["home"],
        bowling_team_id=core["away"],
        runs=149,
        wickets=6,
        balls=100,
        innings_status="innings_limit_reached",
    )
    with pytest.raises(ValidationError, match="meet or exceed"):
        service.save_innings(
            match_id=core["match"],
            innings_number=2,
            batting_team_id=core["away"],
            bowling_team_id=core["home"],
            runs=149,
            wickets=4,
            balls=87,
            target=150,
            innings_status="target_reached",
        )

    innings_id = service.save_innings(
        match_id=core["match"],
        innings_number=2,
        batting_team_id=core["away"],
        bowling_team_id=core["home"],
        runs=150,
        wickets=4,
        balls=88,
        target=150,
        innings_status="target_reached",
    )
    assert service.repo.innings.get(innings_id)["innings_status"] == "target_reached"


def test_innings_limit_status_requires_full_effective_allocation(
    service: CricketService, core: dict[str, int]
) -> None:
    """Require an innings-limit status to match the effective allocation.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    with pytest.raises(ValidationError, match="full allocation"):
        service.save_innings(
            match_id=core["match"],
            innings_number=1,
            batting_team_id=core["home"],
            bowling_team_id=core["away"],
            runs=120,
            wickets=5,
            balls=99,
            innings_status="innings_limit_reached",
        )


def test_t20_result_is_calculated_as_win_by_runs(
    service: CricketService, core: dict[str, int]
) -> None:
    """Calculate the representative T20 defence from completed innings.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    assign_core_match_format(service, core, "T20")
    service.save_innings(
        match_id=core["match"],
        innings_number=1,
        batting_team_id=core["home"],
        bowling_team_id=core["away"],
        runs=165,
        wickets=7,
        balls=120,
        innings_status="innings_limit_reached",
    )
    service.save_innings(
        match_id=core["match"],
        innings_number=2,
        batting_team_id=core["away"],
        bowling_team_id=core["home"],
        runs=151,
        wickets=9,
        balls=120,
        innings_status="innings_limit_reached",
    )

    # Completing the second innings stores the structured calculated outcome.
    result = service.repo.matches.get(core["match"])
    assert result["winning_team_id"] == core["home"]
    assert result["result_type"] == "Runs"
    assert result["result_margin_value"] == 14
    assert result["result_source"] == "Calculated"


def test_t20_result_is_calculated_as_win_by_wickets(
    service: CricketService, core: dict[str, int]
) -> None:
    """Calculate the representative successful T20 chase.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    assign_core_match_format(service, core, "T20")
    service.save_innings(
        match_id=core["match"],
        innings_number=1,
        batting_team_id=core["home"],
        bowling_team_id=core["away"],
        runs=165,
        wickets=7,
        balls=120,
        innings_status="innings_limit_reached",
    )
    service.save_innings(
        match_id=core["match"],
        innings_number=2,
        batting_team_id=core["away"],
        bowling_team_id=core["home"],
        runs=166,
        wickets=4,
        balls=111,
        innings_status="target_reached",
    )

    result = service.repo.matches.get(core["match"])
    assert result["winning_team_id"] == core["away"]
    assert result["result_type"] == "Wickets"
    assert result["result_margin_value"] == 6


def test_odi_equal_completed_scores_are_a_tie(
    service: CricketService, core: dict[str, int]
) -> None:
    """Calculate the representative tied ODI result.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    assign_core_match_format(service, core, "ODI")
    service.save_innings(
        match_id=core["match"],
        innings_number=1,
        batting_team_id=core["home"],
        bowling_team_id=core["away"],
        runs=275,
        wickets=8,
        balls=300,
        innings_status="innings_limit_reached",
    )
    service.save_innings(
        match_id=core["match"],
        innings_number=2,
        batting_team_id=core["away"],
        bowling_team_id=core["home"],
        runs=275,
        wickets=10,
        balls=299,
        innings_status="all_out",
    )

    result = service.repo.matches.get(core["match"])
    assert result["winning_team_id"] is None
    assert result["result_type"] == "Tie"
    assert service.result_description(result) == "Match tied"


def test_revised_target_drives_dls_wicket_result(
    service: CricketService, core: dict[str, int]
) -> None:
    """Use an authoritative revised target without calculating DLS.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    assign_core_match_format(service, core, "ODI")
    # The uninterrupted first innings is recorded before the chase is reduced.
    service.save_innings(
        match_id=core["match"],
        innings_number=1,
        batting_team_id=core["home"],
        bowling_team_id=core["away"],
        runs=250,
        wickets=8,
        balls=300,
        innings_status="innings_limit_reached",
    )
    service.save_match(
        entity_id=core["match"],
        competition_id=core["competition"],
        match_date="2026-07-20",
        venue_id=core["venue"],
        home_team_id=core["home"],
        away_team_id=core["away"],
        scheduled_balls=300,
        revised_balls=180,
        target_runs=251,
        revised_target_runs=180,
        result_method="DLS",
    )
    service.save_innings(
        match_id=core["match"],
        innings_number=2,
        batting_team_id=core["away"],
        bowling_team_id=core["home"],
        runs=181,
        wickets=5,
        balls=170,
        innings_status="target_reached",
    )

    result = service.repo.matches.get(core["match"])
    assert result["winning_team_id"] == core["away"]
    assert result["result_type"] == "Wickets"
    assert result["result_margin_value"] == 5
    assert result["result_method"] == "DLS"
    assert service.result_description(
        {**result, "winning_team_name": "Oval Invincibles Men"}
    ) == "Oval Invincibles Men won by 5 wickets using the DLS method"


@pytest.mark.parametrize(
    ("match_status", "result_type", "description"),
    [
        ("No Result", "No Result", "No result"),
        ("Abandoned", "Abandoned", "Match abandoned"),
    ],
)
def test_terminal_match_status_calculates_non_numeric_result(
    service: CricketService,
    core: dict[str, int],
    match_status: str,
    result_type: str,
    description: str,
) -> None:
    """Calculate an exceptional outcome without requiring innings summaries.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :param match_status: Terminal match status.
    :param result_type: Expected structured result type.
    :param description: Expected supporter-friendly description.
    :return: None.
    """
    service.save_match(
        entity_id=core["match"],
        competition_id=core["competition"],
        match_date="2026-07-20",
        venue_id=core["venue"],
        home_team_id=core["home"],
        away_team_id=core["away"],
        match_status=match_status,
    )

    result = service.repo.matches.get(core["match"])
    assert result["result_type"] == result_type
    assert result["result_source"] == "Calculated"
    assert service.result_description(result) == description
    # Placeholder innings must not invalidate an outcome determined by match status.
    service.save_innings(
        match_id=core["match"], innings_number=1, completed=False
    )
    assert service.repo.matches.get(core["match"])["result_type"] == result_type


def test_manual_super_over_winner_overrides_calculated_tie(
    service: CricketService, core: dict[str, int]
) -> None:
    """Retain a manual tie-break winner over the underlying calculated tie.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    service.save_innings(
        match_id=core["match"],
        innings_number=1,
        batting_team_id=core["home"],
        bowling_team_id=core["away"],
        runs=140,
        wickets=7,
        balls=100,
        completed=True,
    )
    service.save_innings(
        match_id=core["match"],
        innings_number=2,
        batting_team_id=core["away"],
        bowling_team_id=core["home"],
        runs=140,
        wickets=8,
        balls=100,
        completed=True,
    )
    service.save_match(
        entity_id=core["match"],
        competition_id=core["competition"],
        match_date="2026-07-20",
        venue_id=core["venue"],
        home_team_id=core["home"],
        away_team_id=core["away"],
        match_status="Completed",
        winning_team_id=core["home"],
        result_type="Tie",
        result_method="Super Over",
        result_source="Manual",
        result_override_reason="Official Super Over result.",
    )

    result = service.repo.matches.get(core["match"])
    assert result["result_source"] == "Manual"
    assert service.derive_match_result(core["match"])["result_type"] == "Tie"
    assert service.result_description(
        {**result, "winning_team_name": "London Spirit Men"}
    ) == "Match tied; London Spirit Men won the Super Over"


def test_abandonment_uses_its_own_ruleset_points(
    service: CricketService, core: dict[str, int]
) -> None:
    """Award abandonment points independently from no-result points.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    service.repo.rulesets.update(
        core["ruleset"],
        {"points_for_no_result": 1, "points_for_abandonment": 3},
    )
    service.save_match(
        entity_id=core["match"],
        competition_id=core["competition"],
        match_date="2026-07-20",
        venue_id=core["venue"],
        home_team_id=core["home"],
        away_team_id=core["away"],
        match_status="Abandoned",
    )

    # Both teams receive the competition's explicit abandonment allocation.
    table = calculate_standings(
        service.repo.connection, core["competition"]
    )
    assert all(row["points"] == 3 for row in table)
    assert all(row["no_result"] == 1 for row in table)


def test_tie_break_winner_receives_win_points_in_standings(
    service: CricketService, core: dict[str, int]
) -> None:
    """Treat an official Super Over winner as a win rather than a standing tie.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    service.save_innings(
        match_id=core["match"], innings_number=1,
        batting_team_id=core["home"], bowling_team_id=core["away"],
        runs=150, wickets=7, balls=100, completed=True,
    )
    service.save_innings(
        match_id=core["match"], innings_number=2,
        batting_team_id=core["away"], bowling_team_id=core["home"],
        runs=150, wickets=8, balls=100, completed=True,
    )
    service.save_match(
        entity_id=core["match"],
        competition_id=core["competition"],
        match_date="2026-07-20",
        venue_id=core["venue"],
        home_team_id=core["home"],
        away_team_id=core["away"],
        match_status="Completed",
        winning_team_id=core["home"],
        result_type="Tie",
        result_method="Super Over",
        result_source="Manual",
        result_override_reason="Official Super Over result.",
    )

    table = calculate_standings(
        service.repo.connection, core["competition"]
    )
    winner = next(row for row in table if row["team_id"] == core["home"])
    loser = next(row for row in table if row["team_id"] == core["away"])
    assert winner["won"] == 1 and winner["tied"] == 0
    assert loser["lost"] == 1 and loser["tied"] == 0
    assert winner["points"] == 4


def test_knockout_only_ruleset_has_no_standings(
    service: CricketService, core: dict[str, int]
) -> None:
    """Suppress standings for a competition whose ruleset opts out.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    service.repo.rulesets.update(core["ruleset"], {"has_standings": 0})

    # A knockout-only competition returns no rows instead of a misleading table.
    assert calculate_standings(
        service.repo.connection, core["competition"]
    ) == []


def test_t20_nrr_credits_an_all_out_team_with_full_allocation(
    service: CricketService, core: dict[str, int]
) -> None:
    """Use the T20 allocation for an early all-out NRR denominator.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    assign_core_match_format(service, core, "T20")
    # This test reuses the Hundred ruleset, so adopt the T20 six-ball rate unit.
    service.repo.rulesets.update(core["ruleset"], {"balls_per_rate_unit": 6})
    service.save_innings(
        match_id=core["match"], innings_number=1,
        batting_team_id=core["home"], bowling_team_id=core["away"],
        runs=120, wickets=10, balls=60, innings_status="all_out",
    )
    service.save_innings(
        match_id=core["match"], innings_number=2,
        batting_team_id=core["away"], bowling_team_id=core["home"],
        runs=121, wickets=0, balls=60, innings_status="target_reached",
    )

    table = calculate_standings(
        service.repo.connection, core["competition"]
    )
    home = next(row for row in table if row["team_id"] == core["home"])
    away = next(row for row in table if row["team_id"] == core["away"])
    # Home: 120 from credited 120 balls; away: 121 from 60 balls.
    assert home["net_run_rate"] == -6.1
    assert away["net_run_rate"] == 6.1


def test_revised_target_match_is_excluded_from_nrr(
    service: CricketService, core: dict[str, int]
) -> None:
    """Avoid presenting partial NRR for a revised-target match.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    assign_core_match_format(service, core, "T20")
    service.save_innings(
        match_id=core["match"], innings_number=1,
        batting_team_id=core["home"], bowling_team_id=core["away"],
        runs=160, wickets=6, balls=120,
        innings_status="innings_limit_reached",
    )
    service.save_match(
        entity_id=core["match"], competition_id=core["competition"],
        match_date="2026-07-20", venue_id=core["venue"],
        home_team_id=core["home"], away_team_id=core["away"],
        scheduled_balls=120, revised_balls=60,
        revised_target_runs=80, result_method="DLS",
    )
    service.save_innings(
        match_id=core["match"], innings_number=2,
        batting_team_id=core["away"], bowling_team_id=core["home"],
        runs=81, wickets=3, balls=55, innings_status="target_reached",
    )

    table = calculate_standings(
        service.repo.connection, core["competition"]
    )
    assert all(row["played"] == 1 for row in table)
    assert all(row["net_run_rate"] is None for row in table)
    assert "net_run_rate" not in table_to_csv(table).splitlines()[0]


def test_ruleset_restrictions_are_enforced_for_match_outcomes(
    service: CricketService, core: dict[str, int]
) -> None:
    """Reject revised targets and tie-break winners disabled by a ruleset.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    service.repo.rulesets.update(
        core["ruleset"],
        {
            "revised_targets_allowed": 0,
            "tie_break_winner_allowed": 0,
        },
    )
    with pytest.raises(ValidationError, match="revised targets"):
        service.save_match(
            entity_id=core["match"], competition_id=core["competition"],
            match_date="2026-07-20", venue_id=core["venue"],
            home_team_id=core["home"], away_team_id=core["away"],
            revised_target_runs=80, result_method="DLS",
        )
    with pytest.raises(ValidationError, match="tie-break winner"):
        service.save_match(
            entity_id=core["match"], competition_id=core["competition"],
            match_date="2026-07-20", venue_id=core["venue"],
            home_team_id=core["home"], away_team_id=core["away"],
            match_status="Completed", winning_team_id=core["home"],
            result_type="Tie", result_method="Super Over",
            result_source="Manual", result_override_reason="Official result.",
        )


def test_non_standing_tie_awaits_an_official_tie_break(
    service: CricketService, core: dict[str, int]
) -> None:
    """Withhold an official tied result when the ruleset requires a tie-break.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    service.repo.rulesets.update(core["ruleset"], {"ties_may_stand": 0})
    service.save_innings(
        match_id=core["match"], innings_number=1,
        batting_team_id=core["home"], bowling_team_id=core["away"],
        runs=130, wickets=7, balls=100, completed=True,
    )
    service.save_innings(
        match_id=core["match"], innings_number=2,
        batting_team_id=core["away"], bowling_team_id=core["home"],
        runs=130, wickets=8, balls=100, completed=True,
    )

    # The score fact remains calculable, but no official table result exists yet.
    assert service.derive_match_result(core["match"])["result_type"] == "Tie"
    assert service.repo.matches.get(core["match"])["result_type"] is None
    table = calculate_standings(
        service.repo.connection, core["competition"]
    )
    assert all(row["played"] == 0 for row in table)


def test_disabling_nrr_removes_it_from_ranking_and_export(
    service: CricketService,
) -> None:
    """Keep a disabled NRR criterion out of sort configuration and CSV output.

    :param service: Cricket service.
    :return: None.
    """
    match_format_id = next(
        row["id"] for row in service.list_match_formats() if row["code"] == "T20"
    )
    ruleset_id = service.save_ruleset(
        name="NRR-free T20",
        match_format_id=match_format_id,
        uses_net_run_rate=False,
        table_sort_order="points,net_run_rate,wins",
    )

    ruleset = service.repo.rulesets.get(ruleset_id)
    assert ruleset["uses_net_run_rate"] == 0
    assert ruleset["table_sort_order"] == "points,wins"
    assert table_to_csv(
        [{"team": "Example", "played": 0, "points": 0, "net_run_rate": None}]
    ).splitlines()[0] == "team,played,won,lost,tied,no_result,points"


@pytest.mark.parametrize(
    ("legal_balls", "limit_unit", "balls_per_over"),
    [
        (-1, "balls", None),
        (12, "sessions", None),
        (12, "overs", None),
        (12, "overs", 0),
    ],
)
def test_format_delivery_count_rejects_invalid_values(
    legal_balls: int, limit_unit: str, balls_per_over: int | None
) -> None:
    """Reject invalid delivery counts and format configuration.

    :param legal_balls: Candidate delivery count.
    :param limit_unit: Candidate limit unit.
    :param balls_per_over: Candidate over size.
    :return: None.
    """
    # Invalid format metadata must fail early instead of producing misleading output.
    with pytest.raises(ValueError):
        format_delivery_count(
            legal_balls,
            limit_unit=limit_unit,
            balls_per_over=balls_per_over,
        )


def test_match_validation(service: CricketService, core: dict[str, int]) -> None:
    """Reject invalid teams and completed results.

    :param service: Cricket service.
    :param core: Core identifiers.
    :return: None.
    """
    with pytest.raises(ValidationError, match="cannot play itself"):
        service.save_match(
            competition_id=core["competition"], match_date="2026-07-21",
            home_team_id=core["home"], away_team_id=core["home"],
        )
    with pytest.raises(ValidationError, match="two innings"):
        service.save_match(
            entity_id=core["match"], competition_id=core["competition"],
            match_date="2026-07-20", venue_id=core["venue"],
            home_team_id=core["home"], away_team_id=core["away"],
            match_stage="League", match_status="Completed",
            winning_team_id=core["home"], result_type="Runs",
            result_margin_value=1,
        )


def test_completed_match_and_standings(
    service: CricketService, core: dict[str, int]
) -> None:
    """Calculate points and NRR from innings summaries.

    :param service: Cricket service.
    :param core: Core identifiers.
    :return: None.
    """
    complete_match(service, core)
    table = calculate_standings(service.repo.connection, core["competition"])
    assert table[0]["team"] == "London Spirit Men"
    assert table[0]["won"] == 1
    assert table[0]["points"] == 4
    assert table[0]["net_run_rate"] == 0.65
    assert table[1]["lost"] == 1


def test_league_table_csv_contains_displayed_rows(
    service: CricketService, core: dict[str, int]
) -> None:
    """Serialise the currently calculated league table display columns.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    complete_match(service, core)
    table = calculate_standings(service.repo.connection, core["competition"])

    # The download uses the same calculated rows rather than issuing another query.
    rows = list(csv.DictReader(io.StringIO(table_to_csv(table))))

    assert [row["team"] for row in rows] == [
        "London Spirit Men",
        "Oval Invincibles Men",
    ]
    assert rows[0]["points"] == "4"
    assert list(rows[0]) == [
        "team", "played", "won", "lost", "tied", "no_result",
        "points", "net_run_rate",
    ]


def test_combined_gender_table_sums_franchises_and_recalculates_nrr(
    service: CricketService, core: dict[str, int]
) -> None:
    """Combine paired gender tables by shared franchise name.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    # Rename the fixture teams to gender-neutral franchise identities.
    service.repo.connection.execute(
        "UPDATE teams SET name = 'Franchise A' WHERE id = ?", (core["home"],)
    )
    service.repo.connection.execute(
        "UPDATE teams SET name = 'Franchise B' WHERE id = ?", (core["away"],)
    )
    complete_match(service, core)
    women_home = service.save_team(
        name="Franchise A", country_id=core["country"], gender="Women",
        home_venue_id=core["venue"],
    )
    women_away = service.save_team(
        name="Franchise B", country_id=core["country"], gender="Women",
        home_venue_id=core["venue"],
    )
    women_competition = service.save_competition(
        name="Women's Competition", season="2026", ruleset_id=core["ruleset"],
        gender="Women", format="The Hundred", country_id=core["country"],
    )
    women_match = service.save_match(
        competition_id=women_competition, match_date="2026-07-21",
        venue_id=core["venue"], home_team_id=women_home,
        away_team_id=women_away, match_stage="League",
        match_status="Scheduled",
    )
    service.save_innings(
        match_id=women_match, innings_number=1, batting_team_id=women_home,
        bowling_team_id=women_away, runs=137, wickets=6, balls=100,
        completed=True,
    )
    service.save_innings(
        match_id=women_match, innings_number=2, batting_team_id=women_away,
        bowling_team_id=women_home, runs=138, wickets=6, balls=100,
        completed=True,
    )

    combined = calculate_combined_standings(
        service.repo.connection,
        core["competition"],
    )

    assert set(combined_competition_ids(
        service.repo.connection, core["competition"]
    )) == {core["competition"], women_competition}
    assert [row["team"] for row in combined] == ["Franchise A", "Franchise B"]
    assert all(row["played"] == 2 for row in combined)
    assert all(row["won"] == 1 and row["lost"] == 1 for row in combined)
    assert all(row["points"] == 4 for row in combined)
    assert combined[0]["net_run_rate"] == 0.3
    assert combined[1]["net_run_rate"] == -0.3


def test_csv_exports_separate_matches_and_innings(
    service: CricketService, core: dict[str, int]
) -> None:
    """Ensure supported datasets have stable headers.

    :param service: Cricket service.
    :param core: Core identifiers.
    :return: None.
    """
    complete_match(service, core)
    match_export = export_csv(service.repo.connection, "matches")
    assert "home_team,away_team" in match_export
    assert "notes" not in match_export.splitlines()[0].split(",")
    assert "innings_number,batting_team,bowling_team" in export_csv(
        service.repo.connection, "innings"
    )
    innings_header = export_csv(
        service.repo.connection, "innings"
    ).splitlines()[0].split(",")
    assert "notes" not in innings_header
    assert "innings_status" in innings_header
    match_header = match_export.splitlines()[0].split(",")
    assert {
        "scheduled_balls", "revised_balls", "target_runs", "revised_target_runs",
    } <= set(match_header)
    assert set(DATASETS) >= {"matches", "innings"}


def import_dataset_folder(
    service: CricketService, folder: Path
) -> dict[str, object]:
    """Import one self-contained CSV folder in dependency order.

    :param service: Cricket service.
    :param folder: Folder containing the supported dataset files.
    :return: Import results keyed by dataset name.
    """
    order = (
        "countries", "venues", "teams", "competition_rulesets",
        "competitions", "matches", "innings",
    )
    results: dict[str, object] = {}
    for dataset in order:
        # Every sample follows the same order users can apply through the CLI.
        results[dataset] = CricketImporter(
            service.repo.connection
        ).import_csv(dataset, (folder / f"{dataset}.csv").read_bytes())
    return results


@pytest.mark.parametrize(
    ("folder_name", "format_code", "result_type", "result_method"),
    [
        ("T20-EXAMPLE-2026", "T20", "Runs", "Standard"),
        ("ODI-EXAMPLE-2026", "ODI", "Wickets", "DLS"),
    ],
)
def test_limited_overs_sample_dataset_imports_end_to_end(
    service: CricketService,
    folder_name: str,
    format_code: str,
    result_type: str,
    result_method: str,
) -> None:
    """Import a sample competition and calculate its expected result.

    :param service: Cricket service.
    :param folder_name: Sample dataset folder.
    :param format_code: Expected match-format code.
    :param result_type: Expected calculated result type.
    :param result_method: Expected calculated result method.
    :return: None.
    """
    folder = Path(__file__).parents[1] / "data" / "samples" / folder_name
    results = import_dataset_folder(service, folder)

    assert all(not result.errors for result in results.values())
    competition = service.list_competitions()[0]
    match = service.list_matches(int(competition["id"]))[0]
    assert competition["match_format_code"] == format_code
    assert match["result_type"] == result_type
    assert match["result_method"] == result_method
    assert len(service.list_innings(int(match["id"]))) == 2


def test_updated_hundred_import_folders_remain_compatible(
    service: CricketService,
) -> None:
    """Import both maintained Hundred datasets with their extended schemas.

    :param service: Cricket service.
    :return: None.
    """
    imports_root = Path(__file__).parents[1] / "data" / "imports"
    all_results = []
    for folder_name in ("HUNDRED-MEN-2026", "HUNDRED-WOMEN-2026"):
        # Shared reference rows may skip on the second folder, but none may fail.
        all_results.extend(
            import_dataset_folder(
                service, imports_root / folder_name
            ).values()
        )

    assert all(not result.errors for result in all_results)
    assert len(service.list_competitions()) == 2


def test_csv_exports_can_be_filtered_by_competition(
    service: CricketService, core: dict[str, int]
) -> None:
    """Restrict every export dataset to rows related to one competition.

    :param service: Cricket service.
    :param core: Core identifiers.
    :return: None.
    """
    complete_match(service, core)
    other_home = service.save_team(
        name="Manchester Originals Men", country_id=core["country"],
        gender="Men", home_venue_id=core["venue"],
    )
    other_away = service.save_team(
        name="Northern Superchargers Men", country_id=core["country"],
        gender="Men", home_venue_id=core["venue"],
    )
    other_competition = service.save_competition(
        name="Other Competition", season="2026", ruleset_id=core["ruleset"],
        gender="Men", format="The Hundred", country_id=core["country"],
    )
    service.save_match(
        competition_id=other_competition, match_date="2026-07-21",
        venue_id=core["venue"], home_team_id=other_home,
        away_team_id=other_away, match_stage="League",
        match_status="Scheduled",
    )

    # Parse the CSV output so assertions check row scope rather than incidental text.
    matches = list(
        csv.DictReader(
            io.StringIO(
                export_csv(
                    service.repo.connection, "matches", core["competition"]
                )
            )
        )
    )
    teams = list(
        csv.DictReader(
            io.StringIO(
                export_csv(service.repo.connection, "teams", core["competition"])
            )
        )
    )
    competitions = list(
        csv.DictReader(
            io.StringIO(
                export_csv(
                    service.repo.connection, "competitions", core["competition"]
                )
            )
        )
    )

    assert len(matches) == 1
    assert matches[0]["home_team"] == "London Spirit Men"
    assert {row["name"] for row in teams} == {
        "London Spirit Men", "Oval Invincibles Men",
    }
    assert [row["name"] for row in competitions] == [
        "The Hundred Men's Competition"
    ]


def test_csv_export_rejects_unknown_competition(
    service: CricketService,
) -> None:
    """Reject an invalid competition filter instead of returning an empty export.

    :param service: Cricket service.
    :return: None.
    """
    # A clear error helps callers distinguish invalid input from a valid empty dataset.
    with pytest.raises(ValueError, match="No competition exists"):
        export_csv(service.repo.connection, "matches", 999_999)


def test_ui_save_commits_before_requesting_rerun(
    service: CricketService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Commit an editor mutation before Streamlit interrupts the current run.

    :param service: Cricket service.
    :param monkeypatch: Pytest attribute patching helper.
    :return: None.
    """
    session_state: dict[str, str] = {}
    monkeypatch.setattr(tracker_app.st, "session_state", session_state)

    def interrupt_rerun() -> None:
        """Represent Streamlit ending the current script for a UI refresh.

        :return: None.
        """
        # Streamlit's rerun control flow prevents code after the helper from executing.
        raise RuntimeError("rerun")

    monkeypatch.setattr(tracker_app.st, "rerun", interrupt_rerun)
    with pytest.raises(RuntimeError, match="rerun"):
        tracker_app._save(
            lambda: service.save_country(name="Committed Country", code="CC"),
            "Country saved.",
            service.repo.connection,
        )

    # The transaction has already ended successfully despite the rerun interruption.
    assert service.repo.connection.in_transaction is False
    assert session_state["_pending_success"] == "Country saved."
    assert any(
        row["name"] == "Committed Country" for row in service.list_countries()
    )


def test_ui_save_is_blocked_in_read_only_mode(
    service: CricketService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Do not execute a mutation when a browse-only UI action is received."""
    errors: list[str] = []
    action_called = False

    def action() -> None:
        nonlocal action_called
        action_called = True

    monkeypatch.setattr(tracker_app.st, "error", errors.append)
    tracker_app._save(
        action,
        "Country saved.",
        service.repo.connection,
        read_only=True,
    )

    assert action_called is False
    assert errors == ["This application is browse only; changes cannot be saved."]


def test_request_host_enables_read_only_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the public forwarded host to recognise a configured hosted domain."""
    context = type(
        "Context",
        (),
        {"headers": {"Host": "internal:8501", "X-Forwarded-Host": "demo.streamlit.app"}},
    )()
    monkeypatch.setattr(tracker_app.st, "context", context)

    assert tracker_app._is_read_only_request() is True


def test_pending_success_is_displayed_after_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Display a queued confirmation once on the refreshed page.

    :param monkeypatch: Pytest attribute patching helper.
    :return: None.
    """
    session_state = {"_pending_success": "Innings saved."}
    displayed: list[str] = []
    monkeypatch.setattr(tracker_app.st, "session_state", session_state)
    monkeypatch.setattr(tracker_app.st, "success", displayed.append)

    # Consuming the message prevents it reappearing after unrelated interactions.
    tracker_app._show_pending_success()

    assert displayed == ["Innings saved."]
    assert "_pending_success" not in session_state


def test_export_dataset_change_resets_custom_file_stem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replace a custom export stem whenever the dataset changes.

    :param monkeypatch: Pytest attribute patching helper.
    :return: None.
    """
    session_state = {
        "export": "innings",
        "export_file_stem": "my-custom-name",
    }
    monkeypatch.setattr(tracker_app.st, "session_state", session_state)

    # The callback always follows the current dataset, irrespective of prior user input.
    tracker_app._reset_export_file_stem()

    assert session_state["export_file_stem"] == "innings"


def test_csv_validation_reports_unknown_references(connection: sqlite3.Connection) -> None:
    """Return a clear row error for missing references.

    :param connection: Open database connection.
    :return: None.
    """
    result = CricketImporter(connection).import_csv(
        "venues", "name,city,country\nSomewhere,London,Unknown\n"
    )
    assert result.imported == 0
    assert result.skipped == 1
    assert "Unknown country" in result.errors[0]


def test_country_csv_reimport_skips_existing_record(
    connection: sqlite3.Connection,
) -> None:
    """Treat repeated country imports as skipped records.

    :param connection: Open database connection.
    :return: None.
    """
    importer = CricketImporter(connection)
    content = "name,code\nEngland,ENG\n"
    first = importer.import_csv("countries", content)
    second = importer.import_csv("countries", content)

    assert first.imported == 1
    assert second.imported == 0
    assert second.skipped == 1
    assert second.errors == []
    assert connection.execute("SELECT COUNT(*) FROM countries").fetchone()[0] == 1


def test_all_csv_reimports_skip_existing_records(
    service: CricketService, core: dict[str, int]
) -> None:
    """Skip existing natural keys across every supported dataset.

    :param service: Cricket service.
    :param core: Core identifiers.
    :return: None.
    """
    complete_match(service, core)
    importer = CricketImporter(service.repo.connection)

    for dataset in DATASETS:
        content = export_csv(service.repo.connection, dataset)
        expected_rows = max(len(content.splitlines()) - 1, 0)
        result = importer.import_csv(dataset, content)

        assert result.imported == 0, dataset
        assert result.skipped == expected_rows, dataset
        assert result.errors == [], dataset


def test_team_identity_uses_name_and_gender(
    service: CricketService, core: dict[str, int]
) -> None:
    """Allow equal team names across genders and skip only an equal pair.

    :param service: Cricket service.
    :param core: Core identifiers.
    :return: None.
    """
    importer = CricketImporter(service.repo.connection)
    content = (
        "name,country,gender,home_venue\n"
        "Manchester Originals,England,Men,Lord's\n"
        "Manchester Originals,England,Women,Lord's\n"
        "Manchester Originals,England,Men,Lord's\n"
    )

    result = importer.import_csv("teams", content)

    assert result.imported == 2
    assert result.skipped == 1
    assert result.errors == []
    rows = service.repo.connection.execute(
        """
        SELECT name, gender FROM teams
        WHERE name = ? COLLATE NOCASE
        ORDER BY gender
        """,
        ("Manchester Originals",),
    ).fetchall()
    assert [(row["name"], row["gender"]) for row in rows] == [
        ("Manchester Originals", "Men"),
        ("Manchester Originals", "Women"),
    ]


def test_match_form_team_options_preserve_duplicate_gendered_names(
    service: CricketService, core: dict[str, int]
) -> None:
    """Keep both team identifiers available when their names are identical.

    :param service: Cricket service.
    :param core: Core identifiers.
    :return: None.
    """
    duplicate = service.save_team(
        name="London Spirit Men", country_id=core["country"],
        gender="Women", home_venue_id=core["venue"],
    )

    # Gender-qualified labels prevent one dictionary entry replacing the other.
    options = tracker_app._team_options(service.list_teams())
    assert options["London Spirit Men — Men"] == core["home"]
    assert options["London Spirit Men — Women"] == duplicate


def test_match_competition_change_clears_editor_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reset selected-row and record-specific state after changing competition.

    :param monkeypatch: Pytest attribute patching helper.
    :return: None.
    """
    session_state = {
        "match_workspace_competition": "New competition",
        "match_workspace_match_id": 10,
        "match_editor_generation": 2,
        "match_editor_new": True,
        "match_date_10": "2026-07-20",
        "match_winner_10": "Old winner",
        "match_calculated_result_10": "Runs",
        "main_navigation": "Matches",
    }
    monkeypatch.setattr(tracker_app.st, "session_state", session_state)

    # The callback must preserve global navigation and the newly chosen competition.
    tracker_app._reset_match_tab()

    assert session_state["match_workspace_competition"] == "New competition"
    assert session_state["match_workspace_match_id"] is None
    assert session_state["match_editor_generation"] == 3
    assert session_state["match_editor_new"] is False
    assert session_state["main_navigation"] == "Matches"
    assert "match_date_10" not in session_state
    assert "match_winner_10" not in session_state
    assert "match_calculated_result_10" not in session_state


def test_innings_match_selector_updates_shared_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish an innings dropdown choice for the matches table and form.

    :param monkeypatch: Pytest attribute patching helper.
    :return: None.
    """
    session_state = {
        "innings_match_widget": "Match B",
        "match_workspace_match_id": 1,
        "match_editor_generation": 4,
        "match_editor_new": True,
    }
    monkeypatch.setattr(tracker_app.st, "session_state", session_state)

    # Synchronising also resets any stale dataframe row selection.
    tracker_app._sync_workspace_match(
        {"Match A": 1, "Match B": 2},
        "innings_match_widget",
    )

    assert session_state["match_workspace_match_id"] == 2
    assert session_state["match_editor_generation"] == 5
    assert session_state["match_editor_new"] is False


def test_match_checkbox_selection_prefers_new_row() -> None:
    """Resolve a newly checked match when the prior row is still checked.

    :return: None.
    """
    # Data editors briefly return both values while changing a checkbox selection.
    assert tracker_app._choose_match_selection([10, 11], 10) == 11
    assert tracker_app._choose_match_selection([11], 11) == 11
    assert tracker_app._choose_match_selection([], 11) is None


def test_match_team_cells_are_styled_by_result() -> None:
    """Colour winner, loser, and neutral team cells from match outcomes.

    :return: None.
    """
    rows = [
        {
            "home_team_id": 1, "away_team_id": 2, "winning_team_id": 1,
            "result_type": "Runs", "match_status": "Completed",
        },
        {
            "home_team_id": 3, "away_team_id": 4, "winning_team_id": None,
            "result_type": "Tie", "match_status": "Completed",
        },
        {
            "home_team_id": 5, "away_team_id": 6, "winning_team_id": None,
            "result_type": "Abandoned", "match_status": "Abandoned",
        },
    ]
    frame = pd.DataFrame(
        {
            "Selected": [False, False, False],
            "Home team": ["Home A", "Home B", "Home C"],
            "Away team": ["Away A", "Away B", "Away C"],
        }
    )

    # Only team-name cells receive outcome colours.
    styles = tracker_app._match_team_cell_styles(rows, frame)

    assert styles.at[0, "Home team"] == "background-color: #dff2e1"
    assert styles.at[0, "Away team"] == "background-color: #f8dddd"
    assert styles.at[1, "Home team"] == "background-color: #fff3cd"
    assert styles.at[1, "Away team"] == "background-color: #fff3cd"
    assert styles.at[2, "Home team"] == "background-color: #fff3cd"
    assert styles.at[2, "Away team"] == "background-color: #fff3cd"
    assert styles.at[0, "Selected"] == ""


def test_innings_view_uses_persistent_tab_selection(
    service: CricketService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the innings editor active during table-selection reruns.

    :param service: Cricket service.
    :param monkeypatch: Pytest attribute patching helper.
    :return: None.
    """
    rendered: list[str] = []
    radio_arguments: dict[str, object] = {}
    monkeypatch.setattr(tracker_app.st, "header", lambda _label: None)

    def select_innings(*_args: object, **kwargs: object) -> str:
        """Return the persisted innings selection and capture its widget key.

        :param _args: Positional radio arguments.
        :param kwargs: Keyword radio arguments.
        :return: Selected innings view label.
        """
        # A stable key is what lets Streamlit restore the selection after rerunning.
        radio_arguments.update(kwargs)
        return "Innings"

    monkeypatch.setattr(tracker_app.st, "radio", select_innings)
    monkeypatch.setattr(
        tracker_app,
        "_match_editor_tab",
        lambda _service, _read_only=False: rendered.append("Matches"),
    )
    monkeypatch.setattr(
        tracker_app,
        "_innings_editor_tab",
        lambda _service, _read_only=False: rendered.append("Innings"),
    )

    tracker_app._matches(service)

    assert radio_arguments["key"] == "matches_active_tab"
    assert rendered == ["Innings"]


def test_innings_import_uses_competition_date_and_gender(
    service: CricketService, core: dict[str, int]
) -> None:
    """Resolve an innings match and teams using their intended natural keys.

    :param service: Cricket service.
    :param core: Core identifiers.
    :return: None.
    """
    # Equal women's names prove that the competition's men's gender is needed
    # to resolve the two team references unambiguously.
    service.save_team(
        name="London Spirit Men",
        country_id=core["country"],
        gender="Women",
        home_venue_id=core["venue"],
    )
    service.save_team(
        name="Oval Invincibles Men",
        country_id=core["country"],
        gender="Women",
        home_venue_id=core["venue"],
    )
    content = (
        "competition,season,match_date,home_team,away_team,innings_number,"
        "batting_team,bowling_team,runs,wickets,balls,extras,target,completed\n"
        "The Hundred Men's Competition,2026,2026-07-20,,,1,"
        "London Spirit Men,Oval Invincibles Men,150,6,100,,,1\n"
    )

    result = CricketImporter(service.repo.connection).import_csv(
        "innings", content
    )

    assert result.imported == 1
    assert result.skipped == 0
    assert result.errors == []
    innings = service.repo.connection.execute(
        "SELECT * FROM innings"
    ).fetchone()
    assert innings["match_id"] == core["match"]
    assert innings["batting_team_id"] == core["home"]
    assert innings["bowling_team_id"] == core["away"]


def test_planned_innings_import_allows_blank_details(
    service: CricketService, core: dict[str, int]
) -> None:
    """Import a future innings with only its match and innings number.

    :param service: Cricket service.
    :param core: Core identifiers.
    :return: None.
    """
    content = (
        "competition,season,match_date,home_team,away_team,innings_number,"
        "batting_team,bowling_team,runs,wickets,balls,extras,target,completed\n"
        "The Hundred Men's Competition,2026,2026-07-20,"
        "London Spirit Men,Oval Invincibles Men,1,,,,,,,,False\n"
    )

    result = CricketImporter(service.repo.connection).import_csv(
        "innings", content
    )

    assert result.imported == 1
    assert result.skipped == 0
    assert result.errors == []
    innings = service.repo.connection.execute(
        "SELECT * FROM innings"
    ).fetchone()
    assert innings["match_id"] == core["match"]
    assert innings["batting_team_id"] is None
    assert innings["bowling_team_id"] is None
    assert innings["runs"] is None
    assert innings["wickets"] is None
    assert innings["balls"] is None
    assert innings["completed"] == 0
    assert innings["innings_status"] == "not_started"


def test_completed_match_result_is_derived_from_innings(
    service: CricketService, core: dict[str, int]
) -> None:
    """Store a calculated run result when a match becomes complete.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    # A completed defence supplies all facts needed for a run-margin result.
    service.save_innings(
        match_id=core["match"], innings_number=1, batting_team_id=core["home"],
        bowling_team_id=core["away"], runs=150, wickets=6, balls=100,
        completed=True,
    )
    service.save_innings(
        match_id=core["match"], innings_number=2, batting_team_id=core["away"],
        bowling_team_id=core["home"], runs=137, wickets=8, balls=100,
        completed=True,
    )
    service.save_match(
        entity_id=core["match"], competition_id=core["competition"],
        match_date="2026-07-20", venue_id=core["venue"],
        home_team_id=core["home"], away_team_id=core["away"],
        match_stage="League", match_status="Completed",
    )

    match = service.repo.matches.get(core["match"])
    assert match["winning_team_id"] == core["home"]
    assert match["result_type"] == "Runs"
    assert match["result_margin_value"] == 13
    assert match["result_source"] == "Calculated"
    assert match["result_method"] == "Standard"


def test_completing_both_innings_updates_match_result_immediately(
    service: CricketService, core: dict[str, int]
) -> None:
    """Complete an ordinary match and calculate its result from the innings editor.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    # The fixture begins scheduled and should not require a separate match-form save.
    service.save_innings(
        match_id=core["match"], innings_number=1, batting_team_id=core["home"],
        bowling_team_id=core["away"], runs=165, wickets=5, balls=100,
        completed=True,
    )
    service.save_innings(
        match_id=core["match"], innings_number=2, batting_team_id=core["away"],
        bowling_team_id=core["home"], runs=160, wickets=9, balls=100,
        completed=True,
    )

    match = service.repo.matches.get(core["match"])
    assert match["match_status"] == "Completed"
    assert match["winning_team_id"] == core["home"]
    assert match["result_type"] == "Runs"
    assert match["result_margin_value"] == 5
    assert match["result_source"] == "Calculated"
    # The match editor's enriched row must expose the generated winner label.
    displayed_match = next(
        row for row in service.list_matches() if row["id"] == core["match"]
    )
    assert displayed_match["winning_team_name"] == "London Spirit Men"


def test_one_completed_innings_does_not_complete_match(
    service: CricketService, core: dict[str, int]
) -> None:
    """Keep a match unresolved until both expected innings are complete.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    # One completed innings is insufficient evidence of a completed match.
    service.save_innings(
        match_id=core["match"], innings_number=1, batting_team_id=core["home"],
        bowling_team_id=core["away"], runs=165, wickets=5, balls=100,
        completed=True,
    )

    match = service.repo.matches.get(core["match"])
    assert match["match_status"] == "Scheduled"
    assert match["result_type"] is None


def test_uncompleting_innings_clears_calculated_result(
    service: CricketService, core: dict[str, int]
) -> None:
    """Clear generated match fields when an innings is explicitly uncompleted.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    service.save_innings(
        match_id=core["match"], innings_number=1, batting_team_id=core["home"],
        bowling_team_id=core["away"], runs=165, wickets=5, balls=100,
        completed=True,
    )
    second_id = service.save_innings(
        match_id=core["match"], innings_number=2, batting_team_id=core["away"],
        bowling_team_id=core["home"], runs=160, wickets=9, balls=100,
        completed=True,
    )
    assert service.repo.matches.get(core["match"])["result_type"] == "Runs"

    # Even a full ball allocation is no longer conclusive after an explicit uncomplete.
    service.save_innings(
        entity_id=second_id, match_id=core["match"], innings_number=2,
        batting_team_id=core["away"], bowling_team_id=core["home"],
        runs=160, wickets=9, balls=100, completed=False,
    )

    match = service.repo.matches.get(core["match"])
    assert match["match_status"] == "In Progress"
    assert match["winning_team_id"] is None
    assert match["result_type"] is None
    assert match["result_margin_value"] is None
    assert match["result_source"] is None


def test_successful_chase_is_derived_before_completed_flag(
    service: CricketService, core: dict[str, int]
) -> None:
    """Recognise a reached target even when the chase is not explicitly complete.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    # Reaching the target conclusively ends an otherwise unmarked second innings.
    service.save_innings(
        match_id=core["match"], innings_number=1, batting_team_id=core["home"],
        bowling_team_id=core["away"], runs=157, wickets=7, balls=100,
        completed=True,
    )
    service.save_innings(
        match_id=core["match"], innings_number=2, batting_team_id=core["away"],
        bowling_team_id=core["home"], runs=158, wickets=6, balls=94,
        completed=False,
    )
    service.save_match(
        entity_id=core["match"], competition_id=core["competition"],
        match_date="2026-07-20", venue_id=core["venue"],
        home_team_id=core["home"], away_team_id=core["away"],
        match_stage="League", match_status="Completed",
    )

    match = service.repo.matches.get(core["match"])
    assert match["winning_team_id"] == core["away"]
    assert match["result_type"] == "Wickets"
    assert match["result_margin_value"] == 4


def test_incomplete_chase_does_not_create_result(
    service: CricketService, core: dict[str, int]
) -> None:
    """Leave result fields empty while the chasing innings can continue.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    # A lower partial score is not evidence that the first batting side won.
    service.save_innings(
        match_id=core["match"], innings_number=1, batting_team_id=core["home"],
        bowling_team_id=core["away"], runs=157, wickets=7, balls=100,
        completed=True,
    )
    service.save_innings(
        match_id=core["match"], innings_number=2, batting_team_id=core["away"],
        bowling_team_id=core["home"], runs=120, wickets=3, balls=72,
        completed=False,
    )
    service.save_match(
        entity_id=core["match"], competition_id=core["competition"],
        match_date="2026-07-20", venue_id=core["venue"],
        home_team_id=core["home"], away_team_id=core["away"],
        match_stage="League", match_status="Completed",
    )

    match = service.repo.matches.get(core["match"])
    assert match["result_type"] is None
    assert match["result_source"] is None


def test_abandoned_match_override_does_not_require_innings(
    service: CricketService, core: dict[str, int]
) -> None:
    """Save an official abandoned result when no innings data exists.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    # Exceptional outcomes use an explained manual override instead of calculation.
    service.save_match(
        entity_id=core["match"], competition_id=core["competition"],
        match_date="2026-07-20", venue_id=core["venue"],
        home_team_id=core["home"], away_team_id=core["away"],
        match_stage="League", match_status="Abandoned",
        result_type="Abandoned", result_method="Other",
        result_source="Manual",
        result_override_reason="Match abandoned without a ball bowled.",
    )

    match = service.repo.matches.get(core["match"])
    assert match["match_status"] == "Abandoned"
    assert match["winning_team_id"] is None
    assert match["result_type"] == "Abandoned"
    assert match["result_source"] == "Manual"
    assert service.list_innings(core["match"]) == []


def test_abandoned_result_is_credited_when_status_was_scheduled(
    service: CricketService, core: dict[str, int]
) -> None:
    """Synchronise and credit an abandoned result entered on a scheduled fixture.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    # Placeholder innings may exist for the scheduled fixture without usable score data.
    service.save_innings(match_id=core["match"], innings_number=1, completed=False)
    service.save_innings(match_id=core["match"], innings_number=2, completed=False)
    # Selecting the official result is sufficient; users need not duplicate its status.
    service.save_match(
        entity_id=core["match"], competition_id=core["competition"],
        match_date="2026-07-20", venue_id=core["venue"],
        home_team_id=core["home"], away_team_id=core["away"],
        match_stage="League", match_status="Scheduled",
        result_type="Abandoned", result_method="Other",
        result_source="Manual",
        result_override_reason="Match abandoned without a ball bowled.",
    )

    match = service.repo.matches.get(core["match"])
    table = calculate_standings(service.repo.connection, core["competition"])
    assert match["match_status"] == "Abandoned"
    assert all(row["played"] == 1 for row in table)
    assert all(row["no_result"] == 1 for row in table)
    assert all(row["points"] == 2 for row in table)
    assert all(row["net_run_rate"] is None for row in table)


def test_innings_edit_recalculates_result_but_preserves_manual_override(
    service: CricketService, core: dict[str, int]
) -> None:
    """Refresh calculated summaries and retain an explicit official override.

    :param service: Cricket service.
    :param core: Core fixture identifiers.
    :return: None.
    """
    service.save_innings(
        match_id=core["match"], innings_number=1, batting_team_id=core["home"],
        bowling_team_id=core["away"], runs=100, wickets=8, balls=100,
        completed=True,
    )
    second_id = service.save_innings(
        match_id=core["match"], innings_number=2, batting_team_id=core["away"],
        bowling_team_id=core["home"], runs=100, wickets=9, balls=100,
        completed=True,
    )
    service.save_match(
        entity_id=core["match"], competition_id=core["competition"],
        match_date="2026-07-20", venue_id=core["venue"],
        home_team_id=core["home"], away_team_id=core["away"],
        match_stage="League", match_status="Completed",
    )
    assert service.repo.matches.get(core["match"])["result_type"] == "Tie"

    # Correcting the chase immediately replaces the generated tie with a wicket result.
    service.save_innings(
        entity_id=second_id, match_id=core["match"], innings_number=2,
        batting_team_id=core["away"], bowling_team_id=core["home"],
        runs=101, wickets=9, balls=100, completed=True,
    )
    assert service.repo.matches.get(core["match"])["result_type"] == "Wickets"

    # An official tie-break outcome remains stored through later innings corrections.
    service.save_match(
        entity_id=core["match"], competition_id=core["competition"],
        match_date="2026-07-20", venue_id=core["venue"],
        home_team_id=core["home"], away_team_id=core["away"],
        match_stage="League", match_status="Completed",
        winning_team_id=core["home"], result_type="Wickets",
        result_margin_value=1, result_margin_type="Wickets",
        result_method="Super Over", result_source="Manual",
        result_override_reason="Official Super Over result.",
        _defer_completion_validation=True,
    )
    service.save_innings(
        entity_id=second_id, match_id=core["match"], innings_number=2,
        batting_team_id=core["away"], bowling_team_id=core["home"],
        runs=99, wickets=9, balls=100, completed=True,
    )
    match = service.repo.matches.get(core["match"])
    assert match["winning_team_id"] == core["home"]
    assert match["result_method"] == "Super Over"
    assert service.derive_match_result(core["match"])["result_type"] == "Runs"
