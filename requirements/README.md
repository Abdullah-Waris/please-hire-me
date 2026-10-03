# Dependency locks

- `runtime.lock`: pinned application and optional Gmail dependencies used by `setup.sh`.
- `development.lock`: runtime dependencies plus pytest and PDF rendering tools used by CI and local verification.

Both install before `pip install --no-deps -e .`. Supported dependency ranges and optional extras are declared in `../pyproject.toml`. Keep the runtime pins consistent with the development lock; do not commit an editable checkout path or a platform-specific local wheel URL.
