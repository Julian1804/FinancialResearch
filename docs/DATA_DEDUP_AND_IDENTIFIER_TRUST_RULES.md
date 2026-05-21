# Data Dedup and Identifier Trust Rules

- Morningstar, AKShare, Eastmoney, Tonghuashun and similar third-party sources are candidate by default.
- Official or authoritative sources may become trusted_candidate only after QA and source-role validation.
- All stock, fund, ETF and futures data must keep exchange or official identifiers.
- Same code in different markets is not the same entity.
- Different source aliases for one entity must be mapped through Entity Master.
- Commodity benchmark, spot, futures and index data must not be mixed.
- Fund flow proxy is not actual flow unless the source explicitly defines net flow.
- Revised data must keep revision/vintage records and must not overwrite prior snapshots.
