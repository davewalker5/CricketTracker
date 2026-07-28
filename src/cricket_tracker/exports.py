"""CSV and PDF export helpers for Cricket Tracker."""

from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path
from typing import Any


DATASETS = (
    "countries", "venues", "teams", "competition_rulesets",
    "competitions", "matches", "innings",
)

EXPORT_QUERIES = {
    "countries": """
        SELECT name, code FROM countries ORDER BY name COLLATE NOCASE
    """,
    "venues": """
        SELECT v.name, v.city, c.name AS country, v.capacity
        FROM venues v LEFT JOIN countries c ON c.id = v.country_id
        ORDER BY v.name COLLATE NOCASE
    """,
    "teams": """
        SELECT t.name, c.name AS country, t.gender,
               v.name AS home_venue
        FROM teams t
        LEFT JOIN countries c ON c.id = t.country_id
        LEFT JOIN venues v ON v.id = t.home_venue_id
        ORDER BY t.name COLLATE NOCASE
    """,
    "competition_rulesets": """
        SELECT r.name, f.name AS match_format, r.points_for_win,
               r.points_for_tie, r.points_for_no_result,
               r.points_for_abandonment, r.points_for_loss, r.has_standings,
               r.uses_net_run_rate, r.include_knockout_matches_in_table,
               r.table_sort_order, r.balls_per_innings, r.wickets_per_innings,
               r.balls_per_rate_unit, r.combine_gender_tables,
               r.ties_may_stand, r.tie_break_winner_allowed,
               r.revised_targets_allowed
        FROM competition_rulesets r
        JOIN match_formats f ON f.id = r.match_format_id
        ORDER BY r.name COLLATE NOCASE
    """,
    "competitions": """
        SELECT x.name, x.season, r.name AS ruleset, x.gender, x.format,
               c.name AS country
        FROM competitions x
        LEFT JOIN countries c ON c.id = x.country_id
        JOIN competition_rulesets r ON r.id = x.ruleset_id
        ORDER BY x.season, x.name COLLATE NOCASE
    """,
    "matches": """
        SELECT c.name AS competition, c.season, m.match_date, m.start_time,
               v.name AS venue, h.name AS home_team, a.name AS away_team,
               m.match_stage, m.match_status, tw.name AS toss_winner,
               m.toss_decision, w.name AS winning_team, m.result_type,
               m.result_margin_value, m.result_margin_type, m.result_method,
               m.result_source, m.result_override_reason,
               m.scheduled_balls, m.revised_balls,
               m.target_runs, m.revised_target_runs
        FROM matches m
        JOIN competitions c ON c.id = m.competition_id
        LEFT JOIN venues v ON v.id = m.venue_id
        JOIN teams h ON h.id = m.home_team_id
        JOIN teams a ON a.id = m.away_team_id
        LEFT JOIN teams tw ON tw.id = m.toss_winner_team_id
        LEFT JOIN teams w ON w.id = m.winning_team_id
        ORDER BY m.match_date, COALESCE(m.start_time, ''), m.id
    """,
    "innings": """
        SELECT c.name AS competition, c.season, m.match_date,
               h.name AS home_team, a.name AS away_team, i.innings_number,
               b.name AS batting_team, o.name AS bowling_team, i.runs,
               i.wickets, i.balls, i.extras, i.target, i.completed,
               i.innings_status
        FROM innings i
        JOIN matches m ON m.id = i.match_id
        JOIN competitions c ON c.id = m.competition_id
        JOIN teams h ON h.id = m.home_team_id
        JOIN teams a ON a.id = m.away_team_id
        LEFT JOIN teams b ON b.id = i.batting_team_id
        LEFT JOIN teams o ON o.id = i.bowling_team_id
        ORDER BY m.match_date, m.id, i.innings_number
    """,
}

