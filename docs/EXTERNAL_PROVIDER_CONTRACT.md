# External Provider Contract

## Purpose

FinancialResearch canonical facts can be trusted from three source classes:

- `trusted_by_text`: financial report text evidence.
- `trusted_by_real_external`: real external financial data providers.
- `trusted_by_simulated_external`: deterministic mock provider data for dev/test only.

Production analysis consumption must not use simulated external data.

## Provider Interface

External providers implement `ExternalFinancialDataProvider` and return `ExternalProviderFact` records.

Required provider metadata for every external fact:

- `provider_name`
- `provider_type`
- `retrieved_at`
- `source_url_or_reference`
- `is_simulated`

Real providers such as Eastmoney, Tonghuashun, Morningstar, or Wind should use:

- `provider_type = "real_external_provider"`
- `is_simulated = false`
- `trust_status = "trusted_by_real_external"`

Real external data must come from an authoritative institution's official website or officially licensed API. Examples include official Eastmoney, Tonghuashun, Morningstar, Wind, exchange, regulator, or issuer data interfaces where usage rights are clear.

Media reposts, forums, public-account articles, social media posts, scraped screenshots, and second-hand summaries must not be used as `trusted_by_real_external` sources. They may be retained only as untrusted reference material or routed to a separate review/crawler workflow.

Future crawler work should live in a dedicated official-data acquisition project with provider-specific authentication, rate limits, source URLs, retrieval timestamps, and licensing notes.

The built-in mock provider uses:

- `provider_name = "simulated_authoritative_external_provider"`
- `provider_type = "mock_external_provider"`
- `is_simulated = true`
- `trust_status = "trusted_by_simulated_external"`

## Consumption Modes

Production mode allows only:

- `trusted_by_text`
- `trusted_by_real_external`

Dev/test mode allows:

- `trusted_by_text`
- `trusted_by_real_external`
- `trusted_by_simulated_external`

## Guardrail

Simulated external facts are written for workflow testing but excluded by default from production analysis consumption. Table candidates remain candidate-only unless independently validated by text or real external data.
