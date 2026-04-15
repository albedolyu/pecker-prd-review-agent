---

source: 数据维度-对外投资增加间接投资_原始版本.md
created: 2026-04-12
updated: 2026-04-12
tags: [domain/对外投资, status/已验证]
sources: 0
title: t_ds_company_basic表结构
scope: workspace
category: constraint
---

# 约束-t_ds_company_basic表结构

企业基本信息表，被对外投资模块通过 `entid_inv` / `invest_id` JOIN 使用。

## 关键字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| entid | bigint | 企业UID（主键） |
| entname | varchar(200) | 企业名称 |
| oper_name | varchar(100) | 法人代表 |
| regcap | decimal | 注册资本 |
| regcap_cur | varchar(20) | 注册资本币种 |
| esdate | date | 成立日期 |
| prov_name | varchar(50) | 省份 |
| city_name | varchar(50) | 城市 |
| nic_id | varchar(10) | 行业分类代码（17版） |
| nic_id_bak | varchar(10) | 行业分类代码（13版） |
| nacaoid | varchar(11) | 组织机构代码（⚠️ 非行业字段） |

## ⚠️ 注意
- `nacaoid` 是组织机构代码，**不是**行业分类字段
- 行业筛选应使用 `nic_id` 或 `nic_id_bak`，PRD §3.6 伪代码中误用了 `nacaoid`（见改进项 R-005）

## 关联
- [[概念-对外投资]]
- [[约束-ds_company_discover_invest表结构]]
- [[约束-ds_invest_alpha表结构]]
- [[场景-直接投资列表页]]
- [[场景-间接投资列表页]]
