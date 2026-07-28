# FinancialResearch

FinancialResearch is a database-centered platform for economic and financial
research. It builds a traceable and extensible data foundation, then develops
statistical, machine-learning, neural-network, document-intelligence,
virtual-expert, and multi-agent simulation tools on top of that foundation.

FinancialResearch 是一个以金融经济数据库为核心底座的研究平台。平台在可追溯、
可扩展的数据基础上，开发统计分析、机器学习、神经网络、专业文档解析、
虚拟专家和多智能体仿真工具，用于经济金融课题研究、实验、分析和预测。

The database is the foundation. Economic and financial research is the purpose.
Models, agents, simulations, document intelligence, and user interfaces are
research tools built on that foundation. FinancialResearch is not primarily a
real-time quotation or chart display product, is not a trading system, and is
not an investment-advice service.

## Project Overview / 项目概述

FinancialResearch is intended to support governed financial data collection,
source evaluation, dataset construction, company and report analysis,
experiments, simulations, forecasts, and evidence-backed research reporting.

The public repository is a source-progress checkpoint. It contains source code,
configuration schemas, public documentation, and lightweight validation paths.
It does not include databases, Parquet snapshots, runtime evidence, scratch
files, private corpora, credentials, model weights, provider payloads, generated
read models, or internal agent governance.

## Background and Motivation / 背景与动机

Economic and financial research is often limited by fragmented source data,
weak lineage, ambiguous reporting dates, unclear units and currencies, and
research workflows that mix current implementation state with long-term
ambition. FinancialResearch treats the data foundation as the first-class
system because analysis, modeling, and simulation are only defensible when the
underlying observations and transformations are traceable.

The project aims to make research artifacts reproducible: source observations,
standard facts, read models, model features, labels, experiments, and reports
should retain their provenance, transformation path, and applicability scope.

## Core Design Principle / 核心设计原则

The platform separates long-term research vision from implemented capability.
Current source code may contain prototypes, scaffolds, or partial integrations;
those are not described as operational public features until validation proves
the full workflow.

The intended data flow is:

```text
Data sources and documents
-> source observations
-> standard financial facts
-> research-oriented read models
-> research tools and model layer
-> evidence-backed experiments, analysis, forecasts and simulations
```

## Platform Architecture / 平台架构

The architecture is database-centered:

- **Source layer**: public or explicitly approved sources, original documents,
  provider interfaces, release dates, effective dates, revision batches, and
  source payload references.
- **Observation layer**: replay-safe source observations and source details
  that preserve the upstream representation.
- **Fact layer**: standardized financial facts with explicit subject, metric,
  economic time, unit, currency, scale, scope, lineage, and conflict handling.
- **Read-model layer**: research-oriented projections for market, fundamental,
  macro, fund/ETF, bond, index, FX, commodity, identity, lineage, coverage, and
  document workflows.
- **Tool and model layer**: deterministic queries, statistics, machine
  learning, neural networks, document intelligence, virtual experts, assisted
  reporting, and multi-agent simulation.
- **Evidence layer**: reproducible experiments, evaluation records, forecasts,
  simulations, reports, and uncertainty notes.

## Research Capability Map / 研究能力图谱

### A. Database Foundation

- market, fundamental, macro, fund/ETF, bond, index, FX and commodity data;
- capital-flow and market-participant proxy data;
- financial reports, announcements, articles, transcripts and research corpus;
- policies, events, sentiment and historical information;
- source, publication/release date, effective date, revision batch and
  transformation traceability.

### B. Traditional Statistics and Econometrics

- descriptive statistics;
- OLS, Logit and panel models;
- ARIMA and other time-series methods;
- nonlinear models;
- factor, event-study, industry-rotation and capital-ecology research;
- backtesting and robustness analysis.

### C. Machine Learning and Neural Networks

- classification, regression and ranking;
- random forest and boosting;
- neural-network and deep time-series models;
- structured/text/multimodal experiments;
- reproducible features, labels, train/test boundaries and evaluation.

### D. Agent-Based Economic and Financial Simulation

- government and regulators;
- banks, funds, insurers and institutions;
- enterprises and industry chains;
- investors and capital groups;
- media, opinion leaders and the public;
- policy, event and information-diffusion mechanisms;
- research of policy transmission, sentiment diffusion, liquidity shocks,
  industry rotation and possible event paths.

### E. Virtual Experts and Viewpoint Research

- collect public articles, speeches, interviews, videos and books;
- preserve original corpus and source references;
- model documented reasoning patterns and historical viewpoint changes;
- provide source-grounded simulated professional opinions;
- distinguish source statements, model inference and uncertainty;
- do not claim to reproduce or represent the real person.

