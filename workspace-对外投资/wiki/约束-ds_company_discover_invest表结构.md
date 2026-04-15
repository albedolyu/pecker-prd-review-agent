---

source: 数据维度-对外投资增加间接投资_原始版本.md
created: 2026-04-12
updated: 2026-04-12
tags: [domain/对外投资, status/已验证]
sources: 0
title: ds_company_discover_invest表结构
scope: workspace
category: constraint
---

# 约束-ds_company_discover_invest 表结构

## 说明

直接投资物理表，记录企业直接持股关系。

## DDL（摘要）

```sql
CREATE TABLE `ds_company_discover_invest` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `entid` bigint(20) NOT NULL DEFAULT '0' COMMENT '企业UID',
  `entid_inv` bigint(20) NOT NULL DEFAULT '0' COMMENT '对外投资企业UID',
  `invest_name` varchar(200) NOT NULL COMMENT '对外投资企业名称',
  `entstatus` varchar(10) DEFAULT NULL COMMENT '被投资企业状态',
  `entstatus_cn` varchar(200) DEFAULT NULL COMMENT '被投资企业状态中文',
  `entstatus_gs` varchar(100) DEFAULT NULL COMMENT '被投资企业企业状态名称(GS)',
  `esdate` date DEFAULT NULL COMMENT '成立日期',
  `invest_ratio` decimal(18,4) DEFAULT NULL COMMENT '持股比例',
  `data_status` tinyint(2) NOT NULL DEFAULT '0' COMMENT '数据状态（0有效,1历史,2删除,3去重）',
  `create_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`)
);
```

## 关键字段说明

| 字段 | 含义 | 备注 |
|------|------|------|
| `entid` | 母公司 UID | 关联 t_ds_company_basic.entid |
| `entid_inv` | 被投资企业 UID | 关联 t_ds_company_basic.entid 获取企业详情 |
| `invest_ratio` | 直接持股比例 | decimal(18,4)，前端展示保留4位小数百分比 |
| `entstatus` | 经营状态码 | 枚举值未在PRD中定义 ⚠️ |
| `data_status` | 数据有效性 | 0=有效，查询时须加 WHERE data_status=0 |

## 评审发现的问题

- `entstatus` 枚举值未定义（盲区 ⚠️）
- 行业字段缺失，行业筛选需 JOIN `t_ds_company_basic`

## 关联

- [[概念-对外投资]]
- [[约束-t_ds_company_basic表结构]]
- [[场景-直接投资列表页]]
