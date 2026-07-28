#!/usr/bin/env bash

if (( $# < 2 )); then
    scriptname=$(basename -- "$0")
    echo "Usage: $scriptname export-type /path/to/export/file.csv"
    exit 1
fi

export PROJECT_ROOT=$( cd "$(dirname "$0")/.." ; pwd -P )
cd "$PROJECT_ROOT"

export PYTHONPATH="$PROJECT_ROOT/src"

type=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')

venv/bin/cricket-export "$2" --dataset "$type"