COMPETITION_FILTERS = {
    "countries": """
        id IN (
            SELECT country_id FROM competitions WHERE id = :competition_id
            UNION
            SELECT t.country_id
            FROM teams t
            WHERE t.id IN (
                SELECT home_team_id FROM matches WHERE competition_id = :competition_id
                UNION
                SELECT away_team_id FROM matches WHERE competition_id = :competition_id
            )
            UNION
            SELECT v.country_id
            FROM venues v
            WHERE v.id IN (
                SELECT venue_id FROM matches WHERE competition_id = :competition_id
                UNION
                SELECT t.home_venue_id
                FROM teams t
                WHERE t.id IN (
                    SELECT home_team_id FROM matches WHERE competition_id = :competition_id
                    UNION
                    SELECT away_team_id FROM matches WHERE competition_id = :competition_id
                )
            )
        )
    """,
    "venues": """
        v.id IN (
            SELECT venue_id FROM matches WHERE competition_id = :competition_id
            UNION
            SELECT t.home_venue_id
            FROM teams t
            WHERE t.id IN (
                SELECT home_team_id FROM matches WHERE competition_id = :competition_id
                UNION
                SELECT away_team_id FROM matches WHERE competition_id = :competition_id
            )
        )
    """,
    "teams": """
        t.id IN (
            SELECT home_team_id FROM matches WHERE competition_id = :competition_id
            UNION
            SELECT away_team_id FROM matches WHERE competition_id = :competition_id
        )
    """,
    "competition_rulesets": """
        r.id IN (SELECT ruleset_id FROM competitions WHERE id = :competition_id)
    """,
    "competitions": "x.id = :competition_id",
    "matches": "m.competition_id = :competition_id",
    "innings": "m.competition_id = :competition_id",
}


def export_csv(
    connection: sqlite3.Connection,
    dataset: str,
    competition_id: int | None = None,
) -> str:
    """Export one supported dataset to CSV text.

    :param connection: Open SQLite connection.
    :param dataset: Dataset name from :data:`DATASETS`.
    :param competition_id: Optional competition whose related rows should be exported.
    :return: CSV text with a header row.
    :raises ValueError: If the dataset or competition is unsupported.
    """
    if dataset not in EXPORT_QUERIES:
        raise ValueError(f"Unsupported export dataset: {dataset}.")
    query = EXPORT_QUERIES[dataset]
    parameters: dict[str, int] = {}
    if competition_id is not None:
        # Reject stale UI or command-line identifiers with a clear message.
        competition = connection.execute(
            "SELECT 1 FROM competitions WHERE id = ?", (competition_id,)
        ).fetchone()
        if not competition:
            raise ValueError(f"No competition exists with ID {competition_id}.")
        # Every export query has one ORDER BY, so insert its dataset-specific filter before it.
        query = query.replace(
            "ORDER BY",
            f"WHERE {COMPETITION_FILTERS[dataset]} ORDER BY",
            1,
        )
        parameters["competition_id"] = competition_id
    cursor = connection.execute(query, parameters)
    output = io.StringIO()
    fieldnames = [column[0] for column in cursor.description]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in cursor.fetchall():
        writer.writerow(dict(row))
    return output.getvalue()


def export_all(
    connection: sqlite3.Connection,
    directory: Path | str,
    competition_id: int | None = None,
) -> list[Path]:
    """Write every supported CSV dataset to a directory.

    :param connection: Open SQLite connection.
    :param directory: Destination directory.
    :param competition_id: Optional competition whose related rows should be exported.
    :return: Paths written in dependency order.
    """
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for dataset in DATASETS:
        path = target / f"{dataset}.csv"
        # Apply the same scope to every file so a filtered directory remains importable.
        path.write_text(
            export_csv(connection, dataset, competition_id),
            encoding="utf-8",
        )
        written.append(path)
    return written


def standings_pdf(
    title: str, table: list[dict[str, Any]], destination: Path | str
) -> Path:
    """Create a compact PDF league-table report.

    :param title: Report title.
    :param table: Calculated standings rows.
    :param destination: Output PDF path.
    :return: Written PDF path.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle, Paragraph

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(str(path), pagesize=A4)
    styles = getSampleStyleSheet()
    headings = ["Team", "P", "W", "L", "T", "NR", "Pts", "NRR"]
    rows = [
        [
            row["team"], row["played"], row["won"], row["lost"], row["tied"],
            row["no_result"], row["points"],
            "—" if row["net_run_rate"] is None else f"{row['net_run_rate']:+.3f}",
        ]
        for row in table
    ]
    report_table = Table([headings, *rows], repeatRows=1)
    report_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173f35")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef5f2")]),
            ]
        )
    )
    document.build([Paragraph(title, styles["Title"]), Spacer(1, 12), report_table])
    return path
