{
  "generated_at": "2026-05-21T05:34:17Z",
  "summary": {
    "schema_validated": 1,
    "cross_validated": 2,
    "freshness_validated": 1,
    "ready_for_trusted": 0,
    "trusted_candidate": 0,
    "blocked": 0
  },
  "items": [
    {
      "dataset_id": "baostock_daily",
      "source_id": "baostock",
      "status": "cross_validated_candidate",
      "missing_for_trusted_candidate": [
        "official exchange benchmark",
        "longer freshness window",
        "license/source provenance review"
      ]
    },
    {
      "dataset_id": "akshare_tencent_daily",
      "source_id": "akshare_tencent",
      "status": "cross_validated_candidate",
      "missing_for_trusted_candidate": [
        "official exchange benchmark",
        "AKShare upstream provenance review"
      ]
    },
    {
      "dataset_id": "fred_treasury_rates",
      "source_id": "fred_public_api",
      "status": "freshness_validated_candidate",
      "missing_for_trusted_candidate": [
        "publish_date/release calendar for as-of safety"
      ]
    },
    {
      "dataset_id": "commodity_benchmark",
      "source_id": "world_bank_pink_sheet/fred",
      "status": "schema_validated_candidate",
      "missing_for_trusted_candidate": [
        "benchmark/spot/futures separation remains explicit",
        "publish_date unavailable for World Bank rows"
      ]
    },
    {
      "dataset_id": "morningstar_controlled_candidates",
      "source_id": "morningstar_direct",
      "status": "controlled_candidate",
      "missing_for_trusted_candidate": [
        "license boundary",
        "official benchmark coverage",
        "freshness",
        "field completeness"
      ]
    }
  ]
}