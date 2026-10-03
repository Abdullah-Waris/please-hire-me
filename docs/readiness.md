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
| Optional native employer accounts | Explicit opt-in, same-origin exact one-use POST grants, private credentials, durable creation/sign-in intents, paused-write and uncertainty tests; dashboard manual confirmation |
| Recover generated passwords after Pi migration | Separate passphrase-encrypted account-vault transfer; identity/history binding, conflicting-file rejection, idempotent import and unchanged uncertainty states |
| Intended owner remains configured safely | Private ledger inspection: confirmed email matches the requested owner; submissions paused; zero active runs. No identity/token values are stored in this report. |

## Fresh-environment proof

- macOS ARM64 / Python 3.14: **137 passed**, with a temporary empty HOME and PATH excluding Claude/Codex. Only installed browser binaries were reused. Five third-party PyMuPDF deprecation warnings occurred.
- Debian 12 Bookworm / Linux ARM64 / Python 3.11: all pinned development dependencies installed from scratch; `pip check` passed; Chromium and system dependencies installed; **137 passed in 50.97 seconds**.
- The Linux test container had no credentials or private host mounts, no runtime network, a **4 GiB memory limit**, four CPU allocation, and 512 PID ceiling. Its source was copied from tracked files, including the current test fixes, rather than the whole private working directory.
- Linux base: `python:3.11-slim-bookworm@sha256:2333bd330d12de02514770b3585cad313644316047cdee24a7acfdece6de6efb`.
- Native-account follow-up: **156 tests passed** on macOS and **156 passed in 70.65 seconds** in Linux ARM64 under the same 4 GiB/no-runtime-network limits. Mobile opt-in and manual account-confirmation controls were exercised and visually inspected. The final account-history identity guard additionally has focused regression coverage.
- Credential-transfer follow-up: **163 full-suite tests passed in 68.49 seconds** on macOS; an added interruption regression also passed in the eight-test transfer suite. **21 account, backup and transfer tests passed** on Linux ARM64/Python 3.11 under the same 4 GiB/no-runtime-network limits. These exercise real encryption/decryption with synthetic credentials, including resumed partial imports; package dependency checks passed.
- These fixtures exercise supported browser forms and transport contracts. They do not exercise live Claude/Codex/API inference, Google delivery, actual systemd activation, SD-card durability, or Pi 4 performance.

## Application workspace follow-up

- The frontend now includes live overview cards, search/sort/status filters, responsive application records, a guided checklist, grouped preferences, and an essential-facts view with optional fields.
- Read-only demo data is disposable and isolated from personal storage. Authenticated CSV exports include the full opportunity ledger and neutralize spreadsheet formula prefixes, while excluding answer packages and documents.
- Full-ledger totals are verified beyond the auxiliary 500-row snapshot cap and across 23-hour/25-hour local days. Quiet eligibility decisions remain recorded without inflating the attention queue. Exact diagnostic reasons remain available.
- Form regressions cover unsaved drafts, optional-field toggles, provider-specific controls, malformed JSON feedback, and connection recovery. Local setup diagnostics and port-error messages have coverage.
- **264 full-suite tests passed** on macOS ARM64 / Python 3.14 in 83.69 seconds. Coverage includes private history downloads, full-ledger pagination, source revocation, paused crash recovery, connection switching, saved-answer withdrawal, scheduler ownership, company boundaries and alias-resistant attempt history. The five PyMuPDF deprecation warnings remain third-party warnings.
- Preferences show installed and saved schedule intervals separately. Applying an interval preserves paused submissions, protects another applicant’s existing schedule (including disabled systemd timers), and activates only the worker timer when updating a Pi schedule. Tests substitute OS-service calls and do not install a real personal schedule.
- Opportunity details can skip a company and its configured aliases. That action removes only unattempted drafts and unneeded future questions; submitting/confirmed/uncertain/email-verification evidence remains unchanged. Pending preference drafts must be saved first, and errors stay visible inside the dialog.
- SQLite query-plan checks confirm indexes serve recent/fit sorting, active-history selection and daily submission totals. Budget checks read narrow timestamp/state/company metadata, preserving timezone and uncertainty policies without loading answer packages. A disposable check with 3,000 past attempts and 500 aliases took 0.031 seconds with 2.67 MiB traced peak memory on this Mac; this is local fixture evidence, not a Pi benchmark.
- Editing or removing aliases cannot hide earlier attempts from company uncertainty holds, lifetime ceilings, same-day limits or cooldowns. Budget and CLI duplicate checks retain originally recorded keys alongside current aliases of the original employer name; attempt records themselves are unchanged.
- Dashboard refreshes and ledger pages omit answer packages; a capability-protected endpoint retrieves one record when its evidence panel opens. Open panels, keyboard focus and viewed images survive routine refreshes, while state changes invalidate the caches. A fixture containing 500 synthetic answer records reduced the snapshot from 4,277,509 to 317,509 bytes (92.6%); actual savings depend on record contents.
- Employer account review searches and pages the complete metadata history without exposing vault credentials. Old unresolved accounts and failed sources remain visible ahead of recent successful records. Browser fixtures cover mobile paging, Unicode search, failed-load retry and unsaved verification-note protection.
- An axe-core 4.10.3 audit of all eight screens at 1440px, 390px, and 320px, including the expanded saved-answer review and the opportunity dialog, found zero WCAG A/AA rule violations for the selected WCAG 2/2.1 rule tags after contrast and focus fixes. All checked screens had no page overflow. This is automated UI evidence on synthetic data, not live employer acceptance evidence.

## Outstanding requirements

1. **Employer account coverage:** opted-in native registration/sign-in now has browser integration and fixtures. Site-specific JavaScript/SSO, extra fields, agreement acceptance and account email verification still require manual handling. Initial pages containing only sign-in are held because the actual posting has not yet been read for eligibility. Validate account acceptance on selected real portals before unattended use. At-rest credentials rely on OS permissions; regular history backups exclude them. The separate encrypted account-vault export/import now recovers generated passwords into matching restored history without clearing held account states. Do not broaden browser write permissions or give the model passwords to fill remaining gaps.
2. **Live Gmail authorization:** the requested owner's private instance has neither a Google Desktop OAuth client nor a connected Gmail token. Signing into Gmail in Chromium does not grant the worker access. Import the client JSON and authorize that account on the worker machine; then verify code receipt and one batch-report delivery.
3. **Pi commissioning:** provision supported 64-bit Raspberry Pi OS, install Chromium and the selected provider, restore or complete the private applicant setup, install services, verify pause/restart and backup restoration, and run a bounded supervised batch. Retire the source machine's scheduler first. Hardware is not connected in this session.
4. **Live new-provider validation:** Codex and API adapters have fixture coverage; confirm the selected CLI version/login or API model access before enabling unattended work. API mode needs an explicitly chosen key/model and vendor-side spend limits.

See the [main README](../README.md) for setup commands and the [worker contract](worker-contract.md) for invariants. Full automation remains incomplete while the outstanding requirements remain.
