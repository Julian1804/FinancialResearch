# FR Custom Connector Layer Design

## Name

`FRDataConnectors`

## Principle

Do not clone AKShare. Implement only FinancialResearch adapters with raw preservation, normalization, quality gates, trust status, fallback, and cross-source validation.

## Adapters

| Adapter | Role | Trust |
|---|---|---|
| BaostockDailyAdapter | operational_source | candidate_external_data |
| AKShareAdapter | priority_repair_source_optional_if_unstable | candidate_external_data |
| EastmoneyDirectAdapter | deferred_secondary_validation_source | candidate_external_data |
| CNINFODisclosureAdapter | financial_report_discovery | trusted_by_official_source_candidate |
| FREDAdapter | official_macro_source | trusted_by_real_external_candidate |
| BLSAdapter | official_macro_source | trusted_by_real_external_candidate |
| TreasuryFiscalDataAdapter | official_macro_source | trusted_by_real_external_candidate |
| WorldBankPinkSheetAdapter | official_commodity_source | trusted_by_real_external_candidate |

## Shared Contract

```json
{
  "input": [
    "watchlist",
    "metrics_registry",
    "source_registry",
    "storage_paths"
  ],
  "output": [
    "raw_output_path",
    "normalized_output_path",
    "quality_result",
    "trust_status",
    "candidate_only",
    "failure_mode"
  ],
  "storage": "NAS-first raw and structured storage with local runtime mirrors",
  "quality_gate": "required before consumption-grade staging",
  "formal_trusted_consumption": "not modified by connector layer"
}
```
