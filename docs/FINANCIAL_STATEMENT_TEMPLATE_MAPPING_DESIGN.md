# Financial Statement Template Mapping Design

Generated at: 2026-05-03

## Goal

Financial statement template mapping converts canonical tables into candidate financial statement structures before formal field extraction.

The first version should be rule-based, explainable, and reviewable. It should not delegate the full mapping problem to an LLM.

## Statement Recognition Targets

Primary targets:

- `balance_sheet`
- `income_statement`
- `cash_flow_statement`

Secondary targets:

- `shareholder_table`
- `segment_revenue_table`
- `unknown`

Unknown tables should remain available for human review and later adapter improvement.

## Keyword And Structure Features

Balance sheet indicators:

- 资产负债表 / 資產負債表 / balance sheet
- 资产总计 / 資產總計
- 负债合计 / 負債合計
- 所有者权益 / 股东权益
- assets, liabilities, equity

Income statement indicators:

- 利润表 / 利潤表 / income statement
- 营业收入 / 營業收入
- 营业成本 / 營業成本
- 净利润 / 淨利潤
- profit, revenue, income

Cash flow indicators:

- 现金流量表 / 現金流量表 / cash flow statement
- 经营活动 / 經營活動
- 投资活动 / 投資活動
- 筹资活动 / 籌資活動
- net cash flow

Shareholder table indicators:

- 股东信息 / 股東信息
- 前十名股东 / 前十名股東
- 持股数量
- 持股比例
- 质押 / 質押

Segment revenue indicators:

- 分部
- 分行业
- 分产品 / 分產品
- 收益明细 / 收益明細
- segment revenue

## A-Share And HK Report Differences

A-share reports commonly use:

- 元, 万元, 人民币
- 本期, 上期, 年初至报告期末
- 合并 / 母公司 statement variants
- shareholder pledge and restricted share tables

Hong Kong reports commonly use:

- RMB, HKD, USD, 千元, 百万元
- year ended / six months ended
- consolidated statement wording
- segment revenue and business service categories
- bilingual or traditional Chinese labels

The mapper must preserve locale and wording evidence rather than forcing a single naming convention too early.

## Consolidated Vs Parent Company Statements

Mapping should detect:

- 合并 / consolidated
- 母公司 / company
- 本集团 / group
- 本公司 / company

If both consolidated and parent-company tables exist, downstream extraction should keep them separate.

## Unit Recognition

Units must be detected before numeric values are normalized:

- 元
- 千元
- 万元
- 百万元
- 人民币
- 港币 / HKD
- 美元 / USD

Unit evidence may appear in titles, nearby page text, table headers, or notes above the table.

## Period Column Recognition

Common period labels:

- 本期
- 上期
- 本年
- 上年
- 本报告期
- 上年同期
- 截至某日
- year ended
- period ended

The mapper should preserve raw period labels and only normalize them after enough date context is available.

## Table Layout Handling

Horizontal tables:

- metrics in rows
- periods in columns
- common in financial statements

Vertical tables:

- metrics in columns
- periods or categories in rows
- common in segment or shareholder disclosures

Cross-page tables:

- prefer `merged_cross_page_table` candidates when confidence is acceptable;
- keep source page fragments for audit;
- require review if continuation confidence is low or numbers appear split.

## Why Rules First

Template mapping should start with rules because:

- financial rows require traceable source evidence;
- table coordinates and units matter;
- review teams need deterministic reasons;
- LLM output can be useful later but should not be the only authority for numeric mapping.

LLM support can be added as an assistant for ambiguous labels after canonical evidence is available.

## Human Review Points

Before automatic field extraction, review should check:

- statement type classification;
- consolidated vs parent-company distinction;
- unit and currency;
- period columns;
- cross-page table merges;
- visual table recovery pages;
- low-confidence or malformed tables;
- rows with duplicate or ambiguous labels.
