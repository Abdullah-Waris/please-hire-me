#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo 'Python 3.11+ is required.' >&2; exit 1; }
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m playwright install chromium
printf '\nOpen the printed dashboard URL. Import your resume, confirm facts once, and enable automatic applications.\n'
exec .venv/bin/python -m hireme dashboard
