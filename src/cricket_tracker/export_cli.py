"""Command-line CSV exporter."""

from __future__ import annotations

import argparse
from pathlib import Path

from cricket_tracker.database import apply_migrations, connect
from cricket_tracker.exports import DATASETS, export_all, export_csv


def parser() -> argparse.ArgumentParser:
    """Build the export argument parser.

    :return: Configured parser.
    """
    # Keep all export controls available to both direct callers and the console script.
    result = argparse.ArgumentParser(description="Export Cricket Tracker CSV data.")
    result.add_argument("destination", type=Path)
    result.add_argument("--dataset", choices=DATASETS)
    result.add_argument(
        "--competition",
        type=int,
        help="Export only data related to this competition ID.",
    )
    return result


def main(arguments: list[str] | None = None) -> int:
    """Export one or all CSV datasets.

    :param arguments: Optional arguments for tests or embedding.
    :return: Zero after a successful export.
    """
    options = parser().parse_args(arguments)
    apply_migrations()
    connection = connect()
    try:
        # A file destination exports one dataset; a directory destination exports all.
        if options.dataset:
            options.destination.parent.mkdir(parents=True, exist_ok=True)
            options.destination.write_text(
                export_csv(connection, options.dataset, options.competition),
                encoding="utf-8",
            )
            print(f"Exported {options.dataset} to {options.destination}.")
        else:
            paths = export_all(connection, options.destination, options.competition)
            print(f"Exported {len(paths)} datasets to {options.destination}.")
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
