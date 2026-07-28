"""Add match allocations and meaningful limited-overs innings statuses."""

from yoyo import step


steps = [
    step(
        """
        ALTER TABLE matches
        ADD COLUMN scheduled_balls INTEGER
            CHECK (scheduled_balls IS NULL OR scheduled_balls > 0)
        """,
        "ALTER TABLE matches DROP COLUMN scheduled_balls",
    ),
    step(
        """
        ALTER TABLE matches
        ADD COLUMN revised_balls INTEGER
            CHECK (revised_balls IS NULL OR revised_balls > 0)
        """,
        "ALTER TABLE matches DROP COLUMN revised_balls",
    ),
    step(
        """
        ALTER TABLE innings
        ADD COLUMN innings_status TEXT NOT NULL DEFAULT 'not_started'
            CHECK (innings_status IN (
                'not_started', 'in_progress', 'completed', 'all_out',
                'target_reached', 'innings_limit_reached', 'abandoned'
            ))
        """,
        "ALTER TABLE innings DROP COLUMN innings_status",
    ),
    step(
        """
        UPDATE innings
        SET innings_status = CASE
            WHEN completed = 1 THEN 'completed'
            WHEN runs IS NOT NULL OR wickets IS NOT NULL OR balls IS NOT NULL
                THEN 'in_progress'
            ELSE 'not_started'
        END
        """,
        """
        UPDATE innings
        SET completed = CASE
            WHEN innings_status IN (
                'completed', 'all_out', 'target_reached',
                'innings_limit_reached'
            ) THEN 1
            ELSE 0
        END
        """,
    ),
]
