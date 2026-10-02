# Contributing

The worker must never invent facts, retry uncertain submissions, exceed company/application budgets or bypass login/CAPTCHA. Keep those properties executable and tested, not in model prompts.

Run `.venv/bin/python -m pytest -q`, `node --check hireme/static/app.js`, and `bash -n` on each changed shell file individually. Browser tests must use synthetic local ATS fixtures. Never test a submission against a real employer as a contributor check.

No personal data belongs in git: facts, documents, screenshots, logs, credentials and application history stay private. Before committing, inspect `git diff --cached` and `git status --short`. Source research is public evidence only; do not write candidate answers into tracked notes.

Every adapter must declare its trusted destinations and bounded actions, demonstrate unknown-field handling, record exact Q&A, and preserve UNKNOWN after ambiguous submission. Unsupported widgets/portals become exceptions rather than broader agent authority.
