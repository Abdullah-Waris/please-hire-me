#!/usr/bin/env bash
# Discover full board snapshots into the shared ledger; no slug-derived filesystem paths.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python -m hireme discover --source delta "$@"
