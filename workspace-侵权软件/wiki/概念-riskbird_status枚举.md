---
source: 侵权软件需求文档-v1.0-原始.md
created: 2026-04-12
updated: 2026-04-12
tags: [domain/侵权软件, status/已验证]
---

# riskbird_status 枚举定义

## 字段说明

`riskbird_status` 是侵权软件主表 `ds_risk_software_infringement_data` 中的状态控制字段，类型为 `tinyint(1)`，用于控制数据在风鸟端的可见性。

## 枚举值

| 值 | 含义 | 说明 |
|----|------|------|
| 0 | 正常显示 | 数据在风鸟端对用户可见 |
| 1 | 屏蔽 | 数据在风鸟端隐藏，不对用户展示 |

## 应用规则

- 风鸟端所有展示侵权软件数据的模块（企业主页、风险扫描、全文检索）均只查询 `riskbird_status = 0` 的数据
- 对应 SQL WHERE 条件：`WHERE riskbird_status = 0`
- 屏蔽原因（业务语义）在PRD中未说明，属于知识盲区⚠️

## 待确认

- 屏蔽（=1）的触发条件是什么？人工操作还是系统自动？
- 是否有其他枚举值（如 2=待审核）？

## 关联

- [[约束-ds_risk_software_infringement_data表结构]]
- [[概念-侵权软件]]
