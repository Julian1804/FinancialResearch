# Morningstar Direct Feasibility Audit

Generated at: 2026-05-20T10:00:31Z

## Scope

Morningstar Direct / Analytics Lab is treated as a licensed authorized platform, not a public free source. This audit validates safe local integration with a user-copied 24-hour authentication token only.

## Security Boundary

- Auto login: no.
- Password storage: no.
- Browser automation: no.
- MFA/SSO bypass: no.
- Token logging: no; only masked token status is recorded.
- Full backfill: no until entitlement and redistribution review.
- Formal trusted consumption: not affected.

## Current Status

- Token status: available.
- Masked token: ****PwqA.
- Package installed: True (1.13.0).
- Import OK: True.
- Smoke status: success.
- Entitlement assessment: at_least_one_small_request_authorized.

## Source Policy

- source_id: morningstar_direct
- source_type: licensed_authorized_platform
- access_method: morningstar_data_python / direct_web_services / api_center
- api_allowed: manual_token_required
- crawler_allowed: False
- token_expiry: 24h
- redistribution_status: needs_review
- raw_storage_allowed: needs_user_confirmation
- trust_status: licensed_source_candidate

## Next Gate

Before any raw data storage or larger retrieval, confirm Morningstar entitlement, redistribution limits, and whether local raw storage is allowed for the intended dataset.
