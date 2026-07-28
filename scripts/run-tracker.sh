#!/usr/bin/env bash

export PROJECT_ROOT=$( cd "$(dirname "$0")/.." ; pwd -P )
cd "$PROJECT_ROOT"

. venv/bin/activate

export PYTHONPATH="$PROJECT_ROOT/src"

venv/bin/cricket-tracker
