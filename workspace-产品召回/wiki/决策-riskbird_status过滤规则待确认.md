---
source: PRD评审-2026-04-12
created: 2026-04-12
updated: 2026-04-12
tags: [domain/风控, status/待验证]
---

# 决策：riskbird_status 过滤规则（待确认）

## 背景

PRD §3.4「风鸟端特殊规则」要求：只显示 `riskbird_status = 0` 的数据。  
但该字段在 §2.1 DDL 中**完全缺失**，字段来源、取值含义、与 `data_status` 的关系均未定义。

## 待确认问题

| 问题 | 说明 |
|------|------|
| 字段来源 | `riskbird_status` 属于 `ds_risk_recall` 主表还是另一张关联表？ |
| 取值含义 | 0 = 正常/有效，1 = 屏蔽/无效？ |
| 与 data_status 关系 | 两个字段是 AND 关系（同时过滤）还是 OR？ |
| 适用范围 | 该过滤仅限风鸟端，还是所有端均需执行？ |

## 评审建议

在 DDL 中补充该字段定义，并在 §3.4 中以伪代码说明过滤逻辑：

```sql
WHERE data_status = 0
  AND riskbird_status = 0
```

## 关联

- [[约束-ds_risk_recall表结构]]
- [[概念-产品召回]]
