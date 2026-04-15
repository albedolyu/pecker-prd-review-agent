---

source: 数据维度-对外投资增加间接投资_原始版本.md
created: 2026-04-12
updated: 2026-04-12
tags: [domain/对外投资, domain/数据契约, status/已验证]
sources: 0
title: 对外投资DDL
scope: workspace
category: constraint
---

# 约束-对外投资DDL

## 涉及物理表

### 1. 直接投资表：`ds_company_discover_invest`

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | bigint(20) | 主键，自增 |
| entid | bigint(20) | 企业UID（主体企业） |
| entid_inv | bigint(20) | 被投资企业UID |
| invest_name | varchar(200) | 对外投资企业名称 |
| entstatus | varchar(10) | 被投资企业状态（枚举值未定义⚠️） |
| entstatus_cn | varchar(200) | 被投资企业状态中文 |
| entstatus_gs | varchar(100) | 被投资企业状态（GS口径） |
| esdate | date | 成立日期 |
| invest_ratio | numeric | 持股比例 |
| data_status | tinyint | 数据状态（0有效,1历史,2删除,3去重） |
| create_time | timestamp | 创建时间 |
| update_time | timestamp | 更新时间 |

### 2. 间接投资表：`ds_invest_alpha`（PostgreSQL）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | int8 | 主键 |
| entid | int8 | 企业UID（主体企业） |
| invest_id | int8 | 被投资企业UID |
| invest_name | varchar(200) | 被投资企业名称 |
| invest_ratio | numeric(8,4) | 持股合计比例 |
| path_cnt | int4 | 股权路径数量 |
| invest_paths | text | 股权链数据（⚠️数据结构未定义，格式不明） |
| data_status | int2 | 数据状态 |
| create_time | timestamp | 创建时间 |
| update_time | timestamp | 更新时间 |

### 3. 企业基本信息表：`t_ds_company_basic`（部分关键字段）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| entid | bigint(20) | 企业UID（主键关联键） |
| entname | varchar(200) | 企业名称 |
| oper_name | varchar(100) | 法人代表 |
| regcap | decimal | 注册资本 |
| esdate | date | 成立日期 |
| prov_name | varchar(50) | 所属省份 |
| dom | varchar(500) | 注册地址 |
| nacaoid | varchar(11) | 组织机构代码（⚠️非行业分类字段，PRD伪代码误用） |
| nic_id | varchar(10) | 行业分类代码（17版，应为行业筛选字段） |
| nic_id_bak | varchar(10) | 行业分类代码（13版备用） |
| uniscid | varchar(50) | 统一社会信用代码 |
| data_status | tinyint | 数据状态 |

## ⚠️ 已知问题

1. **nacaoid 误用**：PRD §3.6 行业筛选伪代码使用 `nacaoid` 字段，但该字段实为"组织机构代码"，行业筛选应使用 `nic_id` 或 `nic_id_bak`
2. **invest_paths 结构未定义**：`ds_invest_alpha.invest_paths` 字段为 text 类型，PRD 未说明其数据结构（JSON？分隔符？）
3. **entstatus 枚举未定义**：`entstatus` 字段的完整枚举值在 PRD 中缺失

## 关联
- [[概念-对外投资]]
- [[场景-对外投资筛选逻辑]]
- [[概念-间接投资持股计算]]
