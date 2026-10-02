#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON=".venv/bin/python"
[ -x "$PYTHON" ] || { echo 'Run ./setup.sh to install the worker.' >&2; exit 1; }
if [ $# -gt 0 ] && [[ "$1" =~ ^[0-9]+$ ]]; then
  exec "$PYTHON" -m hireme run --limit "$1"
fi
exec "$PYTHON" -m hireme run "$@"
