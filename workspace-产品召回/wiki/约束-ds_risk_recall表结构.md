---
source: 产品召回需求文档-v1.0-原始.md §2.0/§2.1
created: 2026-04-12
updated: 2026-04-12
tags: [domain/技术约束, status/已验证]
authority: contextual
owner: albedolyu
---

# 约束：ds_risk_recall 表结构

## 数据源信息
- **数据库**：ds_risk
- **主表**：ds_risk_recall
- **连接信息**：已脱敏（见运维配置文档，不在 PRD 中记录）

## DDL（主表字段）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | - | 主键 |
| entid | - | 企业ID，关联键 |
| entname | - | 企业名称 |
| title | varchar | 公告标题 |
| content | text | 公告正文（同时映射「公告内容」，见R-002） |
| rdate | date | 发布日期，排序字段 |
| recall_name | - | 召回产品名称 |
| recall_num | - | 召回数量 |
| recall_reason | - | 召回原因 |
| source | - | 信息来源 |
| data_status | int | 过滤字段，=0 表示有效数据 |

## ⚠️ 待确认字段
- `riskbird_status`：PRD §3.4 要求按此字段过滤（=0），但本表 DDL 中**不存在该字段**。
  - 可能来源：其他关联表（未知），需研发确认。
  - 对应改进项：R-001

## 关联
- [[概念-产品召回]]
- [[决策-产品召回评审发现]]
- [[场景-产品召回列表页]]
