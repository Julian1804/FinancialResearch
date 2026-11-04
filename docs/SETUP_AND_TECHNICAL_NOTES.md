# 安装与首次使用 / Installation and first use

[简体中文](#简体中文) · [English](#english)

## 简体中文

### 安装前请先阅读

FR 可以在你的电脑上运行，但公开仓库**不附带金融数据库或预先下载的数据**。第一次使用需要先完成数据库初始化。当前版本尚不能让新用户仅通过页面独立完成首次设置；因此，克隆成功或看到首页，不代表基金和股票数据已经可以查询。

### 需要准备

| 项目 | 用途 |
| --- | --- |
| Windows 11 64 位电脑 | 运行当前版本的本地启动程序 |
| [Git for Windows](https://git-scm.com/install/windows) | 把 FR 仓库克隆到电脑；下载 Windows 64 位安装程序 |
| [Python 3.13.15](https://www.python.org/downloads/release/python-31315/) | 运行 FR；在该页面的文件列表中选择 **Windows installer (64-bit)**，并安装 Windows Python 启动器 |
| 网络连接、浏览器和可用磁盘空间 | 下载程序与所需组件，打开 FR 页面，日后存放自己的数据 |

请勿把 Python 页面的其他主版本、32 位、ARM64 或 embeddable package 当作上述安装程序。打开基础页面不需要另装数据库服务器、Node.js、TensorFlow 或 AI 服务。FR 本身不要求账号或订阅。

### 第一步：安装 Git 和 Python

1. 从上表中的 Git 官网下载并安装 Git for Windows。没有特殊需要时，保持安装程序的默认选项。
2. 从上表中的 Python 官方页面下载 **Windows installer (64-bit)**，安装普通 Python 3.13，并确认 Windows Python 启动器一同安装。
3. 在 Windows“开始”菜单搜索并打开“命令提示符”。分别输入以下两行，每行按一次回车：

        git --version
        py -3.13 --version

两行都显示版本号后再继续。若提示找不到命令，关闭并重新打开“命令提示符”再试；仍不行，请检查对应程序是否安装完成。FR 启动时还会检查 Python 是否为 64 位。

### 第二步：把 FR 克隆到电脑

1. 在文件资源管理器中选择一个你能保存文件的本地文件夹，例如“文档”下自己创建的“FR项目”文件夹。这个文件夹用于存放程序。
2. 进入该文件夹，点击文件资源管理器顶部的地址栏，输入 **cmd** 并按回车。
3. 在打开的命令提示符中输入下面一行并按回车：

        git clone https://github.com/Julian1804/FinancialResearch.git

4. 等待下载结束。打开新出现的 **FinancialResearch** 文件夹，确认里面有 **README.md** 和 **start_fr_local.cmd**。如果提示同名文件夹已存在，先检查是否以前克隆过，不要覆盖已有内容。

克隆公开仓库不要求你注册 FR 账号。Git 和 Python 只需要安装一次。

### 第三步：打开 FR

1. 在文件资源管理器中打开刚克隆的 **FinancialResearch** 文件夹，双击 **start_fr_local.cmd**。
2. 第一次运行时，程序会检查 Python 并安装所需组件。请保留启动窗口，等待完成或查看错误提示。
3. 如果启动成功，FR 会尝试打开浏览器页面。默认地址是 **http://127.0.0.1:8080**；浏览器未自动打开时，可以手动输入该地址。若启动窗口显示不同地址，以窗口显示的地址为准。

当前全新安装也可能在打开首页前遇到设置问题。若窗口报错，请保留原始提示；不要凭猜测更改文件或反复运行不同安装命令。

### 第四步：查看数据状态

第一次使用 FR 时，先查看首页显示的状态，按实际情况操作：

1. **尚未配置或尚未完成初始化：**首次使用需要先完成数据库初始化。若页面没有初始化入口，请暂时停止；当前版本尚不能让新用户自行完成首次设置。“更新数据”不能代替初始化。
2. **已初始化，但尚无可查询数据：**进入左侧 **设置 → 更新数据**，对已配置的数据范围点击 **核查并更新数据**。等待完成后回首页查看结果；如果按钮不可用或更新失败，请按页面提示处理。
3. **数据已可查询：**进入左侧 **数据 → 基金** 或 **数据 → 股票**，查找对象，选择指标和日期范围，查看结果及来源说明。

### 第五步：使用已有数据

可以在 **研究 → 统计分析／建模** 中使用当前数据支持的方法。基金和股票的查询结果可下载为 **CSV**，然后用 Excel 打开；下载内容是本次查询返回的数据，不是整个数据库。

打开 FR 会显示已有的数据状态。需要检查新数据时，请到 **设置 → 更新数据** 手动发起核查。更新期间，原有可用数据仍可查询。不同市场、指标和日期范围的可用数据可能不同；若查询没有结果，先检查对象、指标、日期和首页的数据状态。

### 许可与反馈

使用前请阅读 [LICENSE](../LICENSE)。FR 不提供投资或交易建议，外部数据也可能适用各自的条款。遇到安装或使用问题，可在 [GitHub Issues](https://github.com/Julian1804/FinancialResearch/issues) 反馈 Windows 和 Python 版本、页面提示及启动窗口错误。请勿公开密码、令牌或个人数据。

<a id="english"></a>
## English

### Read this before installing

FR runs on your own computer, but the public repository **does not include a financial database or previously downloaded data**. First-time use requires database initialization. The current version does not yet let new users complete this setup independently through the interface. Cloning the repository or seeing Home does not mean fund and equity data is ready to query.

### What you need

| Item | Purpose |
| --- | --- |
| Windows 11, 64-bit | Run the current local launcher |
| [Git for Windows](https://git-scm.com/install/windows) | Clone FR; choose the Windows 64-bit installer |
| [Python 3.13.15](https://www.python.org/downloads/release/python-31315/) | Run FR; choose **Windows installer (64-bit)** from the file list and install the Windows Python launcher |
| Internet access, a browser, and free disk space | Download the program and required components, open the page, and store your own data later |

Do not select another major Python version, a 32-bit or ARM64 installer, or the embeddable package for this setup. You do not need a separate database server, Node.js, TensorFlow, or an AI service to open the basic page. FR itself requires no account or subscription.

### Step 1: Install Git and Python

1. Download and install Git for Windows from the link above. Keep the default installer options unless you have a specific reason to change them.
2. Download the **Windows installer (64-bit)** from the Python page. Install the standard Python 3.13 package and make sure the Windows Python launcher is installed.
3. Open **Command Prompt** from the Windows Start menu. Enter these lines, pressing Enter after each:

        git --version
        py -3.13 --version

Continue when both commands show version numbers. If a command is not recognized, reopen Command Prompt and try again; then check the relevant installation. FR also checks that Python is 64-bit when it starts.

### Step 2: Clone FR

1. In File Explorer, choose a local folder where you can save files, such as a new **FR Projects** folder under Documents. This folder will hold the program.
2. Open that folder, click File Explorer's address bar, type **cmd**, and press Enter.
3. In the Command Prompt that opens, enter:

        git clone https://github.com/Julian1804/FinancialResearch.git

4. Wait for the download to finish. Open the new **FinancialResearch** folder and confirm that **README.md** and **start_fr_local.cmd** are present. If a folder with that name already exists, check whether you cloned FR before; do not overwrite it.

Cloning this public repository does not require an FR account. You only need to install Git and Python once.

### Step 3: Open FR

1. Open the cloned **FinancialResearch** folder in File Explorer and double-click **start_fr_local.cmd**.
2. On first launch, the program checks Python and installs the components it needs. Keep the launcher window open and wait for completion or an error message.
3. If startup succeeds, FR tries to open a browser page. The default address is **http://127.0.0.1:8080**. Enter it manually if the browser does not open. If the launcher shows a different address, use that one.

A new installation may encounter a setup issue before Home opens. If the launcher shows an error, keep the original message; do not guess at file changes or run a series of different installation commands.

### Step 4: Check your data status

On first use, check the status shown on Home:

1. **Not configured or not initialized:** First-time use requires database initialization. If the page offers no way to initialize, stop here; this version does not yet let new users complete the setup independently. Data Update cannot replace initialization.
2. **Initialized, but no queryable data yet:** Open **Settings → Data Update** and select **Check and update data** for a configured scope. Return to Home after it finishes. Follow the page's guidance if the button is disabled or the update fails.
3. **Data is queryable:** Open **Data → Funds** or **Data → Equities**, select an object, measure, and date range, and inspect the result and source notes.

### Step 5: Use available data

Use supported methods under **Research → Statistics/Modeling**. Fund and equity query results download as **CSV** files that Excel can open. A download contains the rows returned by that query, not the whole database.

Opening FR shows the recorded data status. To check for new data, start a check under **Settings → Data Update**. Previously available data remains queryable during an update. Availability varies by market, measure, and date range; if a query returns nothing, check the object, measure, dates, and data status on Home.

### License and feedback

Read [LICENSE](../LICENSE) before using FR. FR does not provide investment or trading advice, and external data may have separate terms. For installation or usage problems, report your Windows and Python versions, page message, and launcher error in [GitHub Issues](https://github.com/Julian1804/FinancialResearch/issues). Do not post passwords, tokens, or personal data.
