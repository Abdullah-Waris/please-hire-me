# Readiness audit — October 3, 2026

This audit separates implemented software, fixture evidence, and the remaining live setup. It does not certify unattended employer acceptance or mark the full automation goal finished.

## Implemented and verified

| Requirement | Current evidence |
| --- | --- |
| New users start a local web server and get guided setup | `setup.sh`, `server.py`, `setup_status.py`, and the complete fresh-user browser fixture in `tests/test_dashboard.py` |
| Required resume; optional transcript, cover-letter examples, writing samples, and extra context | Private document ingestion and reviewed-use controls in `onboarding.py` and `materials.py`; document/parser/dashboard tests |
| Confirm facts and separate personal evidence from style/reference material | Fact confirmation/revisions and material roles; tests cover revocation, stale context, source budgets, and scope |
| Match context and generate grounded prose/cover letters | `answers.py` and `letters.py`; one-page PDF and synthetic required-cover-letter submission tests; model support checks remain fallible |
| Preferences, schedule, and bounded CLI/API usage | Validated settings, attempt ceilings, durable per-cycle/day model-request reservations, explicit provider/key selection, rate-limit stop tests |
| Pause active work without reviving an old cycle | Cancellation generations, checkpoint checks, process-group termination, and pause/recovery tests |
| Reusable applicant instances | Separate private data directories and dedicated browser profiles; setup begins without embedded identity defaults |
| Pi/local operation without public hosting | Quoted user systemd units, system-Chromium configuration, preflight, local dashboard URL, and Raspberry Pi Connect instructions |
| Portable database/history/documents | SQLite backup API, verified archive references/checksums, new-directory restore, paused restoration, and credential exclusion tests |
| Optional Gmail codes and batch reports | Owner-bound OAuth flow, Greenhouse challenge binding, one-use mail consumption, independent report outbox, and synthetic mail/browser tests |
| Intended owner remains configured safely | Private ledger inspection: confirmed email matches the requested owner; submissions paused; zero active runs. No identity/token values are stored in this report. |

## Fresh-environment proof

- macOS ARM64 / Python 3.14: **137 passed**, with a temporary empty HOME and PATH excluding Claude/Codex. Only installed browser binaries were reused. Five third-party PyMuPDF deprecation warnings occurred.
- Debian 12 Bookworm / Linux ARM64 / Python 3.11: all pinned development dependencies installed from scratch; `pip check` passed; Chromium and system dependencies installed; **137 passed in 50.97 seconds**.
- The Linux test container had no credentials or private host mounts, no runtime network, a **4 GiB memory limit**, four CPU allocation, and 512 PID ceiling. Its source was copied from tracked files, including the current test fixes, rather than the whole private working directory.
- Linux base: `python:3.11-slim-bookworm@sha256:2333bd330d12de02514770b3585cad313644316047cdee24a7acfdece6de6efb`.
- These fixtures exercise supported browser forms and transport contracts. They do not exercise live Claude/Codex/API inference, Google delivery, actual systemd activation, SD-card durability, or Pi 4 performance.

## Outstanding requirements

1. **Employer account creation:** currently manual. The original full automation plan included account creation when needed. The internal `hireme.accounts` foundation now stores employer-scoped passwords in private files outside the ledger, events, model input and portable backups. Durable creation intents become uncertain after interruption and cannot be retried automatically; restored history never generates replacement passwords. These files rely on OS permissions, not encryption. Browser integration still needs explicit applicant consent, site-scoped auth adapters, and verification/recovery fixtures. Do not broaden browser write permissions or give the model passwords to fill this gap.
2. **Live Gmail authorization:** the requested owner's private instance has neither a Google Desktop OAuth client nor a connected Gmail token. Signing into Gmail in Chromium does not grant the worker access. Import the client JSON and authorize that account on the worker machine; then verify code receipt and one batch-report delivery.
3. **Pi commissioning:** provision supported 64-bit Raspberry Pi OS, install Chromium and the selected provider, restore or complete the private applicant setup, install services, verify pause/restart and backup restoration, and run a bounded supervised batch. Retire the source machine's scheduler first. Hardware is not connected in this session.
4. **Live new-provider validation:** Codex and API adapters have fixture coverage; confirm the selected CLI version/login or API model access before enabling unattended work. API mode needs an explicitly chosen key/model and vendor-side spend limits.

See the [main README](../README.md) for setup commands and the [worker contract](worker-contract.md) for invariants. Full automation remains incomplete while the outstanding requirements remain.
