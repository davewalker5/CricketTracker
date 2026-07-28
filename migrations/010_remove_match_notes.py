"""Remove free-text notes from match records."""

from yoyo import step


steps = [
    step(
        "ALTER TABLE matches DROP COLUMN notes",
        "ALTER TABLE matches ADD COLUMN notes TEXT",
    )
]
