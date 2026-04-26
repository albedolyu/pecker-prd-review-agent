---

source: 数据维度-对外投资增加间接投资_原始版本.md
created: 2026-04-12
updated: 2026-04-12
tags: [domain/对外投资, status/已验证]
sources: 0
title: ds_invest_alpha表结构
scope: workspace
category: constraint
authority: generated
owner: pecker-auto
---

# 约束-ds_invest_alpha 表结构

## 表说明

间接投资穿透表，记录企业通过多层股权穿透后的间接持股关系。

## DDL

```sql
CREATE TABLE ds_invest_alpha (
    id int8 DEFAULT nextval(...) NOT NULL,
    entid int8 NOT NULL,               -- 查询企业UID
    invest_id int8 NULL,               -- 被投资企业UID
    invest_name varchar(200) NULL,     -- 被投资企业名称
    invest_ratio numeric(8,4) NULL,    -- 间接持股比例
    path_cnt int4 NULL,                -- 股权路径数量
    invest_paths text NULL,            -- 股权链路（数据结构待明确⚠️）
    data_status int2 NULL,
    create_time timestamp(0) NULL,
    update_time timestamp(0) NULL
);
```

## 关键字段说明

| 字段 | 说明 | 盲区 |
|------|------|------|
| invest_ratio | 间接持股合计比例 | 计算规则未明确（乘积链/最小值？）⚠️ |
| invest_paths | 股权链路 | 数据结构（JSON/分隔符）未定义⚠️ |
| path_cnt | 路径数量 | 与 invest_paths 的关系未说明 |

## 关联

- [[概念-对外投资]]
- [[约束-ds_company_discover_invest表结构]]
- [[约束-t_ds_company_basic表结构]]
- [[场景-间接投资列表页]]
