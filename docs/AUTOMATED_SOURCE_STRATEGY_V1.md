# Automated Source Strategy v1

Generated: 2026-05-21T04:25:06Z

FR automation is catalog and source-status driven. Manual import remains a validation fallback, not the long-term mainline.

Source status counts:
{
  "enabled": 3,
  "controlled_candidate": 2,
  "aggregate_only": 1,
  "on_hold": 2,
  "deferred_retry_needs_key_or_later_retry": 1,
  "enabled_candidate": 2,
  "deferred": 2
}

Official sources with stable API/file endpoints are `official_automated`. Official sources with captcha/login/unclear endpoint
or terms are `official_on_hold`. AKShare/Baostock wrappers and Morningstar licensed datasets are candidate sources and must
pass quality, coverage, freshness, field, cross-source and license checks before trust upgrade.
