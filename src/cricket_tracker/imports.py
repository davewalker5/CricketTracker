"""Validated CSV imports for Cricket Tracker reference and match data."""

from __future__ import annotations

import csv
import io
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable

from cricket_tracker.services import CricketService, ValidationError


@dataclass
class ImportResult:
    """Summarise one CSV import without hiding row errors."""

    imported: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


class DuplicateRow(Exception):
    """Signal that an import row already exists and should be skipped."""


def _boolean(value: Any, default: bool = True) -> bool:
    """Parse a CSV boolean.

    :param value: CSV cell value.
    :param default: Value used for a blank cell.
    :return: Parsed boolean.
    :raises ValidationError: If text is not recognisable.
    """
    text = str(value or "").strip().casefold()
    if not text:
        return default
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    raise ValidationError(f"Invalid boolean value: {value}.")


def _optional_integer(value: Any) -> int | None:
    """Parse an optional CSV integer.

    :param value: CSV cell value.
    :return: Integer or ``None`` for blank input.
    """
    return None if value in (None, "") else int(value)


class CricketImporter:
    """Import named CSV datasets through the validated service layer."""

    def __init__(self, connection: sqlite3.Connection):
        """Initialise an importer.

        :param connection: Open SQLite connection.
        :return: None.
        """
        self.connection = connection
        self.service = CricketService(connection)

    def _id(self, table: str, name: str | None, label: str) -> int | None:
        """Resolve an optional named reference.

        :param table: Trusted reference table.
        :param name: Name from the CSV.
        :param label: User-facing reference label.
        :return: Identifier or ``None`` for blank input.
        :raises ValidationError: If the named row does not exist.
        """
        if not str(name or "").strip():
            return None
        row = self.connection.execute(
            f"SELECT id FROM {table} WHERE name = ? COLLATE NOCASE", (str(name).strip(),)
        ).fetchone()
        if not row:
            raise ValidationError(f"Unknown {label}: {name}.")
        return int(row["id"])

    def _skip_when_found(
        self, query: str, parameters: tuple[Any, ...]
    ) -> None:
        """Skip an import row when its defining key already exists.

        :param query: Trusted existence query returning at most one row.
        :param parameters: Values forming the dataset's defining key.
        :return: None.
        :raises DuplicateRow: If a matching database record exists.
        """
        if self.connection.execute(query, parameters).fetchone():
            raise DuplicateRow

    def _competition_identity(
        self, competition: str, season: str
    ) -> tuple[int, str]:
        """Resolve a competition's identifier and gender.

        :param competition: Competition name.
        :param season: Season label.
        :return: Competition identifier and canonical gender.
        :raises ValidationError: If no matching competition exists.
        """
        row = self.connection.execute(
            """
            SELECT c.id, c.gender
            FROM competitions c
            WHERE c.name = ? COLLATE NOCASE AND c.season = ? COLLATE NOCASE
            """,
            (competition.strip(), season.strip()),
        ).fetchone()
        if not row:
            raise ValidationError(f"Unknown competition: {competition} {season}.")
        return int(row["id"]), str(row["gender"])

    def _competition_id(self, competition: str, season: str) -> int:
        """Resolve a competition identifier by name and season.

        :param competition: Competition name.
        :param season: Season label.
        :return: Competition identifier.
        :raises ValidationError: If no matching competition exists.
        """
        competition_id, _ = self._competition_identity(competition, season)
        return competition_id

    def _team_id(
        self, name: str | None, gender: str, label: str
    ) -> int | None:
        """Resolve a team by its composite name-and-gender key.

        :param name: Team name from the CSV.
        :param gender: Team gender inferred from the competition.
        :param label: User-facing reference label.
        :return: Team identifier or ``None`` for blank input.
        :raises ValidationError: If the named and gendered team does not exist.
        """
        if not str(name or "").strip():
            return None
        row = self.connection.execute(
            """
            SELECT id FROM teams
            WHERE name = ? COLLATE NOCASE
              AND gender = ? COLLATE NOCASE
            """,
            (str(name).strip(), gender),
        ).fetchone()
        if not row:
            raise ValidationError(f"Unknown {gender.lower()} {label}: {name}.")
        return int(row["id"])

    def import_csv(self, dataset: str, content: str | bytes) -> ImportResult:
        """Import a supported CSV dataset.

        Each row is isolated by a savepoint, so a malformed row does not discard
        valid rows and the returned summary remains actionable.

        :param dataset: Supported dataset name.
        :param content: UTF-8 CSV text or bytes.
        :return: Import counts and row-specific errors.
        :raises ValueError: If the dataset is unsupported.
        """
        handlers: dict[str, Callable[[dict[str, str]], None]] = {
            "countries": self._country,
            "venues": self._venue,
            "teams": self._team,
            "competition_rulesets": self._ruleset,
            "competitions": self._competition,
            "matches": self._match,
            "innings": self._innings,
        }
        if dataset not in handlers:
            raise ValueError(f"Unsupported import dataset: {dataset}.")
        text = content.decode("utf-8-sig") if isinstance(content, bytes) else content.lstrip("\ufeff")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValidationError("CSV file must contain a header row.")
        result = ImportResult()
        for line_number, row in enumerate(reader, start=2):
            self.connection.execute("SAVEPOINT import_row")
            try:
                handlers[dataset]({key: (value or "").strip() for key, value in row.items()})
                self.connection.execute("RELEASE import_row")
                result.imported += 1
            except DuplicateRow:
                self.connection.execute("ROLLBACK TO import_row")
                self.connection.execute("RELEASE import_row")
                result.skipped += 1
            except (ValidationError, ValueError, sqlite3.IntegrityError) as error:
                self.connection.execute("ROLLBACK TO import_row")
                self.connection.execute("RELEASE import_row")
                result.skipped += 1
                result.errors.append(f"Row {line_number}: {error}")
        return result

    def _country(self, row: dict[str, str]) -> None:
        """Import a country row.

        :param row: Normalised CSV row.
        :return: None.
        """
        self._skip_when_found(
            "SELECT 1 FROM countries WHERE name = ? COLLATE NOCASE",
            (row.get("name"),),
        )
        self.service.save_country(name=row.get("name"), code=row.get("code"))

    def _venue(self, row: dict[str, str]) -> None:
        """Import a venue row.

        :param row: Normalised CSV row.
        :return: None.
        """
        self._skip_when_found(
            """
            SELECT 1 FROM venues
            WHERE name = ? COLLATE NOCASE
              AND COALESCE(city, '') = ? COLLATE NOCASE
            """,
            (row.get("name"), row.get("city") or ""),
        )
        self.service.save_venue(
            name=row.get("name"),
            city=row.get("city"),
            country_id=self._id("countries", row.get("country"), "country"),
            capacity=_optional_integer(row.get("capacity")),
        )

    def _team(self, row: dict[str, str]) -> None:
        """Import a team row.

        :param row: Normalised CSV row.
        :return: None.
        """
        self._skip_when_found(
            """
            SELECT 1 FROM teams
            WHERE name = ? COLLATE NOCASE
              AND gender = ? COLLATE NOCASE
            """,
            (row.get("name"), row.get("gender")),
        )
        self.service.save_team(
            name=row.get("name"),
            country_id=self._id("countries", row.get("country"), "country"),
            gender=row.get("gender"),
            home_venue_id=self._id("venues", row.get("home_venue"), "home venue"),
        )

    def _ruleset(self, row: dict[str, str]) -> None:
        """Import a ruleset row.

        :param row: Normalised CSV row.
        :return: None.
        """
        self._skip_when_found(
            "SELECT 1 FROM competition_rulesets WHERE name = ? COLLATE NOCASE",
            (row.get("name"),),
        )
        self.service.save_ruleset(
            name=row.get("name"),
            points_for_win=row.get("points_for_win", 2),
            points_for_tie=row.get("points_for_tie", 1),
            points_for_no_result=row.get("points_for_no_result", 1),
            points_for_loss=row.get("points_for_loss", 0),
            uses_net_run_rate=_boolean(row.get("uses_net_run_rate")),
            include_knockout_matches_in_table=_boolean(
                row.get("include_knockout_matches_in_table"), False
            ),
            table_sort_order=row.get("table_sort_order") or "points,net_run_rate,wins",
            balls_per_innings=row.get("balls_per_innings", 100),
            wickets_per_innings=row.get("wickets_per_innings", 10),
            balls_per_rate_unit=row.get("balls_per_rate_unit", 6),
            combine_gender_tables=_boolean(row.get("combine_gender_tables")),
        )

    def _competition(self, row: dict[str, str]) -> None:
        """Import a competition row.

        :param row: Normalised CSV row.
        :return: None.
        """
        self._skip_when_found(
            """
            SELECT 1 FROM competitions
            WHERE name = ? COLLATE NOCASE AND season = ? COLLATE NOCASE
            """,
            (row.get("name"), row.get("season")),
        )
        self.service.save_competition(
            name=row.get("name"),
            season=row.get("season"),
            ruleset_id=self._id("competition_rulesets", row.get("ruleset"), "ruleset"),
            gender=row.get("gender"),
            format=row.get("format") or "The Hundred",
            country_id=self._id("countries", row.get("country"), "country"),
        )

    def _match(self, row: dict[str, str]) -> None:
        """Import a match row.

        :param row: Normalised CSV row.
        :return: None.
        """
        competition_id, gender = self._competition_identity(
            row.get("competition", ""), row.get("season", "")
        )
        home_team_id = self._team_id(row.get("home_team"), gender, "home team")
        away_team_id = self._team_id(row.get("away_team"), gender, "away team")
        self._skip_when_found(
            """
            SELECT 1 FROM matches
            WHERE competition_id = ? AND match_date = ?
              AND home_team_id = ? AND away_team_id = ?
            """,
            (competition_id, row.get("match_date"), home_team_id, away_team_id),
        )
        self.service.save_match(
            competition_id=competition_id,
            match_date=row.get("match_date"),
            start_time=row.get("start_time"),
            venue_id=self._id("venues", row.get("venue"), "venue"),
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            match_stage=row.get("match_stage") or "League",
            match_status=row.get("match_status") or "Scheduled",
            toss_winner_team_id=self._team_id(
                row.get("toss_winner"), gender, "toss winner"
            ),
            toss_decision=row.get("toss_decision"),
            winning_team_id=self._team_id(
                row.get("winning_team"), gender, "winning team"
            ),
            result_type=row.get("result_type"),
            result_margin_value=_optional_integer(row.get("result_margin_value")),
            result_margin_type=row.get("result_margin_type"),
            result_method=row.get("result_method"),
            result_source=row.get("result_source"),
            result_override_reason=row.get("result_override_reason"),
            _defer_completion_validation=True,
        )

    def _innings_match_identity(
        self, row: dict[str, str]
    ) -> tuple[int, str]:
        """Resolve an innings fixture and its competition gender.

        :param row: Normalised innings CSV row.
        :return: Match identifier and canonical competition gender.
        :raises ValidationError: If the fixture is missing or ambiguous.
        """
        competition_id, gender = self._competition_identity(
            row.get("competition", ""), row.get("season", "")
        )
        matches = self.connection.execute(
            """
            SELECT id FROM matches
            WHERE competition_id = ? AND match_date = ?
            ORDER BY id
            LIMIT 2
            """,
            (competition_id, row.get("match_date")),
        ).fetchall()
        if not matches:
            raise ValidationError(
                "Unknown match for innings competition and date."
            )
        if len(matches) > 1:
            # Double-header dates need the fixture teams as a secondary key.
            home_id = self._team_id(
                row.get("home_team"), gender, "home team"
            )
            away_id = self._team_id(
                row.get("away_team"), gender, "away team"
            )
            narrowed = self.connection.execute(
                """
                SELECT id FROM matches
                WHERE competition_id = ? AND match_date = ?
                  AND home_team_id = ? AND away_team_id = ?
                """,
                (
                    competition_id, row.get("match_date"),
                    home_id, away_id,
                ),
            ).fetchall()
            if len(narrowed) != 1:
                raise ValidationError(
                    "More than one match exists for the innings competition "
                    "and date, and the fixture teams do not identify one match."
                )
            matches = narrowed
        return int(matches[0]["id"]), gender

    def _innings(self, row: dict[str, str]) -> None:
        """Import an innings row.

        :param row: Normalised CSV row.
        :return: None.
        """
        match_id, gender = self._innings_match_identity(row)
        self._skip_when_found(
            "SELECT 1 FROM innings WHERE match_id = ? AND innings_number = ?",
            (match_id, row.get("innings_number")),
        )
        self.service.save_innings(
            match_id=match_id,
            innings_number=row.get("innings_number"),
            batting_team_id=self._team_id(
                row.get("batting_team"), gender, "batting team"
            ),
            bowling_team_id=self._team_id(
                row.get("bowling_team"), gender, "bowling team"
            ),
            runs=_optional_integer(row.get("runs")),
            wickets=_optional_integer(row.get("wickets")),
            balls=_optional_integer(row.get("balls")),
            extras=_optional_integer(row.get("extras")),
            target=_optional_integer(row.get("target")),
            completed=_boolean(row.get("completed")),
        )
