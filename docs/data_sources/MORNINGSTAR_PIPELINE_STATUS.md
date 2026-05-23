# Morningstar Pipeline Status

## Current Status

Morningstar is `ready_for_operational_manual_updates`.

It is a licensed institutional data platform, not a public free source. FR does not auto-login, does not store Morningstar passwords, and does not print or commit tokens.

## Manual Update Flow

```text
Dashboard
-> user pastes Morningstar token
-> save token locally in ignored local_secrets
-> click Morningstar Database Update
-> backend scans latest_data_date
-> compute latest_available_data_date
-> look back three effective data/open days
-> collect/update snapshot
-> same-date latest_collected_wins
-> write snapshot / manifest / QA / failure_log / dashboard summary
```

## Completed Capabilities

- Token UI input.
- Token status display.
- Manual update framework.
- Latest data date scan.
- Snapshot history mechanism.
- Capital Flow Exposure Data Product v1.
- Time-Series Readiness.
- Direction Evidence Hardening.
- Underlying Entity Enrichment.
- Exposure Derivation.
- Dashboard lightweight summary.

## Important Boundaries

- Non-China stocks are entity shells only; no non-China equity time series are collected by default.
- TNA/ENF remains sidecar and blocked by `blocked_unit_scale_unknown`.
- Flow proxy remains `proxy_not_actual_flow`, not actual flow.
- Morningstar data products remain candidate/preview unless a later explicit promotion opens a stronger status.
- Formal trusted consumption remains off.

## Operational Notes

The Morningstar update flow is user-triggered. It is not a daemon and not a hidden crawler. Token refresh is a user action. Any storage or license-boundary expansion must be explicit.

