# FinancialResearch

FinancialResearch is a source-only financial research, dataset, analysis,
simulation, and evidence platform. It is not a real-time chart display surface,
not a trading system, and not investment advice.

## License And Public Use

FinancialResearch is publicly visible for noncommercial learning, research,
experimentation, testing, and feedback under the PolyForm Strict License 1.0.0.
See `LICENSE`.

The license permits use for noncommercial purposes only. It does not grant
permission to modify this source, create derivative works, distribute copies or
modified versions, or use the project commercially. GitHub visibility and GitHub
fork functionality do not grant any additional project license beyond
applicable GitHub platform terms and the `LICENSE` file.

Submit suggestions, bug reports, design proposals, research observations, and
feedback through Issues or Discussions. This project is not OSI open source.

FinancialResearch is not investment, financial, or trading advice. Third-party
software, interfaces, documents, and data remain subject to their own licenses
and terms.

## 许可与公开使用

FinancialResearch 以 PolyForm Strict License 1.0.0 授权公开可见，仅用于非商业
学习、研究、实验、测试和反馈。请阅读 `LICENSE`。

该许可不授予修改源代码、创建衍生作品、分发副本或修改版本、或进行商业使用的权利。
GitHub 的可见性或 fork 功能不会在 GitHub 平台条款和本项目 `LICENSE` 之外授予额外
项目许可。

建议、问题报告、设计提案、研究观察和反馈请通过 Issues 或 Discussions 提交。本项目
不是 OSI 开源项目。

FinancialResearch 不构成投资、金融或交易建议。第三方软件、接口、文档和数据仍受其
各自许可和条款约束。

## Current Checkpoint

This repository is being prepared as a clean public source distribution. It
does not include databases, Parquet snapshots, runtime evidence, scratch files,
private corpora, credentials, model weights, provider payloads, or generated
read models.

Current local engineering state, not bundled for public users:

- active snapshot: `frrem1r3_20260722T190906Z_7f8820854863`
- active read model: `readmodel4_frrem1r3_20260722T190906Z_7f8820854863_v1`
- accepted unpublished candidate: `frrem3r2_20260728T031358Z_88b9fa67d6c7`
- accepted unpublished read model:
  `readmodel7_frrem3r2_20260728T031358Z_88b9fa67d6c7_v1`

The unpublished candidate is not active and is not served by the public source
tree.

## Install

Requirements:

- Python 3.10 or newer
- Windows, macOS, or Linux with enough disk for any database you build locally
- Public/free data-source access configured by you

Install the base environment with the single dependency file:

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The base install intentionally excludes TensorFlow, GPU stacks, external LLM
SDKs, and experimental simulation packages. Optional AI or forecasting
dependencies should be installed only for explicitly supported future workflows,
for example:

```bash
python -m pip install openai
python -m pip install "tensorflow-cpu>=2.16,<2.18" "tensorflow-probability>=0.24,<0.25"
```

## Configuration

Copy `.env.example` to `.env` and set only the values you need. Database and
storage locations are environment-specific. Do not commit `.env`, credentials,
local database files, runtime folders, or source payloads.

External AI is optional. Without external AI, the current public source can run
deterministic validation and import smoke checks, but natural-language research
and AI-assisted workflows remain unavailable or prototype-only.

## Run

Backend import/start target:

```bash
python -m uvicorn backend.app.main:app --reload
```

Static frontend source is under `frontend_web/src/dashboard_v1/`. You can serve
it with any local static file server, for example:

```bash
python -m http.server 8080 --directory frontend_web/src/dashboard_v1
```

The current frontend is a static skeleton. It references API routes that are not
all implemented yet. The UI/API cutover is incomplete and should be treated as
prototype status.

## Validation

Base checks:

```bash
python scripts/test_fr_unified_data_entry_core.py
python -m py_compile scripts/fr_unified_data_entry_core.py
```

The public-source export and review-bundle harness is internal and is not
included in the public tree.

## Database Bootstrap Status

The intended public model is:

1. configure storage;
2. configure public/free data sources;
3. download the initial full dataset;
4. build source observations;
5. build standard facts;
6. build read models;
7. run QA;
8. run later incremental updates.

That full one-command bootstrap is not implemented yet. Existing scripts and
runtime evidence prove pieces of the workflow, but the public source tree does
not currently provide a supported initial full-download command or a unified
incremental-update command. Do not fabricate one from historical task scripts.

## Capability Status

No-AI operation:

- dataset registry validation: internal/local only because the public source
  tree excludes storage-path-bearing registry state;
- backend import and health route: supported;
- source-observation, standard-fact, and read-model architecture: implemented
  locally, but public first-run materialization is not yet unified;
- static frontend: prototype;
- database browser: prototype, with missing backend routes;
- deterministic reports: prototype;
- statistical and traditional machine-learning code: prototype/untested for
  public release;
- backtesting, trading, and live simulation: not implemented for public use;
- document parsing: partially implemented through a separate parser service,
  not bundled here.

Optional AI operation:

- natural-language research: prototype only;
- semantic document interpretation: prototype only;
- AI-assisted reporting: prototype only;
- virtual-persona output: not implemented;
- multi-agent workflows: internal engineering only, excluded from public source;
- MiroFish-style biomimetic simulation: not implemented.

Unsupported or untested capabilities are deliberately labeled as such.

## Data Sources And Security

Use public/free data sources unless you explicitly configure and approve another
source. Paid, credentialed, login-gated, terminal-gated, and commercial sources
are excluded by default.

The public source distribution excludes internal agent instructions, runtime
evidence, accepted/rejected candidate payloads, databases, Parquet files,
private corpora, local paths, source payloads, and credentials.

## Third Parties

Confirm third-party obligations before using connected sources or dependencies.
Source dependencies are installed through `requirements.txt`; databases and
provider payloads are not redistributed.
