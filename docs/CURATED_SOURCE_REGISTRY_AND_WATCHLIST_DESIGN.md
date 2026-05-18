# Curated Source Registry and Watchlist Design

## Config Files

- Watchlist: `config/watchlist.json`
- Metrics registry: `config/metrics_registry.json`

The watchlist is deliberately small and sample-oriented. It is not a production investment universe.

## Curated Source Registry

| Source | Trust eligibility | Quality | Incremental | Phase status | Next action |
|---|---|---|---:|---|---|
| sec_edgar_companyfacts | trusted_by_real_external_candidate | quality_passed | True | active_curated | incremental_small_sample_and_quality_gate |
| bls_public_api | trusted_by_real_external_candidate | quality_passed | True | active_curated | incremental_small_sample_and_quality_gate |
| treasury_fiscaldata | trusted_by_real_external_candidate | quality_passed | True | active_curated | incremental_small_sample_and_quality_gate |
| world_bank_pink_sheet | trusted_by_real_external_candidate | quality_passed | True | active_curated | incremental_small_sample_and_quality_gate |
| cninfo_disclosure | trusted_by_official_source_candidate | quality_passed | True | active_report_discovery_smoke | keep small discovery and preserve PDF checksum |
| baostock_daily | candidate_external_data | quality_passed | True | active_candidate | document dataset-level upstream provenance before consumption-grade use |
| akshare_traceable_official | dataset_level_provenance_required | quality_failed | False | defer | retry only traceable official datasets when upstream is reachable |
| fred_public_csv | retry_or_fallback | quality_failed | False | defer | retry with timeout/backoff or replace with alternate official source |

## Design Notes

- SEC, BLS, Treasury, and World Bank are official/authoritative and can become `trusted_by_real_external_candidate` only after quality passes.
- CNINFO is treated as official disclosure metadata candidate when original URL, retrieval time, and checksum are preserved.
- Baostock remains candidate external data until dataset-level upstream provenance is documented.
- AKShare is deferred for Phase 3 when upstream is unavailable or dataset-level provenance is not explicit.
- FRED remains retry/defer if public CSV access times out.
