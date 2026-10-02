# please-hire-me

An automatic job-application worker with a local application desk. Discover internship/new-grad software, ML and research-engineering roles, filter them against confirmed facts, submit supported applications, and leave a clickable exception list for you.

Runs every **six hours**, normally aiming for **seven submissions per cycle**, using up to **ten** when catching up. The daily target is **28**, with a ceiling of **40**. These are goals, not guaranteed results: eligibility, available jobs, company limits, CAPTCHA, login walls and browser availability take priority.

## Start

Requires Python 3.11+, Google Chrome (or bundled Chromium), and Claude Code signed into your subscription if you use model-assisted resume extraction, semantic question matching, or writing-sample selection. A configured Claude CLI API key is also forwarded privately when present.

```bash
./setup.sh
```

Open the local dashboard URL printed in your terminal. Import your resume, confirm the extracted values once, optionally import your transcript under **Your verified facts → Your transcript**, supply authorization and targeting facts, and save approved answer templates. Click **Start automatic applications** to install the six-hour schedule and start the first cycle. **Run a cycle** starts an additional cycle immediately. There is no per-application approval for routine jobs.

If dependencies are already installed:

```bash
.venv/bin/python -m hireme dashboard
.venv/bin/python -m hireme import-resume /absolute/path/resume.pdf
./run.sh
./run.sh 7
```

The dashboard shows real submitted answers and evidence, blocked jobs with direct application links, missing-fact questions, uncertain outcomes, cycle shortfalls and source health. Answer a new question once: its wording, options and employer scope are saved for future use. A company-specific answer cannot silently become another company's answer.

## Facts and privacy

The shared authoritative ledger is at `~/.local/share/please-hire-me/ledger.sqlite3`. All checkouts use it by default, preventing independent clones from losing application history. Facts, answers, JSON review exports, PDFs, screenshots and the dedicated browser profile remain under that private directory. `--data-dir PATH` is available for tests or a genuinely separate applicant; do not use different directories for the same applicant.

Facts have provenance, confirmation and revisions. Resume extraction produces proposals. Citizenship, sponsorship, work authorization, GPA, dates, experience and disclosures are never inferred from template defaults. Blank values remain unknown. Editing JSON exports does not update the ledger; use the dashboard.

Claude receives only the data needed for an inference request, through stdin. It runs in safe mode without built-in tools, MCP, browser access, project configuration or session persistence. It can propose quoted resume facts, match question wording to confirmed profile facts, select approved writing samples, or assemble relevant sentences from those samples. It cannot introduce new factual prose; assembled sentences retain their original wording and source revisions. The CLI still uses its normal subscription authentication; this is a tool-capability boundary, not an OS sandbox around the Claude executable.

Personal information necessarily leaves your computer when supplied to the model or submitted to an employer. Gitignore is not a privacy guarantee. Do not commit personal files or screenshots.

## Automatic submissions and exceptions

Supported single-page forms are inspected and filled by deterministic Playwright code in a **dedicated browser profile**. Your everyday tabs and sessions are not attached. The worker uses genuine browser controls; it does not promise to avoid bot detection or bypass CAPTCHA.

Fields use known mappings, cached semantic matches to confirmed facts, employer-scoped saved answers, or approved writing samples. Exact school/degree aliases and graduation-season formatting are supported. Direct internship evidence can come from the hash-checked resume. Required unknowns, mismatched options, truncation, unsupported widgets, ambiguous eligibility and no-AI/work-sample questions become dashboard exceptions. Optional unknown values are left blank; unsupported prefilled values block submission.

The worker records Q&A and a before-submit screenshot, validates the package again, reserves company/day limits and commits a submit intent before the final click. Confirmation text and an after-submit screenshot determine the recorded outcome. Crash/disconnect/network ambiguity becomes **UNKNOWN**, never an automatic retry. Verify it at the employer and reconcile through the dashboard.

Conservative default company limits: one application per company per day, two lifetime, 90-day cooldown. Skip/interview lists and explicit company aliases are enforced in code. Employer-specific limits may be stricter; add the company to the block list or lower its allowed cadence before proceeding.

## Accounts, verification and unsupported portals

Sign into an approved portal yourself in the dedicated browser:

```bash
.venv/bin/python -m hireme login https://nvidia.wd5.myworkdayjobs.com/
```

This never imports your personal Chrome session. Login, CAPTCHA, emailed verification and unsupported multi-step portal writes are human exceptions with direct links. Discovery includes Workday and other portals; listing a portal does not imply its entire application flow has a tested adapter. Greenhouse/Ashby/Lever/Workable markup variations can also be held for manual handling.

The legacy Gmail/Keychain/clipboard broker and localhost resume server are disabled. No app password is requested. A future automatic OTP service must be bound to a specific application and approved sender. Resume uploads use private hash-checked PDFs only.

## Scheduling and control

```bash
.venv/bin/python -m hireme schedule install
.venv/bin/python -m hireme schedule status
.venv/bin/python -m hireme schedule uninstall
.venv/bin/python -m hireme pause
.venv/bin/python -m hireme resume
.venv/bin/python -m hireme daemon  # alternative terminal scheduler
```

The Mac LaunchAgent uses escaped plist serialization and one shared worker label. Configured Claude connection credentials are preserved in its private 0600 plist so scheduled requests use the same connection. Linux cron uses quoted paths. OS file locks prevent overlapping workers; uncertain attempts and budget reservations also live in SQLite. Scheduling requires completed onboarding. The computer must be awake and the dedicated browser available. A launchd interval is not a promise of four runs during sleep. Keep the dashboard command open for the local UI; scheduled workers run independently.

## Discovery and fit

Public ATS board snapshots, SimplifyJobs lists, six VC boards and company-portal adapters persist candidates into the ledger before application processing. Full snapshots eliminate lossy global sweep cutoffs; individual source errors remain visible and do not delete existing jobs. Sources are checked least-recently-first to avoid starvation. New ATS slugs from discovered URLs are reused without modifying tracked source data.

Every candidate uses shared role, location, seniority, experience, sponsorship, graduation, start-window, compensation and company policy. Skill overlap and early-career wording produce an explainable fit score. Unparseable hard eligibility gates are held, not guessed. Pay floors use known USD minimums and correct hourly/annual periods, not the top of a salary range. A zero floor leaves salary unspecified.

Seasonal targeting supports broad US locations for summer 2027 and separate Bay Area/remote preferences during school. These preferences never establish country-specific legal authorization.

## Existing history

```bash
.venv/bin/python -m hireme import-legacy /path/to/old/checkout
.venv/bin/python -m hireme import-tracker /path/to/interviews.md
```

Legacy facts require confirmation. Inconsistent Markdown history is archived privately and blocks onboarding until you review the employers and add them to the company block list. Do not discard old history to bypass duplicate prevention. Tracker import requires explicit wikilinks and adds company blocks; repeat import when the tracker changes.

## Development and evidence

```bash
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
node --check hireme/static/app.js
```

Tests use synthetic local ATS servers, not real applications. Coverage includes factual provenance, scoped answers, revisions, exact uploads, limits, state transitions, crash recovery, provider capabilities, local dashboard access, source failures and browser submissions. Local fixture proof is not proof of acceptance by any employer. See [docs/architecture.md](docs/architecture.md) for operational boundaries.

MIT. Historical source data and browser recipes are retained as evidence, not executable policy.
