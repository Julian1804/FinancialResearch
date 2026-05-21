# Entity Master and Identifier Crosswalk v1

Generated: 2026-05-21T04:25:06Z

Entity Master v1 defines a shared identifier layer for equity, fund/ETF, index, commodity/futures and macro series data.
Every ingestion run should attempt an `entity_id` mapping before staging. Unmapped identifiers go to
`runtime/automated_ingestion_system/unresolved_entity_queue.json`.

Current seed inventory:
- Entities: 70
- Crosswalk entries: 96
- Unresolved queue: 30
- Duplicate risks: 0

Merge guards:
- Same ticker in different exchanges is not auto-merged.
- Fund fuzzy-name matches are probable_match only.
- Commodity benchmark, spot and futures instruments are separate entities.
- Morningstar identifiers remain licensed-source candidate identifiers until license and validation checks pass.
