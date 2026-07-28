"""Allow rulesets to opt into combined gender standings."""

from yoyo import step


steps = [
    step(
        """
        ALTER TABLE competition_rulesets
        ADD COLUMN combine_gender_tables INTEGER NOT NULL DEFAULT 0
        CHECK (combine_gender_tables IN (0, 1))
        """,
        "ALTER TABLE competition_rulesets DROP COLUMN combine_gender_tables",
    ),
    step(
        """
        UPDATE competition_rulesets
        SET combine_gender_tables = 1
        WHERE name = 'The Hundred' COLLATE NOCASE
        """,
        """
        UPDATE competition_rulesets
        SET combine_gender_tables = 0
        WHERE name = 'The Hundred' COLLATE NOCASE
        """,
    ),
]
