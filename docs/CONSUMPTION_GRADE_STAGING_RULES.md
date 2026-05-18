# Consumption-grade Staging Rules

## Staging Is Not Formal Trusted Consumption

Phase 3 staging is a pre-consumption holding layer. It does not modify the formal FinancialResearch trusted consumption path.

## Rules

- `consumption_grade_candidate`: official/authoritative source plus `quality_passed`.
- `review_candidate`: quality passed but source provenance is not yet sufficient, or quality warning that must not enter consumption-grade.
- `defer`: connector failed or quality failed.

## Explicit Exclusions

- `quality_warning` does not enter consumption-grade.
- `quality_failed` does not enter consumption-grade.
- Baostock and AKShare do not become consumption-grade without dataset-level provenance.
- Media reposts, forums, public-account reposts, and second-hand commentary are not trusted external sources.