### F. Specialized Document Intelligence

- financial-report PDF and table parsing;
- report-role recognition;
- financial field and KPI mapping;
- reporting period, currency, unit and accounting-scope interpretation;
- restatement/revision tracking;
- traceability from original text to structured data and analysis;
- future extension to policies, announcements, industry documents and research
  reports.

### G. Optional AI Layer

Without external AI, database access, deterministic queries, statistics, and
locally runnable models remain the intended base capability. AI adds
natural-language research, semantic interpretation, virtual experts,
multi-agent simulation, and assisted reporting. AI is an enhancement layer, not
a replacement for the database.

## Current Development Checkpoint / 当前开发进度

The current public source checkpoint is not a product release. It is a clean
source distribution checkpoint for review, learning, and controlled project
progress.

Implemented local engineering foundation:

- accepted active local snapshot:
  `frrem1r3_20260722T190906Z_7f8820854863`;
- active local read model:
  `readmodel4_frrem1r3_20260722T190906Z_7f8820854863_v1`;
- governed source-observation, standard-fact, lineage, conflict, coverage, and
  read-model contracts exist in local/internal evidence.

Accepted but unpublished local candidate:

- candidate: `frrem3r2_20260728T031358Z_88b9fa67d6c7`;
- read model: `readmodel7_frrem3r2_20260728T031358Z_88b9fa67d6c7_v1`;
- READMODEL7 remains unpublished and inactive.

Prototype or incomplete public capabilities:

- public first-run full database bootstrap is not yet unified;
- unified incremental-update orchestration is not yet public-ready;
- frontend/API integration is incomplete;
- statistical, ML, model, backtest, simulation, and virtual-expert capabilities
  are not yet systematically tested for public use;
- document parsing is partially implemented through a separate parser service
  and is not bundled as a complete public workflow.

Absent from the public checkpoint:

- databases and generated read models;
- Parquet snapshots and provider payloads;
- runtime evidence, scratch files, private corpora, credentials, model weights,
  and internal agent harness files.

## Installation and Configuration

Requirements:

- Python 3.10 or newer;
- Windows, macOS, or Linux with enough disk for any database you build locally;
- public/free data-source access configured by you.

Install the base environment with the single dependency file:

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The base install intentionally excludes TensorFlow, GPU stacks, external LLM
SDKs, and experimental simulation packages. Optional AI or forecasting
dependencies should be installed only for explicitly supported future
workflows, for example:

```bash
python -m pip install openai
python -m pip install "tensorflow-cpu>=2.16,<2.18" "tensorflow-probability>=0.24,<0.25"
```

Copy `.env.example` to `.env` and set only the values you need. Database and
storage locations are environment-specific. Do not commit `.env`, credentials,
local database files, runtime folders, or source payloads.

Backend import/start target:

```bash
python -m uvicorn backend.app.main:app --reload
```

Static frontend source is under `frontend_web/src/dashboard_v1/`. You can serve
it with any local static file server, for example:

```bash
python -m http.server 8080 --directory frontend_web/src/dashboard_v1
```

Base checks:

```bash
python scripts/test_fr_unified_data_entry_core.py
python -m py_compile scripts/fr_unified_data_entry_core.py
```

The public-source export and review-bundle harness is internal and is not
included in the public tree.

## License and Contribution Policy

FinancialResearch is publicly visible for noncommercial learning, research,
experimentation, testing, and feedback under the PolyForm Strict License 1.0.0.
See `LICENSE`.

The license permits use for noncommercial purposes only. It does not grant
permission to modify this source, create derivative works, distribute copies or
modified versions, or use the project commercially. GitHub visibility and
GitHub fork functionality do not grant any additional project license beyond
applicable GitHub platform terms and the `LICENSE` file.

Submit suggestions, bug reports, design proposals, research observations, and
feedback through Issues or Discussions. This project is not OSI open source.
Unsolicited code changes and pull requests are not accepted unless the
contributor is a collaborator explicitly invited and authorized for that work.

FinancialResearch is not investment, financial, or trading advice. Third-party
software, interfaces, documents, and data remain subject to their own licenses
and terms.

## Data Sources and Security

Use public/free data sources unless you explicitly configure and approve another
source. Paid, credentialed, login-gated, terminal-gated, and commercial sources
are excluded by default.

The public source distribution excludes internal agent instructions, runtime
evidence, accepted/rejected candidate payloads, databases, Parquet files,
private corpora, local paths, source payloads, and credentials.
