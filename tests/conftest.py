"""Shared Cricket Tracker test fixtures."""

from __future__ import annotations

import sqlite3

import pytest

from cricket_tracker.database import apply_migrations, connect
from cricket_tracker.services import CricketService


@pytest.fixture
def database(tmp_path):
    """Create a freshly migrated database.

    :param tmp_path: Pytest temporary directory.
    :return: Database path.
    """
    path = tmp_path / "cricket.db"
    apply_migrations(path)
    return path


@pytest.fixture
def connection(database):
    """Open a test connection.

    :param database: Migrated database fixture.
    :return: Iterator yielding an open connection.
    """
    result = connect(database)
    yield result
    result.close()


@pytest.fixture
def service(connection: sqlite3.Connection):
    """Create a service over the test transaction.

    :param connection: Open test connection.
    :return: Cricket service.
    """
    return CricketService(connection)


@pytest.fixture
def core(service: CricketService):
    """Create a representative The Hundred season and fixture.

    :param service: Cricket service.
    :return: Core entity identifiers.
    """
    country = service.save_country(name="England", code="ENG")
    venue = service.save_venue(name="Lord's", city="London", country_id=country)
    home = service.save_team(
        name="London Spirit Men", country_id=country,
        gender="Men", home_venue_id=venue,
    )
    away = service.save_team(
        name="Oval Invincibles Men", country_id=country,
        gender="Men", home_venue_id=venue,
    )
    ruleset = service.list_rulesets()[0]["id"]
    competition = service.save_competition(
        name="The Hundred Men's Competition", season="2026", ruleset_id=ruleset,
        gender="Men", format="The Hundred", country_id=country,
    )
    match = service.save_match(
        competition_id=competition, match_date="2026-07-20", venue_id=venue,
        home_team_id=home, away_team_id=away,
        match_stage="League", match_status="Scheduled",
    )
    return {
        "country": country, "venue": venue, "home": home, "away": away,
        "competition": competition, "ruleset": ruleset, "match": match,
    }
