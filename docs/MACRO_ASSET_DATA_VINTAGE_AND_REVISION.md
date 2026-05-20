# Macro Asset Data Vintage and Revision

Generated: 2026-05-20T06:48:52Z

Policy:

- Every historical ingestion run has a `retrieval_snapshot_id`.
- Latest normalized files are refreshed, but revision detection compares with previous latest snapshots.
- If a series_id + observation_date value changes, the old/new values are recorded in `revision_log.json`.
- FRED realtime fields are stored when available.
- Sources without vintage support are marked `vintage_support_limited`.
- As-of analysis must use retrieval snapshots and must not silently consume revised values as if they were available historically.

Current revision count: 0
