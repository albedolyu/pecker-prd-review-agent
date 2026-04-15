---
title: 投资类 PRD 的数据源特性
source: 啄木鸟评审提取
created: 2026-04-15
updated: 2026-04-15
tags: [memory/project, extracted/auto]
sources: 1
scope: workspace
category: entity
extracted_from: 对外投资基线v4
extracted_reviewer: default
content_hash: f162838fc244582036aed25e87c5fe55
---

# 投资类 PRD 的数据源特性

对外投资相关 PRD 通常涉及 t_ds_company_basic（企业基础）+ ds_company_discover_invest（投资关联）的多表协作。行业分类常见的陷阱：表中仅存 nic_id、nic_id_cn、nic_id_bak、nic_id_bak_cn，不存在预计算的 level1/level2 字段，二级筛选需通过额外 lookup 或字典映射实现。

> 本页面由啄木鸟自动从 `对外投资基线v4` 评审会话中提取 (2026-04-15)
