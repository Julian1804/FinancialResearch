# Analysis Packet Builder v2 Report

Generated: 2026-05-19T13:46:54Z

## Result

- Packet count: 2
- Targets: 600519, 000001
- OpenAI API called: false
- Formal trusted consumption affected: false

## Data Sources

- FRDataConnectors metadata index: `D:\workspace\FinancialResearch\runtime\frdata_connectors_phase6\frdata_connectors_metadata.sqlite`
- Staging v2: `D:\workspace\FinancialResearch\runtime\frdata_connectors_phase6\consumption_grade_staging_v2.json`
- Connector run results: `D:\workspace\FinancialResearch\runtime\frdata_connectors_phase6\connector_run_results.json`

## Outputs

```json
[
  {
    "packet_id": "packet_554b196c683dca80",
    "data_snapshot_id": "snapshot_dc8a920ca2a06b8d",
    "target_symbol": "600519",
    "market": "A_SHARE",
    "as_of_date": "2026-05-19",
    "analysis_scope": "daily_update",
    "created_at": "2026-05-19T13:46:54Z",
    "paths": {
      "analysis_packet_json": "D:\\workspace\\FinancialResearch\\runtime\\analysis_packet_builder_v2\\600519\\analysis_packet.json",
      "analysis_packet_md": "D:\\workspace\\FinancialResearch\\runtime\\analysis_packet_builder_v2\\600519\\analysis_packet.md",
      "copy_to_gpt_prompt": "D:\\workspace\\FinancialResearch\\runtime\\analysis_packet_builder_v2\\600519\\copy_to_gpt_prompt.md",
      "packet_manifest": "D:\\workspace\\FinancialResearch\\runtime\\analysis_packet_builder_v2\\600519\\packet_manifest.json"
    },
    "source_counts": {
      "source_layers": 11,
      "insufficient_evidence": 3
    },
    "no_openai_api_called": true,
    "formal_trusted_consumption": false
  },
  {
    "packet_id": "packet_037d933cc0a51671",
    "data_snapshot_id": "snapshot_32b10f87daaca8fb",
    "target_symbol": "000001",
    "market": "A_SHARE",
    "as_of_date": "2026-05-19",
    "analysis_scope": "daily_update",
    "created_at": "2026-05-19T13:46:54Z",
    "paths": {
      "analysis_packet_json": "D:\\workspace\\FinancialResearch\\runtime\\analysis_packet_builder_v2\\000001\\analysis_packet.json",
      "analysis_packet_md": "D:\\workspace\\FinancialResearch\\runtime\\analysis_packet_builder_v2\\000001\\analysis_packet.md",
      "copy_to_gpt_prompt": "D:\\workspace\\FinancialResearch\\runtime\\analysis_packet_builder_v2\\000001\\copy_to_gpt_prompt.md",
      "packet_manifest": "D:\\workspace\\FinancialResearch\\runtime\\analysis_packet_builder_v2\\000001\\packet_manifest.json"
    },
    "source_counts": {
      "source_layers": 11,
      "insufficient_evidence": 2
    },
    "no_openai_api_called": true,
    "formal_trusted_consumption": false
  }
]
```
