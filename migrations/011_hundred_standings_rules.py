"""Correct points and rate units for The Hundred standings."""

from yoyo import step


steps = [
    step(
        """
        ALTER TABLE competition_rulesets
        ADD COLUMN balls_per_rate_unit INTEGER NOT NULL DEFAULT 6
        CHECK (balls_per_rate_unit > 0)
        """,
        "ALTER TABLE competition_rulesets DROP COLUMN balls_per_rate_unit",
    ),
    step(
        """
        UPDATE competition_rulesets
        SET points_for_win = 4,
            points_for_tie = 2,
            points_for_no_result = 2,
            balls_per_rate_unit = 5
        WHERE name = 'The Hundred' COLLATE NOCASE
          AND points_for_win = 2
          AND points_for_tie = 1
          AND points_for_no_result = 1
        """,
        """
        UPDATE competition_rulesets
        SET points_for_win = 2,
            points_for_tie = 1,
            points_for_no_result = 1
        WHERE name = 'The Hundred' COLLATE NOCASE
          AND points_for_win = 4
          AND points_for_tie = 2
          AND points_for_no_result = 2
        """,
    ),
]
