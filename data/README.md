# Discovery seeds and public research

| File | Current use |
| --- | --- |
| `boards.md` | Runtime ATS slug seeds from a historical public board snapshot. Counts and availability can be stale. |
| `slug-candidates.txt` | Runtime slug candidates, including dead/unknown boards. Discovery records current source health in the ledger. |
| `sources.md` | Public research and sourcing ideas; not application eligibility policy. |
| `ats-field-notes.md` | Historical observations about forms and eligibility. Consult executable adapters and current postings before relying on them. |
| `queue.example.md` | Legacy Markdown checklist reference. The managed worker uses SQLite rather than this queue. |

Applicant resumes, transcripts, working queues and other personal files are ignored by Git. New uploads belong in the dashboard and are copied to `~/.local/share/please-hire-me/`, not this tracked data directory. Older ignored files in this checkout are retained for migration, not treated as current authority.

Discovery finds openings; submissions go to approved employer ATS destinations. `scripts/probe_boards.sh` writes discovery results to the private ledger and does not rewrite these tracked research files.
