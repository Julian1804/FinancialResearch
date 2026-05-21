{
  "generated_at": "2026-05-21T05:34:17Z",
  "a_share": {
    "summary": {
      "comparison_count": 90,
      "overall_match_counts": {
        "numeric_tolerance_match": 89,
        "mismatch": 1
      },
      "ohlc_exact_matches": 360,
      "expected_ohlc_matches": 360,
      "volume_matches": 90,
      "pct_change_mismatches": 1,
      "status": "cross_validated_candidate",
      "datasets_upgraded": [
        "baostock_daily",
        "akshare_tencent_daily"
      ],
      "trusted_consumption": false
    },
    "field_summary": {
      "open": {
        "exact_match": 90
      },
      "high": {
        "exact_match": 90
      },
      "low": {
        "exact_match": 90
      },
      "close": {
        "exact_match": 90
      },
      "volume": {
        "unit_normalized_match": 90
      },
      "amount": {
        "missing_in_source": 90
      },
      "pct_change": {
        "missing_in_source": 3,
        "numeric_tolerance_match": 84,
        "exact_match": 2,
        "mismatch": 1
      }
    },
    "quality_reference": {
      "generated_at": "2026-05-19T13:16:59Z",
      "items": [
        {
          "quality_check_id": "quality_c0b26c5f0f1df0c2",
          "source_id": "baostock_daily",
          "status": "quality_passed",
          "record_count": 90,
          "checks": {
            "required_fields_present": true,
            "symbol_trade_date_unique": true,
            "duplicate_date_check": true,
            "date_order": true,
            "ohlc_numeric": true,
            "high_ge_max_olc": true,
            "low_le_min_och": true,
            "volume_non_negative": true,
            "amount_non_negative": true,
            "pct_change_reasonable_range": true,
            "turnover_rate_reasonable_range": true
          },
          "warnings": [],
          "candidate_only": true
        },
        {
          "quality_check_id": "quality_b9bdc286058c3c05",
          "source_id": "akshare_tencent_daily",
          "status": "quality_passed",
          "record_count": 90,
          "checks": {
            "required_fields_present": true,
            "symbol_trade_date_unique": true,
            "duplicate_date_check": true,
            "date_order": true,
            "ohlc_numeric": true,
            "high_ge_max_olc": true,
            "low_le_min_och": true,
            "volume_non_negative": true,
            "amount_non_negative": true,
            "pct_change_reasonable_range": true,
            "turnover_rate_reasonable_range": true
          },
          "warnings": [
            "amount_source_not_supported",
            "turnover_rate_source_not_supported",
            "trade_status_source_not_supported",
            "is_st_source_not_supported"
          ],
          "candidate_only": true
        }
      ],
      "summary": {
        "quality_passed": 2,
        "quality_failed": 0
      }
    },
    "limitation": "AKShare Tencent tested interface lacks transaction amount; one pct_change mismatch remains review-only."
  },
  "macro_rates": {
    "summary": {
      "fred_rate_series_checked": 3,
      "treasury_fiscaldata_series_checked": 22,
      "direct_cross_source_matches": 0,
      "freshness_validated_candidates": 25,
      "status": "freshness_validated_candidate",
      "limitation": "Treasury FiscalData average interest rates are not the same instrument as FRED DGS par yields, so exact numerical matching is not required."
    },
    "items": [
      {
        "dataset_id": "fred_public_api:DGS10",
        "series_id": "DGS10",
        "source_id": "fred_public_api",
        "latest_observation": "2026-05-18",
        "quality_status": "pending_quality",
        "validation_status": "freshness_validated_candidate",
        "cross_source_note": "FRED Treasury market-yield series is conceptually related to, but not identical with, Treasury FiscalData average interest-rate series."
      },
      {
        "dataset_id": "fred_public_api:DGS2",
        "series_id": "DGS2",
        "source_id": "fred_public_api",
        "latest_observation": "2026-05-18",
        "quality_status": "pending_quality",
        "validation_status": "freshness_validated_candidate",
        "cross_source_note": "FRED Treasury market-yield series is conceptually related to, but not identical with, Treasury FiscalData average interest-rate series."
      },
      {
        "dataset_id": "fred_public_api:DFF",
        "series_id": "DFF",
        "source_id": "fred_public_api",
        "latest_observation": "2026-05-18",
        "quality_status": "pending_quality",
        "validation_status": "freshness_validated_candidate",
        "cross_source_note": "FRED Treasury market-yield series is conceptually related to, but not identical with, Treasury FiscalData average interest-rate series."
      }
    ],
    "treasury_reference_count": 22
  },
  "commodity": {
    "summary": {
      "benchmark_pairs_checked": 1,
      "status": "schema_validated_candidate",
      "benchmark_spot_futures_guard": true,
      "cross_validated_candidate_count": 0,
      "limitation": "Commodity comparisons are benchmark-level only; World Bank benchmark, FRED spot and futures must stay separate instruments."
    },
    "items": [
      {
        "comparison_id": "oil_wti",
        "fred_series_id": "DCOILWTICO",
        "world_bank_series_id": "CRUDE_WTI",
        "fred_latest_date": "2026-05-11",
        "world_bank_latest_date": "2026-04-01",
        "fred_value": 101.56,
        "world_bank_value": 98.63,
        "difference_pct": 2.970698570414688,
        "validation_status": "benchmark_level_comparison_candidate",
        "limitation": "FRED WTI spot and World Bank WTI benchmark/monthly data are related but not identical; do not mix with futures."
      }
    ]
  }
}