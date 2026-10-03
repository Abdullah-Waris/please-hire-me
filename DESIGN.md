# Application desk

## Surface
A private application workspace for individual applicants. Overview shows the worker state, today's confirmed submissions, distinct opportunities needing attention, and the persisted opportunity ledger. Counts reflect local records; no sample activity appears in the real workspace.

## Direction
Cool paper, white surfaces, deep navy text, restrained blue actions, and compact editorial tables. A narrow desktop sidebar groups the workspace, personal sources, and connections. Small uppercase labels establish hierarchy; generous space keeps forms approachable. A typographic monogram and a CSS document illustration introduce the product without remote assets.

The overview uses three summary cards, searchable and sortable opportunities, plain-language status badges, and an expandable posting form. Search includes company, role, and location. Attention counts deduplicate blocked jobs and their questions. Setup presents a numbered checklist, optional-source labels, and visible guided progress. Preferences are grouped into search, company boundaries, pace, model usage, and browser configuration.

## Tokens and behavior
Background #f4f6f9; surface #ffffff; ink #1c2b40; muted #596a82; rule #e2e8ef; action #285ed5. System typography, 15px base and 1.6 line height. State labels accompany color. Controls have at least 44px height, visible focus, real labels, and live notices. Reduced motion is respected. No external fonts, images, scripts, or styles are required.

On smaller screens the sidebar becomes a scrollable horizontal navigation bar. Summary cards reflow, forms become one column, and table rows become labeled records. The workspace must not overflow at 320px or 390px. Text colors are checked against the actual surface backgrounds. Horizontally scrolling command blocks are keyboard focusable. Browser fixture tests cover uploads, setup, counts, filtering, sorting, posting creation, safe text rendering, preferences, and mobile navigation.

Answer packages load when their evidence disclosure opens. Overview refreshes and ledger pages use narrow application metadata. A bounded memory cache retains up to 100 requested records and 10 viewed confirmation images, keyed by record identity, timestamp, package hash, state and screenshot name. No applicant drafts or evidence enter browser storage. Open evidence and diagnostic disclosures retain keyboard focus across refreshes. The unresolved-outcome queue uses the same on-demand evidence cache and preserves its reading focus. Loading and image failures have local retry feedback; corrupt records are reported instead of being represented as empty answers. The opportunity dialog has a sticky close control for long postings.

Writing-source cards retain their DOM nodes across unchanged refreshes. A compact signature covers source identity, revision, update time, display metadata, original-file availability and active page/filter totals. Unsaved source edits still prevent replacement; a confirmed revision, original-file availability change or page/filter change refreshes the cards. Source library requests serialize with regular polling, preserve the current page on failure and restore keyboard focus after explicit page changes.
