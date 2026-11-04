# FinancialResearch

[简体中文](#简体中文) · [English](#english)

## 简体中文

### 背景介绍

FinancialResearch（FR）是在个人电脑上运行的金融数据与研究平台。我创建它，是因为基础金融研究不应该以购买昂贵的数据终端为前提。FR 希望帮助用户利用免费、公开的数据接口，在本地建立自己的金融数据库。使用 FR 本身无需注册账号、购买订阅或观看广告。

FR 的重点是数据积累和研究。它不是实时行情终端，不提供投资或交易建议，目前也没有成熟金融应用的全部功能。

### 数据处理

FR 对获取的数据进行清洗、整理、计算和检查，记录其来源，并将数据与现实中的基金、证券或经济指标对应起来。涉及对象身份和数据含义时，FR 会依据可获得的交易所、监管机构、发行方等权威资料核对；无法确认的内容会标明。整理和核对后的可用数据存入本地，供查询和分析。这不意味着每个数值都已由官网逐条核实，也不意味着某个市场的全部历史数据已经收齐。

长期目标是逐步整合世界各地可免费获取的金融与经济数据。目前的范围只是这一目标的起点。

### 数据与工具

FR 将股票、基金、固定收益、衍生品、商品、指数、利率、外汇和宏观数据作为可扩展的数据类别。目前重点支持**中国公募基金**及**中国内地和香港股票**研究。实际可查询内容取决于本地已有的数据，各市场和指标的历史覆盖可能不同。其余类别仍在扩展中。

公开仓库提供程序和文档，**不附带金融数据库或预先下载的数据**。当前版本尚不能让新用户仅凭页面完成首次数据库设置。请在下载前阅读[安装与首次使用](docs/SETUP_AND_TECHNICAL_NOTES.md)。

已有数据可以通过三种方式使用：

- **供程序和 AI 工具使用：**FR 提供本地查询接口。外部程序或 AI 工具完成接口连接后可以读取数据；目前没有面向普通用户的一键 AI 接入流程。
- **用 Excel 分析：**基金和股票查询结果可下载为 CSV 文件，再用 Excel 打开。下载的是本次查询返回的数据行，不是整个数据库；当前页面不提供原生 Excel 工作簿导出。
- **在 FR 中研究：**页面提供基金和股票查找、历史数据及来源查看、统计分析，以及包含统计和机器学习方法的建模工具。可用结果取决于本地已有的数据和所选方法。

PDF 解析、模拟市场生态，以及更广的数据和研究能力仍在建设中。

### 安装说明

当前本地启动方式面向 Windows 11 64 位电脑。安装所需程序、克隆仓库和首次使用的具体步骤见[安装与首次使用](docs/SETUP_AND_TECHNICAL_NOTES.md)。第一次使用需要先完成数据库初始化；当前版本尚不能让新用户自行完成这一步。

### 使用说明

完成设置后，双击 FR 文件夹中的 **start_fr_local.cmd** 启动。若成功打开页面，先查看首页的数据状态；启动失败时，请保留窗口中的错误提示。

进入页面后，可以按以下顺序使用：

1. **尚未配置或尚未完成初始化：**首次使用需要先完成数据库初始化。若页面没有初始化入口，请暂时停止；此版本尚不能让新用户自行完成首次设置。“更新数据”不能代替初始化。
2. **已初始化，但尚无可查询数据：**进入左侧 **设置 → 更新数据**，对已配置的范围点击 **核查并更新数据**。完成后回首页查看结果；如果按钮不可用或更新失败，请按页面提示处理。
3. **数据已可查询：**进入左侧 **数据 → 基金** 或 **数据 → 股票**，查找对象并选择指标和日期范围。查询结果可下载为 CSV，用 Excel 打开。也可以进入 **研究 → 统计分析／建模** 使用当前数据支持的方法。

打开 FR 会显示已有的数据状态。需要检查新数据时，请在 **设置 → 更新数据** 中主动发起；更新期间，原有可用数据仍可查询。

### 许可与交流

FR 以 [PolyForm Strict License 1.0.0](LICENSE) 公开源码。该许可允许符合条款的非商业使用，但不授予修改、制作衍生作品或再分发软件的权利；公开可见不等于 OSI 意义上的开源许可。外部数据和软件可能有各自的使用条款。欢迎在 [GitHub Issues](https://github.com/Julian1804/FinancialResearch/issues) 提问、反馈问题和提出建议。

<a id="english"></a>
## English

### Background

FinancialResearch (FR) is a local financial-data and research platform. I started it because basic financial research should not require an expensive data terminal. FR aims to help you build a database on your own computer from free, publicly accessible data interfaces. FR itself requires no account or subscription and shows no ads.

FR focuses on building usable data and research tools. It is not a real-time market terminal or a source of investment or trading advice, and it does not yet offer every feature of a mature financial app.

### Data processing

FR collects, cleans, organizes, calculates, and checks data, records its sources, and links it to real funds, securities, or economic measures. Where identity or meaning matters, FR checks available evidence from exchanges, regulators, issuers, and other authoritative sources. Unresolved questions are marked. Usable data is stored locally for queries and analysis. This does not mean that every value has been checked individually on an official website or that a market's full history is available.

The long-term goal is to bring together freely accessible financial and economic data from around the world. Today's coverage is an early part of that goal.

### Data and tools

FR organizes data into extensible categories: Equity, Fund, Fixed Income, Derivatives, Commodity, Index, Interest Rate, Foreign Exchange, and Macro. The current focus is **China public funds** and **mainland China and Hong Kong equities**. What you can query depends on the data available on your own computer; historical coverage differs by market and measure. The other categories are still being expanded.

The public repository contains the program and documentation, **not a financial database or previously downloaded data**. The current version does not yet let new users complete first-time database setup through the interface alone. Read the [installation and first-use guide](docs/SETUP_AND_TECHNICAL_NOTES.md) before downloading.

Available data can be used in three ways:

- **Programs and AI tools:** Local query interfaces can supply data to external programs or AI tools once you connect them. There is no one-click AI integration for ordinary users yet.
- **Excel:** Download fund and equity query results as CSV and open them in Excel. The download contains the rows returned by that query, not the whole database; the current pages do not produce native Excel workbooks.
- **Research inside FR:** Search funds and equities, inspect available history and source notes, run statistical analysis, and use supported statistical and machine-learning methods in the Modeling workspace. Results depend on the data in your installation and the method selected.

PDF parsing, market-ecosystem simulation, broader data coverage, and more research tools remain in development.

### Installation

The current local launcher targets Windows 11 64-bit computers. See the [installation and first-use guide](docs/SETUP_AND_TECHNICAL_NOTES.md) for the required programs, cloning steps, and what to expect on first use. You need to initialize a database before using its data; this version does not yet let new users do that independently through the interface.

### Usage

After setup, double-click **start_fr_local.cmd** in the FR folder. If the page opens, check the data status on Home. If startup fails, keep the error shown in the launcher window.

1. **Not configured or not initialized:** First-time use requires database initialization. If the page offers no way to initialize, stop here; this version does not yet let new users complete the setup independently. Data Update cannot replace initialization.
2. **Initialized, but no queryable data yet:** Open **Settings → Data Update** and select **Check and update data** for a configured scope. Return to Home after it finishes; follow the page's guidance if the button is disabled or the update fails.
3. **Data is queryable:** Open **Data → Funds** or **Data → Equities**, select an object, measure, and period, and inspect the result. You can download the query as CSV for Excel, or use supported methods under **Research → Statistics/Modeling**.

Opening FR shows the recorded data status. To check for new data, start an update under **Settings → Data Update**. Previously available data remains queryable during an update.

### License and feedback

FR's source is visible under the [PolyForm Strict License 1.0.0](LICENSE). It permits qualifying noncommercial use but does not grant permission to modify the software, make derivative works, or redistribute it. Public visibility does not make this an OSI open-source license. External data and software may have separate terms. Questions, bug reports, and suggestions are welcome in [GitHub Issues](https://github.com/Julian1804/FinancialResearch/issues).
