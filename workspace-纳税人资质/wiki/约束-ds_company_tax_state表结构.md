---
source: 纳税人资质需求文档-v1.0.md
created: 2026-04-12
updated: 2026-04-12
tags: [domain/技术约束, domain/数据, status/待验证]
authority: contextual
owner: albedolyu
---

# 约束：ds_company_tax_state 表结构

## 基本信息

- **表名**：`ds_company_tax_state`
- **所在数据库**：xs（经由 as 数据源接入）
- **数据来源**：国家税务总局公示数据

## 已知字段

| 字段名 | 类型 | 说明 | 枚举值 |
|--------|------|------|--------|
| entid | - | 企业唯一标识 | - |
| tax_type | - | 纳税人性质 | 小规模纳税人、一般纳税人、取消一般纳税人、null |
| edate | - | 认定/取消日期 | yyyy-MM-dd 格式 |

## 字段语义说明

- `edate` 在不同 `tax_type` 下含义不同：
  - `tax_type` = 小规模纳税人 / 一般纳税人 → edate 表示**认定日期**
  - `tax_type` = 取消一般纳税人 → edate 表示**取消日期**
- 企业可能存在**多条记录**，取 edate 最新的一条展示

## 已知问题（评审发现）

- DDL 未在 PRD 中完整定义，字段类型未知 → `status/待验证`
- edate 同日期平局处理规则未定义
- edate 为 null 时的排序规则未定义
- tax_type 为 null 时的前端降级策略未定义

## 数据链路

```
国家税务总局公示 → as 数据源 → xs 数据库 → ds_company_tax_state
```

- as/xs 系统的同步延迟和更新频率：`依据不足⚠️ — 未在 PRD 中说明`

## 关联

- [[概念-纳税人资质]]
- [[约束-企业标签表结构]]
- [[场景-企业主页纳税人资质展示]]
