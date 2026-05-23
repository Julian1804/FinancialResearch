# Agent Workflow And Safety Rules

## Agent Roles

Codex:

- large framework tasks;
- core architecture changes;
- data policy and trust policy changes;
- risky repo-wide documentation consolidation;
- tasks requiring careful git hygiene.

CodeBuddy / V4 Pro:

- repetitive operational runs;
- localized fixes;
- known wrapper execution;
- smaller update tasks with clear boundaries.

## Git Safety

Project root is fixed:

```text
D:\workspace\FinancialResearch
```

All git commands must use:

```powershell
git -C D:\workspace\FinancialResearch ...
```

Rules:

- Do not run `git init`.
- Do not run `git add .` or `git commit` in `D:\workspace` or any parent directory.
- Do not create a new repository.
- Do not push unless explicitly requested.
- At the beginning of a phase, confirm `git -C D:\workspace\FinancialResearch rev-parse --show-toplevel` returns `D:/workspace/FinancialResearch`.
- At the end of a phase, `git -C D:\workspace\FinancialResearch status --short` must be clean.

## Data Safety

- Do not commit `config/local_secrets.json`.
- Do not print or store full tokens in docs, logs, runtime JSON, stdout, or git.
- Do not auto-login Morningstar.
- Do not save Morningstar passwords.
- Do not delete, move, or rename NAS large directories.
- Do not delete historical important data.
- Do not open formal trusted consumption unless the task explicitly asks for it.
- Do not collect non-China equity time series by default.
- Do not modify parse_lab from FinancialResearch tasks.

## Trusted Consumption Boundary

Formal trusted consumption is off by default. Preview products and trusted-candidate fields are not the same as production trusted consumption.

## OpenAI API Boundary

The current human-in-the-loop workflow does not call OpenAI API. It generates prompts for GPT Web and ingests user-pasted final reports.

## Documentation Rule

README is navigation only. Module methodology belongs in module docs. Do not compress detailed methodology into README.

