# GitHub Main Platform Replacement Report

Generated at: 2026-05-08

## Summary

GitHub `main` for `https://github.com/Julian1804/FinancialResearch` has been updated from the legacy Streamlit financial-report system to the modular FinancialResearch platform architecture.

This was an engineering architecture upgrade, not a replacement of the existing financial-report research methodology.

## Backup Tag

The previous remote `main` was preserved with:

```text
backup/main-before-platform-refactor-20260508
```

Tag target:

```text
cf19183a8b402bdcabf888dfc0864554f46e9588
```

## Merge Source

Source branch:

```text
refactor/parse-lab-api-integration
```

Merge commit:

```text
2d85a58b2456574892e8580b9bcaec5b787200f3
```

Commit message:

```text
refactor: replace legacy Streamlit app with modular financial research platform
```

## Push Result

Push to GitHub `main` succeeded:

```text
cf19183..2d85a58  main -> main
```

Remote `main` after push:

```text
2d85a58b2456574892e8580b9bcaec5b787200f3 refs/heads/main
```

## Remote Verification

A shallow clone of GitHub `main` was created for verification.

Verified:

- `backend/` exists.
- `frontend_web/` exists.
- `requirements/` exists.
- `scripts/` exists.
- `docs/` exists.
- `README.md` exists.
- legacy `app/` does not exist.

## README Verification

`README.md` now describes FinancialResearch as a personal investment research integration platform, progressively covering:

- financial-report research,
- macro research,
- sentiment analysis,
- market data / commodities / index / FX / rates tracking,
- research repository,
- decision support.

It also documents:

- `backend/` as the FastAPI backend,
- `frontend_web/` as the future React/Vite dashboard frontend,
- Parse Lab as a separate PDF parsing service accessed by HTTP API,
- the old Streamlit app removal rationale.

## Methodology Preservation

The platform refactor does not discard the original financial-report analysis methodology.

The README keeps the core financial-report framework:

1. industry positioning,
2. macro environment,
3. company overview,
4. cost structure,
5. customer structure,
6. profit model,
7. capital flow,
8. future outlook,
9. moat,
10. risk + expectations.

The README also preserves the distinction between primary financial reports and auxiliary materials:

- annual / semiannual / quarterly reports may be expected to contain the three financial statements;
- earnings releases, announcements, briefings, press releases, presentations, and call transcripts must not be failed solely for missing the three statements.

## Parse Lab Boundary

Parse Lab remains outside the FinancialResearch repository.

FinancialResearch:

- calls Parse Lab through HTTP API,
- does not import Parse Lab parser internals,
- does not vendor Marker / MinerU / Surya / Docling / PaddleOCR parser code,
- owns research workflow, review decisions, extraction eligibility, analysis, forecasting, backtesting, and dashboard concerns.

Parse Lab:

- owns PDF parsing,
- page-level routing,
- table recovery,
- cross-page table candidates,
- quality flags,
- parser QA.

## Safety Checks

Sensitive string scan found only placeholder/documentation references:

- `.env.example` contains empty `ALIYUN_API_KEY` and `DEEPSEEK_API_KEY` placeholders.
- `.gitignore` references secret-related patterns.
- documentation contains generic “no secrets” wording.

No real API key, password, token, bearer credential, private key, or access key was detected.

No large files over 10 MB were found in the commit scope.

The following local artifacts were confirmed ignored and not pushed:

- `runtime/`
- `__pycache__/`
- `*.pyc`
- backend smoke logs
- local editor/runtime leftovers

No PDF, `.env`, virtual environment, `node_modules`, or frontend build artifact entered tracked files.

## Validation

Basic validation performed after merge:

```text
python -m py_compile backend/app/main.py
```

Result: passed.

No parser jobs were run. No Parse Lab source code was modified.

## Final State

GitHub `main` now represents the modular FinancialResearch platform skeleton:

- legacy Streamlit `app/` removed,
- FastAPI backend present,
- React/Vite frontend placeholder present,
- modular financial-research backend module layout present,
- Parse Lab API integration documents and dry-run financial extraction prototype documents present,
- automated validation and human-review-pack scripts present.

