# FinancialResearch

FinancialResearch 是一个个人投资研究用的金融研究总集成平台，目标是提供类似研究 Dashboard 的工作台，逐步覆盖：

- 财报研究
- 宏观研究
- 舆情分析
- 大类资产 / 商品 / 股指 / 汇率 / 利率跟踪
- 研究资料库
- 决策支持

本次重构是工程架构升级，不是推翻原有财报分析方法论。FinancialResearch 仍然围绕长期跟踪、预测、回测、修正来组织研究工作。

## Research Methodology

原有财报分析方法论保持不变：

- 先做一级 / 二级 / 三级行业分类
- 结合宏观环境作为 benchmark
- 围绕财报长期跟踪、预测、回测、修正
- 区分主时序财报和辅助材料

财报分析核心框架仍保留：

1. 行业定位
2. 宏观环境
3. 公司概况
4. 成本结构
5. 客户结构
6. 盈利模式
7. 资金流向
8. 未来展望
9. 护城河
10. 风险 + 预期

主时序财报和辅助材料必须区分：主时序财报才预期包含资产负债表、利润表、现金流量表；业绩新闻稿、业绩公告、业绩简报、电话会议纪要、投资者演示材料等辅助材料不应因缺少三大表被判失败。

## Current Architecture

当前新架构：

- `backend/`: FastAPI 主后端
- `frontend_web/`: 未来 React + Vite 前端
- `requirements/`: 分层依赖文件
- `scripts/`: 本地 smoke test / dry-run 验证脚本
- `docs/`: 架构、集成、测试与复盘文档

核心 backend 模块：

- `backend/app/modules/financial_report`: 财报研究模块
- `backend/app/modules/macro_research`: 宏观研究模块占位
- `backend/app/modules/sentiment_analysis`: 舆情分析模块占位
- `backend/app/modules/market_data_tracking`: 大类资产跟踪模块占位
- `backend/app/modules/research_repository`: 研究资料库模块占位
- `backend/app/modules/decision_support`: 决策支持模块占位
- `backend/app/modules/system_tasks`: 系统任务模块占位

简化目录结构：

```text
FinancialResearch/
  backend/
  frontend_web/
  requirements/
  scripts/
  docs/
  README.md
```

旧 `app/` Streamlit 工程已从当前 refactor 分支移除，可从 Git 历史恢复。

## Why Streamlit Was Removed

Streamlit 曾用于快速原型验证，帮助项目跑通财报上传、解析、抽取、分析、预测、回测等早期流程。

但长期平台化阶段需要更稳定的架构。旧 Streamlit 版本暴露出：

- 页面刷新、侧边栏切换、task detail 切换时容易断线或重跑
- 长任务与 UI 进程耦合，重 parser 容易拖垮页面
- cancel / queued / running / hung 状态不够清晰
- logs 与真实任务状态可能不同步
- UI 层和业务逻辑混在 `app/pages` 与 `app/services`
- 不利于后续扩展宏观、舆情、大类资产、资料库和决策支持模块

因此新架构改为 FastAPI + React。重任务通过 API、任务状态、registry 和 review gate 管理，前端只负责展示和交互。

详细复盘见：

- [STREAMLIT_LEGACY_ISSUES_AND_REFACTOR_LESSONS.md](docs/STREAMLIT_LEGACY_ISSUES_AND_REFACTOR_LESSONS.md)
- [STREAMLIT_REMOVAL_REPORT.md](docs/STREAMLIT_REMOVAL_REPORT.md)

## Parse Lab Boundary

Parse Lab 是独立 PDF 解析服务，不放在本仓库内。

边界原则：

- FinancialResearch backend 通过 HTTP API 调用 Parse Lab
- `frontend_web` 不直接调用 Parse Lab
- FinancialResearch 不 import Parse Lab 内部 parser 模块
- FinancialResearch 不直接调用 Marker / MinerU / Surya / pdfplumber / PyMuPDF
- Parse Lab 负责 PDF 解析、页面级路由、表格恢复、跨页表格候选、quality flags
- FinancialResearch 负责研究流程、质量门槛、review decision、字段抽取、分析、预测、回测和 Dashboard

默认 Parse Lab API v1 地址：

```text
PARSE_LAB_BASE_URL=http://127.0.0.1:8021
```

如果要运行 Parse Lab 相关接口，需要先启动 Parse Lab API v1：

```text
http://127.0.0.1:8021
```

## Completed In Current Refactor

当前阶段已完成：

- FastAPI backend skeleton
- `/api/health` smoke test
- Parse Lab HTTP client connectivity
- Parse Lab single PDF submit + quality gate
- Parsed document registry
- Review queue
- Review decision / extraction eligibility gate
- Canonical table schema
- Financial table candidate extraction dry-run
- Statement field mapping prototype
- Statement field mapping refinement
- Minimal financial extraction dry-run prototype
- Document role / report type gate
- Legacy Streamlit lessons documentation

## Not Yet Complete

当前尚未完成：

- 未接正式 extraction
- 未接 metrics
- 未接 forecast
- 未接 backtest
- 未接 report generation
- 未做正式 frontend Dashboard
- 未实现数据库持久化
- 当前 registry / review decisions 仍是本地 JSONL
- dry-run prototype 不等于正式财务字段入库

## Run Backend

启动 FinancialResearch backend：

```powershell
D:\workspace\envs\financial_research_backend\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8030
```

Health check：

```text
GET http://127.0.0.1:8030/api/health
```

预期返回：

```json
{"status":"ok","service":"financial_research_backend"}
```

## Development Principles

- UI thin, backend-driven
- Long-running tasks must not run inside frontend runtime
- Parse Lab stays isolated
- Frontend must call FinancialResearch backend, not Parse Lab directly
- Parser dependencies must not be installed into the FinancialResearch backend environment
- All parse outputs must pass quality gate and review decision before extraction
- Auxiliary materials must not be penalized for missing three statements
- No metrics / forecast / backtest before extraction regression tests
- Keep source traceability: `source_pages`, `table_group_id`, `quality_flags`, parser source, confidence
- Macro, sentiment, and market data modules should stay inside the main platform until heavy dependencies, long tasks, real-time collection, or model inference justify splitting them out

## Documentation Index

- [FINANCIAL_RESEARCH_NEW_ARCHITECTURE.md](docs/FINANCIAL_RESEARCH_NEW_ARCHITECTURE.md)
- [FINANCIAL_RESEARCH_PLATFORM_REFACTOR_PLAN.md](docs/FINANCIAL_RESEARCH_PLATFORM_REFACTOR_PLAN.md)
- [STREAMLIT_REMOVAL_REPORT.md](docs/STREAMLIT_REMOVAL_REPORT.md)
- [STREAMLIT_LEGACY_ISSUES_AND_REFACTOR_LESSONS.md](docs/STREAMLIT_LEGACY_ISSUES_AND_REFACTOR_LESSONS.md)
- [FINANCIAL_RESEARCH_PARSE_INTEGRATION_TODO.md](docs/FINANCIAL_RESEARCH_PARSE_INTEGRATION_TODO.md)
- [PRE_COMMIT_REVIEW_REPORT.md](docs/PRE_COMMIT_REVIEW_REPORT.md)
- [RESEARCH_FRAMEWORK.md](docs/RESEARCH_FRAMEWORK.md)
- [ROADMAP.md](docs/ROADMAP.md)
