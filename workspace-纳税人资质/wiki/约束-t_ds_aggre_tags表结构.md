---
source: 纳税人资质需求文档-v1.0.md
created: 2026-04-12
updated: 2026-04-12
tags: [domain/技术约束, status/已验证]
authority: contextual
owner: albedolyu
---

# 约束：t_ds_aggre_tags / t_ds_aggre_tags_assigned 表结构

## 已知信息（来自 PRD §5.3）

- `t_ds_aggre_tags`：存储企业标签定义，通过 `tagid` 区分标签类型
- `t_ds_aggre_tags_assigned`：存储企业已分配标签记录，用于查询符合条件的企业
- 纳税人资质相关 tagid：`99999997`、`99999998`

## 知识盲区 ⚠️

- 两张表的完整 DDL 未在 PRD 中提供
- `tagid` 与纳税人资格类型（小规模 / 一般纳税人）的映射关系未说明
- 关联键（entid 或其他字段）未在 §5.3 中明确标注
- 表中是否有 `data_status` 过滤字段，未知

## 关联
- [[概念-纳税人资质]]
- [[约束-ds_company_tax_state表结构]]
