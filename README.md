# FinancialResearch

[English](#english) · [简体中文](#zh-cn)

<a id="english"></a>
## English

### Purpose and architecture

FinancialResearch is a database-centered platform for economic and financial research, analysis, experiments, simulation, prediction, and evidence-backed reporting. Its aim is to make research reproducible: keep the source, economic meaning, time role, transformation, and limits of each result traceable. It is not primarily a live chart display, a trading system, or an investment-advice service.

The intended path is:

```text
Sources and documents
→ source observations
→ standardized financial facts and identity
→ governed releases and research read models
→ analysis, datasets, models, experiments, simulations, and reports
```

The database is the foundation. Statistical and econometric methods, machine learning, neural networks, financial-document intelligence, virtual experts, and multi-agent simulation are research directions built on it. These directions describe the platform's vision; their presence in source code does not establish a complete, operational workflow.

### What this source checkpoint contains

This repository is a **public source checkpoint**, not a hosted service, a database download, or an accepted public product release. It contains application source, a static web interface, configuration schemas, installation scripts, documentation, and bounded offline checks. It does not contain a populated financial database, generated read models, Parquet snapshots, provider responses, credentials, model weights, private corpora, or the developer installation's runtime evidence.

The separately governed development installation has a bounded active V1 release for China Public Fund and China Equity. That installation's accepted data, financial evidence, release IDs, and serving pointers do **not** transfer to users of this source package. Each user must build and validate their own database and release. In the platform vocabulary, China Equity is Equity × China; mainland SSE/SZSE/BSE and Hong Kong HKEX have distinct market and identity semantics.

Other Universe foundations and parts of the application may appear as candidate or partial code. This checkpoint does not claim seven additional Universes are serving, or that the complete research UI, model registry, inference, backtesting, simulation, virtual-expert, and document workflows are finished. A source path, a passing offline test, or a reachable provider does not prove financial coverage or product acceptance.

### Install and run locally

The bounded Windows setup targets Windows 11 x64 and CPython 3.13.15 x64. The hashed `requirements-runtime-py313-win64.lock` is the dependency contract. From the repository root:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-runtime-py313-win64.lock
```

Copy `.env.example` to `.env`. Set `FR_LOCAL_STORAGE_ROOT` and `FR_NAS_ROOT` to locations you own before storage use, or select a local Data Root during First Run. No developer storage defaults or prebuilt database are included. Do not commit `.env`, credentials, databases, runtime folders, or source payloads.

On Windows, launch from the repository root with:

```bat
start_fr_local.cmd
```

The launcher checks CPython and the hashed lock, uses an installation-local environment under `%LOCALAPPDATA%\FinancialResearch\venv`, and starts the backend and frontend on loopback. The default ports are `127.0.0.1:8000` and `127.0.0.1:8080`; `FR_LOCAL_BACKEND_PORT` and `FR_LOCAL_FRONTEND_PORT` select other local ports. First Run asks for a Data Root and checks storage needs for the selected scope. A healthy local app can open before its first financial publication; `/api/readiness` separately reports whether financial serving is available. Stop the foreground launcher with `Ctrl+C` or close its window. The source package does not ship a separate stop script.

For development, the backend entry point is `backend.app.main:app`, and the static interface is under `frontend_web/src/dashboard_v1/`:

```powershell
python -m uvicorn backend.app.main:app --reload
python -m http.server 8080 --directory frontend_web/src/dashboard_v1
```

Run those development commands separately if needed; the Windows launcher already starts the local app. TensorFlow, GPU stacks, external LLM SDKs, and experimental simulation packages are not in the base lock.

### Data, rights, and known limits

Public or free sources are the default. Paid, credentialed, login-gated, terminal-gated, and commercial sources are excluded unless a user explicitly approves and configures them. HKEX Sina/Eastmoney candidate adapters and the Sina financial-statement adapter are disabled by default. Where rights permit, an installation-local `FR_PROVIDER_ROUTE_CONFIG` may declare a route; this file is not distributed. A missing route is a provider gap, not proof that an instrument ceased to exist. This checkpoint does not claim a general licensed-feed or SFTP importer.

Users obtain their own data, subscriptions, credentials, and third-party usage rights from the relevant rights holders. The developer installation's downloads, permissions, and validation results are not transferred. The package excludes internal agent instructions, runtime evidence, accepted and rejected candidate payloads, databases, Parquet data, private corpora, local paths, and credentials.

The package does not contain the accepted HKEX economic-identity population reference. HKEX first-install acquisition returns `identity_reference_gap` **before source requests** unless an installation supplies a separately accepted reference. The structural preflight rejects malformed rows and a reference without a usable accepted economic-identity row; it does not certify the financial evidence or acceptance decision. Mainland Equity and Fund scopes do not inherit this HKEX limitation.

The development installation's observation-specific historical Fund NAV proofs are also absent. A generic `observation_date` does not become `nav_date` without exact proof, and release-bound Modeling rejects unproved Fund NAV input. A new installation must establish its own evidence. No source inventory alone proves a complete market denominator, economic identity, or historical coverage.

### Bounded offline checks

These commands check the current backend import closure, required static resources, application import, and selected fail-closed identity and time-role behavior with disposable test roots:

```powershell
python scripts/fr_public_source.py check-closure
python scripts/fr_public_validation.py smoke
```

They do **not** validate complete product operation, live providers, database construction, financial coverage, or public-release acceptance. The internal export classifier, distribution manifest generator, and review-bundle harness are not shipped; `check-closure` does not regenerate or authorize a publication manifest.

### Removed legacy Python entry points

Compared with the previous public GitHub checkpoint, this package removes these modules and scripts:

```text
backend/app/core/paths.py
backend/app/modules/financial_report/schemas/canonical_fact_contract.py
backend/app/modules/financial_report/schemas/document_role_contract.py
backend/app/modules/financial_report/schemas/extraction_contract.py
backend/app/modules/financial_report/schemas/minimal_extraction_contract.py
backend/app/modules/financial_report/schemas/provisional_fact_contract.py
backend/app/modules/financial_report/schemas/statement_field_contract.py
backend/app/modules/financial_report/schemas/table_contract.py
scripts/fr_dataset_registry_validate.py
scripts/fr_unified_data_entry_core.py
scripts/test_fr_unified_data_entry_core.py
```

The old `fr_unified_data_entry_core` and `fr_dataset_registry_validate` commands are retired. The bounded `check-closure` and `smoke` checks are **not** business-equivalent replacements for those data-entry commands. External Python import compatibility for the removed modules has not been verified.

### License and contributions

FinancialResearch is publicly visible for noncommercial learning, research, experimentation, testing, and feedback under the [PolyForm Strict License 1.0.0](LICENSE). The license permits noncommercial use only. It does not grant permission to modify the source, make derivative works, distribute copies or modified versions, or use it commercially. GitHub visibility and fork features do not add project license rights beyond GitHub's applicable terms and `LICENSE`. This project is **not OSI open source**.

Suggestions, bug reports, research observations, and design proposals are welcome through Issues or Discussions. Unsolicited code changes and pull requests are not accepted unless a collaborator is explicitly invited and authorized. This project gives no investment, financial, or trading advice. Third-party software, interfaces, documents, and data have their own terms.

<a id="zh-cn"></a>
## 简体中文

### 项目定位与架构

FinancialResearch 是以数据库为核心的经济金融研究、分析、实验、仿真、预测和证据化报告平台。它希望让研究结果可复现：每项结果的来源、经济含义、时间角色、转换过程和适用边界都应可追溯。项目主要用途不是实时行情图表展示，也不是交易系统或投资建议服务。

目标数据链路是：

```text
数据来源和文档
→ 来源观测
→ 标准化金融事实与身份
→ 受治理的发布版本和研究读模型
→ 分析、数据集、模型、实验、仿真和报告
```

数据库是基础。统计与计量方法、机器学习、神经网络、金融文档智能、虚拟专家和多智能体仿真是在其上构建的研究方向。这些方向属于平台愿景；源码中出现相关路径，不等于完整工作流已经可运行或获得验收。

### 本次源码进度节点包含什么

本仓库是**公开源码进度节点**，不是托管服务、数据库下载包，也不是已验收的公开产品版本。它包含应用源码、静态网页界面、配置结构、安装脚本、文档及有限的离线检查；不包含已填充的金融数据库、生成的读模型、Parquet 快照、来源响应、凭据、模型权重、私有语料或开发者安装环境的运行证据。

另行治理的开发者安装环境已有范围受限的中国公募基金和中国股票 V1 活跃发布。该环境中已验收的数据、金融证据、发布 ID 和 Serving 指针**不会**随本源码包转交给用户。每位用户须自行建库、验证并发布自己的版本。在平台词汇中，中国股票是 Equity × China 的地区范围；内地 SSE/SZSE/BSE 与香港 HKEX 的市场和身份语义不同。

其他 Universe 基础及部分应用路径可能以候选或未完成代码形式出现。本节点不宣称新增七个 Universe 已提供 Serving，也不宣称完整研究界面、模型注册、推断、回测、仿真、虚拟专家和文档工作流已完成。源码路径、离线测试通过或来源接口可访问，都不足以证明金融覆盖或产品验收。

### 本地安装与运行

当前有界的 Windows 安装目标为 Windows 11 x64 和 CPython 3.13.15 x64。带哈希的 `requirements-runtime-py313-win64.lock` 是依赖合同。在仓库根目录运行：

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-runtime-py313-win64.lock
```

将 `.env.example` 复制为 `.env`。使用存储前，把 `FR_LOCAL_STORAGE_ROOT` 和 `FR_NAS_ROOT` 设为自己拥有的位置，或在首次运行时选择本地 Data Root。包内没有开发者存储默认值或预建数据库。不要提交 `.env`、凭据、数据库、运行目录或来源载荷。

在 Windows 仓库根目录启动：

```bat
start_fr_local.cmd
```

启动器检查 CPython 与哈希锁文件，在 `%LOCALAPPDATA%\FinancialResearch\venv` 使用安装环境本地的虚拟环境，并仅在本机回环地址启动前后端。默认端口是 `127.0.0.1:8000` 和 `127.0.0.1:8080`；可通过 `FR_LOCAL_BACKEND_PORT`、`FR_LOCAL_FRONTEND_PORT` 选择其他本地端口。首次运行要求选择 Data Root，并按所选范围检查存储需求。应用健康启动可能早于首次金融数据发布；`/api/readiness` 会单独报告金融 Serving 是否可用。可用 `Ctrl+C` 停止前台启动器，或关闭其窗口；源码包不附带独立停止脚本。

开发用后端入口为 `backend.app.main:app`，静态界面位于 `frontend_web/src/dashboard_v1/`：

```powershell
python -m uvicorn backend.app.main:app --reload
python -m http.server 8080 --directory frontend_web/src/dashboard_v1
```

如有需要，请分别运行上述开发命令；Windows 启动器已负责启动本地应用。基础依赖锁不包含 TensorFlow、GPU 工具栈、外部 LLM SDK 或实验性仿真软件包。

### 数据、授权与已知限制

默认使用公开或免费来源。付费、需凭据、需登录、需终端权限及商业来源，须由用户明确批准并配置后才可使用。HKEX 的 Sina/Eastmoney 候选适配器及 Sina 财报适配器默认关闭。拥有相应使用权时，可在安装环境本地的 `FR_PROVIDER_ROUTE_CONFIG` 中声明路线；该文件不随包分发。缺少路线是来源缺口，不能据此认定金融工具已终止。本节点不宣称提供通用授权数据流或 SFTP 导入器。

用户须自行从权利人取得数据、订阅、凭据及第三方使用权。开发者安装环境的下载数据、权限和验证结果不会转交。包内不含内部代理指令、运行证据、已接受或拒绝的候选载荷、数据库、Parquet 数据、私有语料、本地路径和凭据。

包内没有已接受的 HKEX 经济身份总体参考。安装环境未提供另行验收的参考时，HKEX 首次采集会在**任何来源请求之前**返回 `identity_reference_gap`。结构预检会拒绝格式不合格的行及没有可用已接受经济身份行的参考；它并不认证金融证据或验收决定。内地股票与基金范围不继承这一 HKEX 限制。

包内也没有开发者安装环境针对历史基金 NAV 逐笔观测的证明。缺少精确证明时，通用 `observation_date` 不会升格为 `nav_date`，受发布版本约束的 Modeling 会拒绝该未证明的基金 NAV 输入。新安装环境须建立自己的证据。仅凭来源清单，不能证明完整市场总体、经济身份或历史覆盖。

### 有限的离线检查

以下命令用可丢弃的测试目录检查当前后端导入闭包、必要静态资源、应用导入，以及部分身份和时间角色的拒绝路径：

```powershell
python scripts/fr_public_source.py check-closure
python scripts/fr_public_validation.py smoke
```

这些检查**不能**证明完整产品运行、实时来源、建库、金融覆盖或公开发布验收。内部导出分类器、分发清单生成器及 Review 包工具不随源码分发；`check-closure` 不会重新生成发布清单，也不授权发布。

### 移除的旧 Python 入口

与上一个 GitHub 公开节点相比，本包移除了以下模块及脚本：

```text
backend/app/core/paths.py
backend/app/modules/financial_report/schemas/canonical_fact_contract.py
backend/app/modules/financial_report/schemas/document_role_contract.py
backend/app/modules/financial_report/schemas/extraction_contract.py
backend/app/modules/financial_report/schemas/minimal_extraction_contract.py
backend/app/modules/financial_report/schemas/provisional_fact_contract.py
backend/app/modules/financial_report/schemas/statement_field_contract.py
backend/app/modules/financial_report/schemas/table_contract.py
scripts/fr_dataset_registry_validate.py
scripts/fr_unified_data_entry_core.py
scripts/test_fr_unified_data_entry_core.py
```

旧的 `fr_unified_data_entry_core`、`fr_dataset_registry_validate` 命令已退役。`check-closure` 和 `smoke` 只是有限的离线源码检查，**不是**旧数据入口在业务上的等价替代。尚未验证外部 Python 代码导入已移除模块的兼容性。

### 许可与贡献

FinancialResearch 按 [PolyForm Strict License 1.0.0](LICENSE) 公开可见，供非商业学习、研究、实验、测试和反馈。该许可仅允许非商业使用；不授予修改源码、制作衍生作品、分发副本或修改版、商业使用的权利。GitHub 的可见性及 fork 功能，不会在适用的 GitHub 平台条款和 `LICENSE` 之外增加项目许可权利。本项目**不是 OSI 开源项目**。

欢迎通过 Issues 或 Discussions 提交建议、故障报告、研究观察和设计提案。未经明确邀请及授权的代码修改和拉取请求不予接受。本项目不提供投资、金融或交易建议。第三方软件、接口、文档和数据各有其适用条款。
