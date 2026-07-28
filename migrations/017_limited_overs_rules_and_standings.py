"""Extend competition rules for limited-overs standings and outcomes."""

from yoyo import step


steps = [
    step(
        """
        ALTER TABLE competition_rulesets
        ADD COLUMN points_for_abandonment INTEGER NOT NULL DEFAULT 1
            CHECK (points_for_abandonment >= 0)
        """,
        "ALTER TABLE competition_rulesets DROP COLUMN points_for_abandonment",
    ),
    step(
        """
        UPDATE competition_rulesets
        SET points_for_abandonment = points_for_no_result
        """,
        "SELECT 1",
    ),
    step(
        """
        ALTER TABLE competition_rulesets
        ADD COLUMN has_standings INTEGER NOT NULL DEFAULT 1
            CHECK (has_standings IN (0, 1))
        """,
        "ALTER TABLE competition_rulesets DROP COLUMN has_standings",
    ),
    step(
        """
        ALTER TABLE competition_rulesets
        ADD COLUMN ties_may_stand INTEGER NOT NULL DEFAULT 1
            CHECK (ties_may_stand IN (0, 1))
        """,
        "ALTER TABLE competition_rulesets DROP COLUMN ties_may_stand",
    ),
    step(
        """
        ALTER TABLE competition_rulesets
        ADD COLUMN tie_break_winner_allowed INTEGER NOT NULL DEFAULT 1
            CHECK (tie_break_winner_allowed IN (0, 1))
        """,
        "ALTER TABLE competition_rulesets DROP COLUMN tie_break_winner_allowed",
    ),
    step(
        """
        ALTER TABLE competition_rulesets
        ADD COLUMN revised_targets_allowed INTEGER NOT NULL DEFAULT 1
            CHECK (revised_targets_allowed IN (0, 1))
        """,
        "ALTER TABLE competition_rulesets DROP COLUMN revised_targets_allowed",
    ),
]
