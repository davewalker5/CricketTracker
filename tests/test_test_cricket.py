"""Test cricket format, innings sequencing, and result scenarios."""

from __future__ import annotations

import pytest

from cricket_tracker.services import CricketService, ValidationError


@pytest.fixture
def test_match(service: CricketService) -> dict[str, int]:
    """Create a standard five-day Test fixture."""
    country = service.save_country(name="Testland", code="TST")
    venue = service.save_venue(name="Test Ground", country_id=country)
    first = service.save_team(name="Team A", country_id=country, gender="Men")
    second = service.save_team(name="Team B", country_id=country, gender="Men")
    ruleset = next(row for row in service.list_rulesets() if row["match_format_code"] == "TEST")
    competition = service.save_competition(
        name="Test Series", season="2026", ruleset_id=ruleset["id"],
        gender="Men", format="Test", country_id=country,
    )
    match = service.save_match(
        competition_id=competition, match_date="2026-08-01", venue_id=venue,
        home_team_id=first, away_team_id=second, match_status="Scheduled",
    )
    return {
        "match": match, "first": first, "second": second,
        "competition": competition,
    }


def innings(
    service: CricketService,
    match: dict[str, int],
    number: int,
    batting: int,
    runs: int,
    wickets: int,
    status: str,
    balls: int | None = None,
) -> int:
    """Save one Test innings with the opposition derived from the fixture."""
    bowling = match["second"] if batting == match["first"] else match["first"]
    return service.save_innings(
        match_id=match["match"], innings_number=number,
        batting_team_id=batting, bowling_team_id=bowling,
        runs=runs, wickets=wickets, balls=balls, innings_status=status,
    )


def test_test_format_is_unlimited_and_active(
    service: CricketService, test_match: dict[str, int]
) -> None:
    """Test innings have two team innings and no delivery allocation."""
    match_format = next(
        row for row in service.list_match_formats() if row["code"] == "TEST"
    )
    assert match_format["active"] == 1
    assert match_format["innings_per_team"] == 2
    assert match_format["limit_unit"] is None
    assert match_format["innings_limit"] is None
    assert service.effective_innings_balls(test_match["match"]) is None
    listed = service.list_matches(test_match["competition"])[0]
    assert listed["effective_delivery_display"] == "Unlimited"


def test_test_innings_with_delivery_progress_can_be_listed(
    service: CricketService, test_match: dict[str, int]
) -> None:
    """Unlimited innings display optional delivery progress in over notation."""
    innings_id = innings(
        service,
        test_match,
        1,
        test_match["first"],
        0,
        0,
        "In Progress",
        0,
    )

    listed = service.list_innings(test_match["match"])

    assert listed[0]["id"] == innings_id
    assert listed[0]["delivery_display"] == "0.0 overs"


def test_fourth_innings_run_victory_is_calculated(
    service: CricketService, test_match: dict[str, int]
) -> None:
    """Aggregate scores produce a fourth-innings win by runs."""
    innings(service, test_match, 1, test_match["first"], 350, 8, "Declared", 620)
    innings(service, test_match, 2, test_match["second"], 300, 10, "All Out", 590)
    innings(service, test_match, 3, test_match["first"], 200, 6, "Declared", 330)
    innings(service, test_match, 4, test_match["second"], 225, 10, "All Out", 410)

    match = service.repo.matches.get(test_match["match"])
    assert match["match_status"] == "Completed"
    assert match["winning_team_id"] == test_match["first"]
    assert match["result_type"] == "Runs"
    assert match["result_margin_value"] == 25


