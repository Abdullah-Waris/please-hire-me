# Worker architecture and verification boundaries

```text
Full public snapshots → durable jobs → deterministic eligibility and skill score
                                          ↓
Confirmed fact store + exact saved answers + approved prose templates
                                          ↓
Dedicated browser → field verification → immutable Q&A package + screenshot
                                          ↓
SQLite transaction: policy + budgets + durable SUBMITTING intent
                                          ↓
One final click → confirmation and screenshot → CONFIRMED or UNKNOWN
                                          ↓
Local dashboard: outcomes, questions, manual jobs, reconciliation, source health
```

## Authority

The SQLite ledger is authoritative. JSON files are private review exports. The provider has no tools and can only propose quoted facts or choose approved template IDs. Executor inputs never contain model-authored Python/JavaScript/selectors, file paths, arbitrary field values or shell commands. DOM evaluation is fixed read-only inspection code.

Private files use 0700 directories/0600 files. Uploaded PDFs are content-addressed and checked again before upload. Known application destinations are exact hostnames; network helpers reject private addresses and bound payload sizes. Browser requests restrict mutating origins and arbitrary third-party destinations; unsupported pre-submit writes are denied except read-only GraphQL and upload paths. This is application-layer defense, not a formal browser/OS sandbox. ATS scripts and intended destination servers necessarily receive submitted personal information.

The dashboard binds loopback, checks Host and Origin, requires a random per-server capability for APIs, has no external assets, disallows framing, uses DOM text nodes for remote content, and accepts bounded inputs. The URL token moves from the fragment into session storage; it is omitted from access logs and Referer headers.

## State and concurrency

Prepared packages contain fact/document revisions and exact answers. Any fact change invalidates prepared packages. Before click, the worker revalidates policy, values, docs, pause and limits inside a transaction. SUBMITTING survives process termination as UNKNOWN. There is no claimed exactly-once guarantee against arbitrary ATS servers; no automatic retry after intent is the safeguard. Human verification may classify a non-submitted attempt, but that job remains held rather than silently retrying.

All default checkouts share one store and OS locks. Explicit alternative data directories create independent applicant histories and must not be used to parallelize one person's submissions. The default queue rechecks blocked jobs in future cycles; facts/questions resolved once become available without manual per-job approval.

## Compatibility limits

Single-page forms with native controls and inspectable custom comboboxes are supported by the generic adapter. Cross-origin frames, invisible/unknown controls, custom consent widgets, multi-step profile saves and unverifiable confirmations are held. Portal adapters discover roles but do not certify application markup. Passive CAPTCHA can still reject automated input; interactive challenges are never attempted.

No Gmail credential integration, arbitrary post-run hook, clipboard broker, localhost resume transport or personal-browser attachment remains. Provider-specific CLI arguments are isolated behind the provider class; business policy is model independent. The subscription CLI must support safe mode and tool disabling; failures stop inference. Optional API providers and resume tailoring are intentionally not enabled without a separately reviewed implementation.

## Release validation

Run the full local suite and browser fixture tests, inspect the diff, and verify dashboard desktop/mobile. Actual employer acceptance, live portal sessions, scheduling while asleep and sustained daily throughput require independent operational evidence. Do not label them verified from local tests.
