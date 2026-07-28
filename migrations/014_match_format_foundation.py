"""Introduce reusable match formats for limited-overs cricket."""

from yoyo import step


steps = [
    step(
        """
        CREATE TABLE match_formats (
            id INTEGER PRIMARY KEY,
            code TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (trim(code) <> ''),
            name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (trim(name) <> ''),
            innings_per_team INTEGER NOT NULL CHECK (innings_per_team > 0),
            limit_unit TEXT NOT NULL CHECK (limit_unit IN ('balls', 'overs')),
            innings_limit INTEGER NOT NULL CHECK (innings_limit > 0),
            balls_per_over INTEGER CHECK (
                (limit_unit = 'balls' AND balls_per_over IS NULL)
                OR
                (limit_unit = 'overs' AND balls_per_over > 0)
            ),
            draw_allowed INTEGER NOT NULL DEFAULT 0
                CHECK (draw_allowed IN (0, 1)),
            tie_allowed INTEGER NOT NULL DEFAULT 1
                CHECK (tie_allowed IN (0, 1)),
            revised_target_supported INTEGER NOT NULL DEFAULT 1
                CHECK (revised_target_supported IN (0, 1)),
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
        )
        """,
        "DROP TABLE match_formats",
    ),
    step(
        """
        INSERT INTO match_formats (
            id, code, name, innings_per_team, limit_unit, innings_limit,
            balls_per_over, draw_allowed, tie_allowed,
            revised_target_supported, active
        ) VALUES
            (1, 'HUNDRED', 'The Hundred', 1, 'balls', 100, NULL, 0, 1, 1, 1),
            (2, 'T20', 'Twenty20', 1, 'overs', 20, 6, 0, 1, 1, 1),
            (3, 'ODI', 'One Day', 1, 'overs', 50, 6, 0, 1, 1, 1)
        """,
        "DELETE FROM match_formats WHERE id IN (1, 2, 3)",
    ),
    step(
        """
        ALTER TABLE competition_rulesets
        ADD COLUMN match_format_id INTEGER NOT NULL DEFAULT 1
            REFERENCES match_formats(id) ON DELETE RESTRICT
        """,
        "ALTER TABLE competition_rulesets DROP COLUMN match_format_id",
    ),
    step(
        """
        CREATE INDEX competition_rulesets_match_format_idx
        ON competition_rulesets(match_format_id)
        """,
        "DROP INDEX competition_rulesets_match_format_idx",
    ),
]
