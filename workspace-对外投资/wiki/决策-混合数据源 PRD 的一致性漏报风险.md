---
title: 混合数据源 PRD 的一致性漏报风险
source: 啄木鸟评审提取
created: 2026-04-15
updated: 2026-04-15
tags: [memory/feedback, extracted/auto]
sources: 1
scope: workspace
category: decision
extracted_from: 对外投资基线v3
extracted_reviewer: default
content_hash: 4034d7acce57b9a3a5ce606128d4b52e
authority: contextual
owner: albedolyu
---

# 混合数据源 PRD 的一致性漏报风险

多数据库架构（MySQL + PostgreSQL 混合）的 PRD 在「数据源列表」和「连接信息详细说明」两处易出现驱动类型、连接池配置前后矛盾。未来评审此类 PRD 时，需在 RC-* 规则中强化数据源配置的跨章节一致性校验，避免 must 级问题遗漏。参考本次 R-001。

> 本页面由啄木鸟自动从 `对外投资基线v3` 评审会话中提取 (2026-04-15)
