# Text Parsing Quality Review Plan

## Scope

This review pack audits existing parsed text quality before expanding `trusted_by_text` usage. It does not rerun the parser, optimize table parsing, change Parse Lab routing, or create a report/forecast/backtest.

## Sampling Target

Target sample size: 150-250 text snippets.

The generator draws from existing Parse Lab and FinancialResearch runtime exports:

- Round3 field candidate evidence text.
- Round3 review queue evidence text.
- Parse QA issue excerpts.
- Existing parsed page text from `pages.jsonl`.

High-risk samples are prioritized for manual review, while low-risk samples are retained for spot checks and AI pre-check accuracy measurement.

## Coverage

Samples are tagged across:

- Financial numeric text: revenue, profit, margin, cost, expense, cash flow, assets, liabilities, equity, amounts, percentages, growth, period, currency, unit.
- Financial explanation text: revenue growth reasons, cost changes, margin changes, cash-flow explanations, asset/liability changes, operating risk.
- Sentiment / management / strategy text: management statements, strategic shifts, market outlook, operating risk, qualitative future-facing statements.
- Complex language: negatives, conditions, uncertainty, year-on-year direction, multiple numbers, multiple periods, mixed Chinese/English, Traditional Chinese HK disclosure style, OCR line breaks.

## AI Pre-check

Each sample receives an AI-style deterministic pre-check with:

- parsed text completeness.
- OCR / line break / sentence boundary risks.
- number recognition risk.
- unit / currency / percentage risk.
- period recognition risk.
- growth direction risk.
- negative or condition preservation risk.
- sentiment or strategy summary.
- trusted-by-text candidate flag.
- risk labels.

Risk labels include:

- `numeric_parse_risk`
- `unit_currency_risk`
- `period_risk`
- `growth_direction_risk`
- `negative_or_condition_missing_risk`
- `sentence_boundary_risk`
- `mixed_language_risk`
- `sentiment_or_strategy_summary_risk`
- `missing_context_risk`
- `hallucinated_summary_risk`
- `normalization_loss_risk`
- `low_risk`

## Manual Review

The review pack includes:

- raw text.
- parsed text.
- normalized text as a derived field only.
- normalization diff / warnings.
- AI summary.
- AI pre-check snapshot.
- risk labels.
- human review fields displayed next to the AI judgment.

Human review captures:

- trusted-by-text eligibility.
- numeric correctness.
- unit / currency / percentage correctness.
- period correctness.
- overall meaning correctness.
- AI summary accuracy.
- not-trusted reason.
- regression-set recommendation.
- reviewer notes.

Saved human review data preserves the raw text, parsed text, normalized text, normalization audit, and AI pre-check snapshot. The static review UI saves locally for navigation and exports reviewed rows as JSON or JSONL so later ingest can compute AI-human disagreement categories such as numeric error missed, unit/currency error missed, period error missed, summary over-interpreted, summary hallucinated, false high-risk, and false low-risk.

## Trust Rule

Financial report text is not automatically trusted. A text snippet can only become `trusted_by_text` after passing the text quality gate. Strategy and sentiment summaries are interpretation candidates and never replace original evidence text.

`raw_text` is the source evidence and must not be overwritten. `normalized_text` is only a derived convenience field; if normalization removes numbers, units/currency/percentages, periods, negative words, or conditional expressions, the item is tagged with `normalization_loss_risk` and requires review before it can support trust resolution.
