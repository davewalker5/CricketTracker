"""Add explicit original and revised targets for limited-overs results."""

from yoyo import step


steps = [
    step(
        """
        ALTER TABLE matches
        ADD COLUMN target_runs INTEGER
            CHECK (target_runs IS NULL OR target_runs > 0)
        """,
        "ALTER TABLE matches DROP COLUMN target_runs",
    ),
    step(
        """
        ALTER TABLE matches
        ADD COLUMN revised_target_runs INTEGER
            CHECK (revised_target_runs IS NULL OR revised_target_runs > 0)
        """,
        "ALTER TABLE matches DROP COLUMN revised_target_runs",
    ),
]
