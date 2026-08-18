"""Tests for limited-overs match analysis."""

from __future__ import annotations

import sqlite3

import pytest

from cricket_tracker.analysis import (
    batting_order_summary,
    head_to_head,
    load_analysis_matches,
    scoring_rate,
    team_summary,
)
from cricket_tracker.services import CricketService


def _complete_run_win(service: CricketService, core: dict[str, int]) -> None:
    """Record a completed match won by the team batting first.

    :param service: Cricket service over the test database.
    :param core: Core fixture identifiers.
    :return: None.
    """
    # Both innings carry exact ball counts so score and rate metrics are eligible.
    service.save_innings(
        match_id=core["match"],
        innings_number=1,
        batting_team_id=core["home"],
        bowling_team_id=core["away"],
        runs=150,
        wickets=6,
        balls=100,
        innings_status="completed",
    )
    service.save_innings(
        match_id=core["match"],
        innings_number=2,
        batting_team_id=core["away"],
        bowling_team_id=core["home"],
        runs=137,
        wickets=8,
        balls=100,
        innings_status="completed",
    )
    service.save_match(
        entity_id=core["match"],
        competition_id=core["competition"],
        match_date="2026-07-20",
        venue_id=core["venue"],
        home_team_id=core["home"],
        away_team_id=core["away"],
        match_stage="League",
        match_status="Completed",
    )


def test_scoring_rate_is_format_aware() -> None:
    """Use balls rather than decimal overs for every scoring rate.

    :return: None.
    """
    # The same innings has different conventional displays across the formats.
    assert scoring_rate(106, 100, "HUNDRED") == 106
    assert scoring_rate(106, 100, "T20") == pytest.approx(6.36)
    assert scoring_rate(106, 100, "ODI") == pytest.approx(6.36)
    assert scoring_rate(50, None, "T20") is None


def test_team_summary_uses_team_perspective_and_separate_margins(
    connection: sqlite3.Connection,
    service: CricketService,
    core: dict[str, int],
) -> None:
    """Summarise results, innings, batting order, and margins together.

    :param connection: Open test database connection.
    :param service: Cricket service over the test database.
    :param core: Core fixture identifiers.
    :return: None.
    """
    # A single defending win exercises both the aggregate and history projections.
    _complete_run_win(service, core)
    matches = load_analysis_matches(connection, core["competition"])
    report = team_summary(matches, core["home"])

    assert report["metrics"]["wins"] == 1
    assert report["metrics"]["won_first"] == 1
    assert report["metrics"]["average_scoring_rate"] == 150
    assert report["win_margins"]["largest_runs"] == 13
    assert report["win_margins"]["largest_wickets"] is None
    assert report["history"][0]["Batting position"] == "Batted first"
    assert report["history"][0]["Team innings"] == "150/6"


def test_batting_order_and_head_to_head_find_notable_scores(
    connection: sqlite3.Connection,
    service: CricketService,
    core: dict[str, int],
) -> None:
    """Identify defended totals and preserve actual innings order.

    :param connection: Open test database connection.
    :param service: Cricket service over the test database.
    :param core: Core fixture identifiers.
    :return: None.
    """
    # The same complete match supports competition-wide and head-to-head reports.
    _complete_run_win(service, core)
    matches = load_analysis_matches(connection, core["competition"])
    order_report = batting_order_summary(matches)
    comparison = head_to_head(matches, core["home"], core["away"])

    assert order_report["competition"]["batting_first_wins"] == 1
    assert order_report["competition"]["lowest_successfully_defended_total"] == 150
    assert comparison["notable"]["lowest_successfully_defended_total"] == 150
    assert comparison["notable"]["highest_aggregate"] == 287
    assert comparison["history"][0]["First innings"].endswith("150/6")


def test_head_to_head_rejects_the_same_team() -> None:
    """Prevent a team from being compared with itself.

    :return: None.
    """
    # The service guard also protects callers outside the Streamlit selector.
    with pytest.raises(ValueError, match="distinct teams"):
        head_to_head([], 7, 7)
