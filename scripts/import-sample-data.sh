#!/usr/bin/env bash

# Import the complete T20 and ODI examples into the configured Cricket Tracker
# database. Set CRICKET_TRACKER_DB before running to target a different database.
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd -P)
PROJECT_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd -P)
IMPORT_COMMAND="$PROJECT_DIR/venv/bin/cricket-import"
SAMPLES_DIR="$PROJECT_DIR/data/samples"

declare -a sample_folders=(
    "T20-EXAMPLE-2026"
    "ODI-EXAMPLE-2026"
)

# Reference data must be loaded before records which refer to it.
declare -a datasets=(
    "countries"
    "venues"
    "teams"
    "competition_rulesets"
    "competitions"
    "matches"
    "innings"
)

if [[ ! -x "$IMPORT_COMMAND" ]]; then
    echo "Cricket Tracker importer not found at: $IMPORT_COMMAND" >&2
    echo "Create the project virtual environment before importing sample data." >&2
    exit 1
fi

export PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

for sample_folder in "${sample_folders[@]}"; do
    echo "Importing $sample_folder..."

    for dataset in "${datasets[@]}"; do
        sample_file="$SAMPLES_DIR/$sample_folder/$dataset.csv"
        if [[ ! -f "$sample_file" ]]; then
            echo "Required sample file not found: $sample_file" >&2
            exit 1
        fi

        echo "  $dataset"
        "$IMPORT_COMMAND" "$dataset" "$sample_file"
    done
done

echo "T20 and ODI sample data imported successfully."
