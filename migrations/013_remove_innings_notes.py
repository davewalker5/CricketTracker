"""Remove free-text notes from innings records."""

from yoyo import step


steps = [
    step(
        "ALTER TABLE innings DROP COLUMN notes",
        "ALTER TABLE innings ADD COLUMN notes TEXT",
    )
]
