# BLS Resilient Ingestion Report

Generated: 2026-05-20T07:37:01Z

Final status: `deferred_retry_needs_api_key_or_later_retry`.

The previous BLS API run returned `REQUEST_NOT_PROCESSED` / daily threshold style failures.
This phase did not stop at that message. It produced:

- failure diagnosis by series
- tiny single-series retry
- deferred retry queue
- official flat-file fallback audit

Fallback audit root: `https://download.bls.gov/pub/time.series/`

Fallback availability count: 0

If threshold persists, add `BLS_API_KEY` to `config/local_secrets.json` and rerun with low-frequency chunking.

No OpenAI API was called. No formal trusted consumption was modified.
