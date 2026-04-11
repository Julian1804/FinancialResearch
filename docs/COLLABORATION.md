# Collaboration Guide

This document defines how contributors should work on the Financial Research Assistant project.

## 1. Working principles

This project is a long-horizon research system, not a one-off chat app. Contributions must protect:

- time-series integrity
- separation of primary financial reports vs auxiliary materials
- structured outputs and traceability
- backward compatibility where possible
- explainability over cleverness

If a change makes outputs look more impressive but weakens reproducibility or temporal consistency, do not merge it.

## 2. Recommended branching model

Suggested branches:

- `main`: stable branch, only reviewed and tested changes
- `dev`: integration branch for ongoing development
- `feature/<name>`: new features
- `fix/<name>`: bug fixes
- `refactor/<name>`: internal cleanup without intended behavior change
- `docs/<name>`: documentation-only changes

Examples:

- `feature/task-runtime-registry`
- `fix/update-json-repair`
- `refactor/parser-page-routing`
- `docs/github-onboarding`

## 3. Commit message suggestions

Use short, clear commit messages.

Recommended patterns:

- `feat: add company profile manual override flow`
- `fix: prevent auxiliary materials entering actuals`
- `refactor: split llm gateway from agent routing`
- `docs: update architecture and workflow notes`
- `test: add parser regression fixtures`

A good commit should make it obvious:

- what changed
- why it changed
- whether schemas or historical outputs are affected

## 4. Pull request checklist

Every pull request should answer these questions:

1. What problem does this change solve?
2. Which modules are affected?
3. Does it change any JSON schema or file naming rule?
4. Does it affect historical data compatibility?
5. Does it alter the distinction between primary and auxiliary materials?
6. What should reviewers test manually?
7. Are there screenshots or sample outputs if UI behavior changed?

Recommended PR sections:

- Background
- Scope of change
- Files touched
- Risk / compatibility notes
- Manual test steps
- Follow-up tasks

## 5. High-risk areas

Changes in these areas require extra review:

### 5.1 Schema and registry changes

Any change to:

- `parsed_*.json`
- `extracted_*.json`
- `report_*.json`
- `delta_*.json`
- `forecast_check_*.json`
- profile registries / workflow registries / task registries

must include:

- compatibility notes
- migration plan if needed
- sample before/after payloads

### 5.2 Time-series logic

Any change touching:

- `report_type`
- `document_type`
- `period_key`
- `is_primary_financial_report`
- `can_adjust_forecast`
- material timeline ordering

must be reviewed carefully. These fields are foundational.

### 5.3 Primary vs auxiliary classification

Never allow these to collapse into one category.

Examples of auxiliary materials:

- earnings release
- earnings presentation
- investor communication
- operational update
- management deck
- call notes

Even when an auxiliary document contains nearly final FY figures, it must not replace a primary FY report in actuals.

### 5.4 Forecast / backtest logic

Any change to forecasting or forecast-check logic must specify:

- whether the statistical model path changed
- whether any AI explanation path changed
- whether bias attribution logic changed
- whether old backtests remain interpretable

## 6. Testing expectations

At minimum, contributors should test the parts they changed.

Recommended manual test layers:

### UI layer

- page loads without immediate exceptions
- task progress displays correctly
- user selections behave as expected
- formal and debug flows remain separate

### Data layer

- output files are created in the expected folder
- naming remains stable
- no unintended overwrite occurs
- existing historical files still load

### Research logic layer

- primary materials remain primary
- auxiliary materials remain auxiliary
- actuals are not polluted by auxiliary data
- company profile refresh behavior is correct
- manual overrides are preserved

### LLM layer

- bad JSON outputs are handled gracefully
- fallback / repair logic works
- profile routing behaves as configured

## 7. Recommended review mindset

Reviewers should not only ask “does it run?” They should also ask:

- does it preserve temporal integrity?
- does it introduce hidden coupling?
- does it weaken traceability?
- will it confuse future contributors?
- can the result be backtested and explained later?

## 8. Data safety and security

Never commit:

- `.env`
- real API keys
- private PDFs unless explicitly intended
- local user data
- local task runtime dumps
- machine-specific cache directories

Before pushing, always check:

- no secrets in config files
- no local paths hardcoded
- no large raw data directories accidentally staged

## 9. Recommended onboarding order for new contributors

New contributors should read in this order:

1. `README.md`
2. `docs/ARCHITECTURE.md`
3. `docs/RESEARCH_FRAMEWORK.md`
4. `docs/ROADMAP.md`
5. this file

Only after that should they start modifying code.

## 10. Decision rule when uncertain

If unsure whether a change belongs in the formal flow or only in the debug flow:

- put it in debug first
- stabilize it
- promote it to formal flow later

If unsure whether a field belongs in actuals:

- keep it out of actuals
- retain it as contextual or auxiliary information
- only elevate it after explicit review
