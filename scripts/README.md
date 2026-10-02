# Script compatibility

`delta_sweep.py`, `portal_sweep.py`, `list_sweep.py`, `schedule.sh`, `scheduled_run.sh` and `dupe_check.sh` delegate to the managed worker. Discovery stores full snapshots in the private ledger; it does not advance legacy timestamp files. Use `python -m hireme --help` for current flags.

`ashby_form_fields.sh` validates slugs and uses structured GraphQL JSON. `probe_boards.sh` discovers into the ledger; `render_boards.py` prints source health. `tracker_companies.py PATH` extracts explicit wikilinks. The HN helper remains a public read-only research tool.

The old Gmail broker, resume HTTP server and unrestricted Claude launcher are disabled. There is no arbitrary post-run script integration.
