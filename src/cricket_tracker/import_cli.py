"""Command-line CSV importer."""

from __future__ import annotations

import argparse
from pathlib import Path

from cricket_tracker.database import apply_migrations, session
from cricket_tracker.exports import DATASETS
from cricket_tracker.imports import CricketImporter


def parser() -> argparse.ArgumentParser:
    """Build the import argument parser.

    :return: Configured parser.
    """
    result = argparse.ArgumentParser(description="Import Cricket Tracker CSV data.")
    result.add_argument("dataset", choices=DATASETS)
    result.add_argument("file", type=Path)
    return result


def main(arguments: list[str] | None = None) -> int:
    """Import one CSV file.

    :param arguments: Optional arguments for tests or embedding.
    :return: Zero on success, or one when rows were rejected.
    """
    options = parser().parse_args(arguments)
    apply_migrations()
    with session() as connection:
        result = CricketImporter(connection).import_csv(
            options.dataset, options.file.read_bytes()
        )
    print(f"Imported {result.imported}; skipped {result.skipped}.")
    for error in result.errors:
        print(error)
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

