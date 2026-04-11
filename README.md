# Financial Research Assistant

## 项目简介

Financial Research Assistant 是一个面向长期研究场景的财报分析系统。

它不是一次性“上传几份财报、自动生成一篇报告”的聊天工具，而是一个围绕 **主财报、辅助材料、预测、回测、修正日志、管理层反馈** 持续运转的研究系统。项目核心目标是建立：

- 持续研究
- 持续修正预期
- 持续回测偏差
- 持续沉淀系统记忆

项目定位更接近一个 **研究操作系统**，而不是普通的 AI 摘要工具。

---

## 项目要解决的问题

这个项目希望解决的不只是“看懂一份财报”，而是一整套研究流程问题：

1. 如何把多期正式财报串成稳定主时序。
2. 如何纳入业绩公告、业绩说明会、演示材料、并购公告等辅助材料，但不污染主财报时间轴。
3. 如何站在某个时间点，基于当时全部已知信息形成一份“当时视角”的研究报告。
4. 如何根据当前信息预测下一期或下一年表现。
5. 如何在真实数据出来后，对照旧预测进行回测。
6. 如何识别偏差来自宏观、行业、公司变化，还是来自分析框架本身。
7. 如何把偏差经验写回系统记忆，让下一轮研究更稳。
8. 如何把研究结果转译成管理层可执行的信息和决策支持。

---

## 项目方法论

### 1. 研究系统 ≠ 聊天机器人
本项目优先级：

- 可解释性 > 复杂度
- 稳定性 > 一次性聪明
- 时间序列认知 > 单次回答漂亮
- 结构化输出 > 大段自然语言
- 允许“信息不足” > 编造结论

### 2. 主财报与辅助材料必须严格分离
主财报决定：

- `report_type`
- `period_key`
- 主时序顺序
- actuals 口径
- 预测映射关系

辅助材料只用于：

- 修正预期
- 补充研究上下文
- 提高时效性
- 解释趋势变化

辅助材料不能替代正式财报，不能进入主时序 actuals。

### 3. 预测不是“给个数字”
预测必须具备：

- 统计模型基础
- AI 解释层
- 预测快照
- 实际值对照
- 偏差归因
- 修正日志
- 历史反馈

---

## 财报分析统一框架

项目内所有公司分析，统一遵循以下 10 大模块：

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

详细定义见：[`docs/RESEARCH_FRAMEWORK.md`](docs/RESEARCH_FRAMEWORK.md)

---

## 当前系统能力

当前系统已经具备以下主流程能力：

- 上传财报
- 解析 PDF 并生成 `parsed_*.json`
- 提取关键结构化信息并生成 `extracted_*.json`
- 自动抽取标准化财务指标
- 生成 actual metrics registry
- 多材料 AI 财报分析报告生成
- 基于历史信息生成最新版研究报告（update）
- 正式 BSTS 预测页 + forecast snapshot + registry
- forecast_check 实际值对照与偏差分析
- 回测复盘摘要 / 偏差热力图 / 预警信号总结
- revision log 写回 history_memory
- 基于历史资料的 QA 检索问答
- repository / timeline / SQLite 索引总览
- 正式版工作台 + 测试版独立调试页面
- 公司画像标签体系与手动覆盖能力

---

## 前端结构

### 正式版
面向日常使用，目标是：

- 操作简化
- 后台逻辑完整
- 不暴露太多中间过程

当前正式版主要包括：

- 工作台
- 公司画像

### 测试版
面向开发和调试，保留每一层独立页面：

- Upload
- Parse
- Extract
- Metrics
- Metrics Table
- Actuals
- Analyze
- Update
- Forecast
- Forecast Dashboard
- Forecast Check
- Backtest Dashboard
- Backtest Report
- Revision Memory
- Master Report
- Summary Report
- Decision Support
- QA
- Repository

---

## 当前核心目录建议

```text
repo/
├── app/
├── config/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── RESEARCH_FRAMEWORK.md
│   ├── ROADMAP.md
│   └── COLLABORATION.md（可后续补）
├── tests/
├── scripts/
├── data/                  # 本地数据，不建议直接入库
├── .env.example
├── .gitignore
├── README.md
└── requirements.txt
```

---

## 当前最重要的系统原则

1. 不能把辅助材料当主财报。
2. 不能为了“看起来更聪明”破坏结构化和可追溯性。
3. 不能让 AI 编造数字。
4. 不能只看最新一期，忽略历史误差积累。
5. 不能把正式版做成测试版那样复杂。

---

## 当前尚未完全完成的部分

项目现在已经进入“研究系统”阶段，但仍有一些关键能力尚未完全完成：

- 完整后台任务系统（当前为协作式取消，不是强中断）
- parse 的单文件/单页耗时诊断
- 更成熟的复杂页多模态解析
- 更完整的全行业标签与行业画像映射
- 统一状态总线 / registry 体系
- 更强的模型输出 JSON 修复与 schema 约束
- 更完整的 GitHub 多人协作规范

详细规划见：[`docs/ROADMAP.md`](docs/ROADMAP.md)

---

## 建议的协作流程

1. 先理解项目方法论，再开始改代码。
2. 涉及 `parsed / extracted / report / registry` 结构变更时，先更新文档再改代码。
3. 任何会影响主/辅材料判定的逻辑修改，都需要特别审查。
4. 修改公司画像标签体系时，必须保持：
   - BM / VC / LC 单选
   - LC 支持 `sub_type`
   - G 多选
   - 手动覆盖优先级最高
5. 预测与回测相关模块必须保证可追溯。

---

## 文档索引

- 项目架构说明：[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- 财报分析框架：[`docs/RESEARCH_FRAMEWORK.md`](docs/RESEARCH_FRAMEWORK.md)
- 后续路线图：[`docs/ROADMAP.md`](docs/ROADMAP.md)