def test_fourth_innings_wicket_victory_and_target_state(
    service: CricketService, test_match: dict[str, int]
) -> None:
    """The final batting team wins with its remaining wickets."""
    innings(service, test_match, 1, test_match["first"], 300, 10, "All Out")
    innings(service, test_match, 2, test_match["second"], 250, 10, "All Out")
    innings(service, test_match, 3, test_match["first"], 180, 10, "All Out")
    innings(service, test_match, 4, test_match["second"], 231, 7, "Target Reached")

    state = service.test_match_state(test_match["match"])
    match = service.repo.matches.get(test_match["match"])
    assert state["final_innings_target"] == 231
    assert match["winning_team_id"] == test_match["second"]
    assert match["result_type"] == "Wickets"
    assert match["result_margin_value"] == 3


def test_follow_on_and_innings_victory(
    service: CricketService, test_match: dict[str, int]
) -> None:
    """A valid follow-on changes the third-innings team and supports an innings win."""
    service.save_match(
        entity_id=test_match["match"], competition_id=test_match["competition"],
        match_date="2026-08-01", home_team_id=test_match["first"],
        away_team_id=test_match["second"], match_status="Scheduled",
        follow_on_enforced=True,
    )
    innings(service, test_match, 1, test_match["first"], 500, 8, "Declared")
    innings(service, test_match, 2, test_match["second"], 200, 10, "All Out")
    state = service.test_match_state(test_match["match"])
    assert state["first_innings_lead"] == 300
    assert state["follow_on_threshold"] == 200
    assert state["follow_on_available"] is True
    innings(service, test_match, 3, test_match["second"], 250, 10, "All Out")

    match = service.repo.matches.get(test_match["match"])
    assert match["winning_team_id"] == test_match["first"]
    assert match["result_type"] == "Innings and Runs"
    assert match["result_margin_value"] == 50
    assert service.result_description(
        {**match, "winning_team_name": "Team A"}
    ) == "Team A won by an innings and 50 runs"


def test_follow_on_below_threshold_is_rejected(
    service: CricketService, test_match: dict[str, int]
) -> None:
    """The configured lead threshold is enforced at the second innings."""
    service.save_match(
        entity_id=test_match["match"], competition_id=test_match["competition"],
        match_date="2026-08-01", home_team_id=test_match["first"],
        away_team_id=test_match["second"], match_status="Scheduled",
        follow_on_enforced=True,
    )
    innings(service, test_match, 1, test_match["first"], 350, 10, "All Out")
    with pytest.raises(ValidationError, match="requires a first-innings lead of 200"):
        innings(service, test_match, 2, test_match["second"], 151, 10, "All Out")


def test_draw_is_explicit_and_level_in_progress_is_not_a_tie(
    service: CricketService, test_match: dict[str, int]
) -> None:
    """Time-dependent draws are explicit and an open level innings is not tied."""
    innings(service, test_match, 1, test_match["first"], 300, 10, "All Out")
    innings(service, test_match, 2, test_match["second"], 250, 10, "All Out")
    innings(service, test_match, 3, test_match["first"], 100, 10, "All Out")
    innings(service, test_match, 4, test_match["second"], 150, 6, "In Progress")
    assert service.derive_match_result(test_match["match"]) is None

    service.save_match(
        entity_id=test_match["match"], competition_id=test_match["competition"],
        match_date="2026-08-01", home_team_id=test_match["first"],
        away_team_id=test_match["second"], match_status="Drawn",
    )
    match = service.repo.matches.get(test_match["match"])
    assert match["result_type"] == "Draw"
    assert match["winning_team_id"] is None
    assert service.result_description(match) == "Match drawn"


def test_test_rejects_limited_overs_fields_and_invalid_order(
    service: CricketService, test_match: dict[str, int]
) -> None:
    """Test records cannot use revised targets or bypass chronological order."""
    with pytest.raises(ValidationError, match="do not use innings allocations"):
        service.save_match(
            entity_id=test_match["match"], competition_id=test_match["competition"],
            match_date="2026-08-01", home_team_id=test_match["first"],
            away_team_id=test_match["second"], scheduled_balls=450,
        )
    with pytest.raises(ValidationError, match="numbered consecutively"):
        innings(service, test_match, 2, test_match["second"], 200, 10, "All Out")
