# Financial Report Structured Data Policy

Routing status: `active_methodology`
Authority: routed by `AGENTS.md`; cannot override `FR_CURRENT_STATE.md` or `FR_NEXT_TASK.md`.
Current truth route: `AGENTS.md` -> `docs/FR_CANONICAL_CONTEXT_INDEX.md` -> `docs/FR_CURRENT_STATE.md` -> `docs/FR_NEXT_TASK.md`.


Generated: 2026-05-23T10:05:16Z

Structured financial interfaces are the consumption-candidate mainline. Sina, THS, Eastmoney financial statements, Eastmoney earnings tables, CNINFO disclosure metadata, Eastmoney notices and Eastmoney company news can be retained according to interface-level QA.

Official filings and issuer/regulatory disclosures are authoritative evidence
for the filed report, event, or statement. Structured interfaces remain the
consumption-candidate mainline when retrieval, mapping, and QA succeed, but a
parser or connector failure does not invalidate the official filing itself.

PDFs remain original report evidence for explanation, narrative, risk
disclosure, management discussion, strategy context, and reality checks against
structured interfaces. PDF parsing, OCR, extracted tables, cleaned text, and
summaries are derived interpretation layers. They do not overwrite structured
interface metrics or official filing evidence for core financial facts without
an explicit evidence-backed correction.
