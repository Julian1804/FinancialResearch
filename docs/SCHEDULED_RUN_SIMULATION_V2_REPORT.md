{
  "generated_at": "2026-05-21T05:34:17Z",
  "summary": {
    "tasks_total": 9,
    "executed_count": 5,
    "dry_run_count": 0,
    "deferred_or_on_hold_count": 3,
    "controlled_audit_count": 1,
    "daily_group_executed": true,
    "monthly_group_executed": true,
    "weekly_or_on_demand_morningstar_audit": true,
    "quarterly_group_dry_run": true
  },
  "tasks": [
    {
      "dataset_id": "baostock_a_share_daily",
      "source_id": "baostock",
      "update_frequency": "daily",
      "scheduled_action": "executed_cached_or_incremental_check",
      "enabled": true,
      "blocker": null,
      "next_suggested_run_at": "2026-05-22T05:34:17Z"
    },
    {
      "dataset_id": "akshare_tencent_a_share_daily",
      "source_id": "akshare_tencent",
      "update_frequency": "daily",
      "scheduled_action": "executed_cached_or_incremental_check",
      "enabled": true,
      "blocker": null,
      "next_suggested_run_at": "2026-05-22T05:34:17Z"
    },
    {
      "dataset_id": "fred_rates_macro",
      "source_id": "fred",
      "update_frequency": "daily/monthly",
      "scheduled_action": "executed_cached_or_incremental_check",
      "enabled": true,
      "blocker": null,
      "next_suggested_run_at": "2026-05-22T05:34:17Z"
    },
    {
      "dataset_id": "treasury_yields",
      "source_id": "us_treasury_fiscaldata",
      "update_frequency": "daily",
      "scheduled_action": "executed_cached_or_incremental_check",
      "enabled": true,
      "blocker": null,
      "next_suggested_run_at": "2026-05-22T05:34:17Z"
    },
    {
      "dataset_id": "world_bank_pink_sheet",
      "source_id": "world_bank_pink_sheet",
      "update_frequency": "monthly",
      "scheduled_action": "executed_cached_or_incremental_check",
      "enabled": true,
      "blocker": null,
      "next_suggested_run_at": "2026-06-20T05:34:17Z"
    },
    {
      "dataset_id": "morningstar_us_etf_symbol_search",
      "source_id": "morningstar_direct",
      "update_frequency": "weekly_or_on_demand",
      "scheduled_action": "controlled_audit_only",
      "enabled": false,
      "blocker": "license/storage/coverage boundary not cleared",
      "next_suggested_run_at": "2026-05-28T05:34:17Z"
    },
    {
      "dataset_id": "amac_individual_fund_universe",
      "source_id": "amac_individual_fund_universe",
      "update_frequency": "monthly",
      "scheduled_action": "deferred_or_on_hold",
      "enabled": false,
      "blocker": "stable automated endpoint not confirmed",
      "next_suggested_run_at": "2026-06-20T05:34:17Z"
    },
    {
      "dataset_id": "bls_macro",
      "source_id": "bls_public_api",
      "update_frequency": "monthly",
      "scheduled_action": "deferred_or_on_hold",
      "enabled": false,
      "blocker": "public API threshold/API key needed",
      "next_suggested_run_at": "2026-06-20T05:34:17Z"
    },
    {
      "dataset_id": "fund_quarterly_holdings",
      "source_id": "morningstar_direct_or_official_reports",
      "update_frequency": "quarterly",
      "scheduled_action": "deferred_or_on_hold",
      "enabled": false,
      "blocker": "source/license validation required",
      "next_suggested_run_at": "2026-08-19T05:34:17Z"
    }
  ]
}