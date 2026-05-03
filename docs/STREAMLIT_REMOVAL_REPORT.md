# Streamlit Removal Report

Generated at: 2026-05-03

## Deleted Directory

```text
app/
```

## Safety Check

Deletion was performed only on branch:

```text
refactor/parse-lab-api-integration
```

Before deletion, `app/` existed in the current worktree. Its first-level contents were recorded in `docs/LOCAL_PROJECT_INVENTORY.md` as:

```text
app/
  agents/
  config/
  models/
  pages/
  services/
  utils/
  main.py
  __init__.py
```

The old code is not copied to `legacy_archive`; it remains recoverable from GitHub main/master history or local Git history.

## Reason

The old `app/` directory contained the Streamlit monolith. The new branch is refactoring FinancialResearch into a FastAPI + React modular platform, so the Streamlit application is removed from the current worktree.

## Inventory

The old project structure was recorded before removal in:

```text
docs/LOCAL_PROJECT_INVENTORY.md
```

## Recovery

The old code can be restored from Git history or the GitHub remote repository if needed.

## Legacy Policy

No `legacy_archive` directory is created.

The legacy Streamlit project is not retained in the new architecture and will not be maintained going forward.

The following files were intentionally preserved for later cleanup:

- `.gitignore`
- `README.md`
- `requirements.txt`
- `requirements-forecast.txt`

## Legacy Streamlit Lessons

The old Streamlit implementation was removed because the project has moved beyond prototype mode. The major lessons were around UI stability, long-running parser tasks, cancel/hung state handling, log/task status drift, resource pressure from heavy parsers, and tight coupling between pages and business logic.

The full review is documented in:

```text
docs/STREAMLIT_LEGACY_ISSUES_AND_REFACTOR_LESSONS.md
```

Future UI work should not reintroduce parser execution or long-running task ownership into the frontend runtime.
