"""Record how each stored match result was produced."""

from yoyo import step


steps = [
    step(
        "ALTER TABLE matches ADD COLUMN result_method TEXT",
        "ALTER TABLE matches DROP COLUMN result_method",
    ),
    step(
        """
        ALTER TABLE matches ADD COLUMN result_source TEXT
        CHECK (result_source IS NULL OR result_source IN ('Calculated', 'Manual'))
        """,
        "ALTER TABLE matches DROP COLUMN result_source",
    ),
    step(
        "ALTER TABLE matches ADD COLUMN result_override_reason TEXT",
        "ALTER TABLE matches DROP COLUMN result_override_reason",
    ),
    step(
        """
        UPDATE matches
        SET result_method = CASE WHEN result_type IS NOT NULL THEN 'Standard' END,
            result_source = CASE WHEN result_type IS NOT NULL THEN 'Manual' END,
            result_override_reason = CASE
                WHEN result_type IS NOT NULL
                THEN 'Result retained from data entered before automatic calculation was enabled.'
            END;
        """,
        "SELECT 1",
    )
]
