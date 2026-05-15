# Parse Lab Round3 Trust Resolution Prototype Report

## Scope

This prototype consumes the existing Parse Lab Round3 provisional field facts from:

`runtime/financial_report/provisional_facts/parse_lab_round3`

It does not modify Parse Lab, does not change the default V1.1 parsing flow, and does not promote Parse Lab table-derived candidates directly into final facts.

## Trust Policy

FinancialResearch analysis, forecasting, backtesting, and decision-support consumers must read only trusted facts. Candidate-only records may be retained for traceability and later review, but they are excluded from the analysis consumption payload.

The trust statuses are:

- `trusted_by_text`: core financial field matched to financial report text evidence.
- `trusted_by_external`: core financial field matched by the simulated authoritative external provider.
- `validated_candidate`: text/table validation passed, but the field is not a core financial fact for analysis consumption.
- `candidate_only`: retained as provisional data and excluded from analysis consumption.
- `needs_human_review`: core financial field that cannot be automatically trusted by text or external validation.
- `rejected`: explicit conflicts or rejected candidates.

## Core Field Rule

Core fields are recognized when `field_name` or `evidence_text` contains financial statement terms for revenue, profit, loss, income, assets, liabilities, equity, cash, cost, expense, or Chinese equivalents such as 收入、收益、利润、利潤、资产、資產、负债、負債、权益、權益、现金、現金、成本、费用、費用.

Obvious share-award or administrative labels, such as participant, employee, vesting, share award, 相關獎勵對象, 獎勵股份, 归属, and 歸屬, are excluded from core-field classification.

## External Provider

The prototype uses a deterministic simulated authoritative provider. It does not crawl 东方财富、同花顺、晨星、Wind, or other external services. The simulated provider only promotes numeric, core, partially matched fields when the field context matches a small set of financial-statement keywords.

## Output

Output directory:

`runtime/financial_report/trust_resolution/parse_lab_round3`

Generated files:

- `trusted_facts.json`
- `validated_candidates.json`
- `candidate_only_facts.json`
- `needs_human_review.json`
- `rejected_facts.json`
- `analysis_consumption_trusted_facts.json`
- `trust_resolution_summary.json`

Only `analysis_consumption_trusted_facts.json` is intended for formal FinancialResearch consumption.

## Prototype Result

Input provisional facts: 273

Trust resolution result:

- `trusted_by_text`: 80
- `trusted_by_external`: 2
- `validated_candidate`: 177
- `candidate_only`: 10
- `needs_human_review`: 4
- `rejected`: 0

Trusted facts total: 82

Core fields: 86

Non-core fields: 187

## Consumption Guardrail

The analysis consumption function `load_trusted_facts_for_analysis()` reads only `analysis_consumption_trusted_facts.json` and returns only records with:

- `trusted=true`
- `trust_status in {"trusted_by_text", "trusted_by_external"}`
- `candidate_only=false`

This prevents `candidate_only`, `validated_candidate`, and `needs_human_review` records from entering formal analysis.

## Test

Prototype test:

`python scripts\test_parse_lab_round3_trust_resolution.py`

The test asserts that trusted and candidate data are disjoint, analysis consumption only returns trusted records, `needs_human_review` contains only core fields, and Parse Lab remains unmodified.
