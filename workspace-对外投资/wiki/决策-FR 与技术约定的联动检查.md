---
title: FR 与技术约定的联动检查
source: 啄木鸟评审提取
created: 2026-04-15
updated: 2026-04-15
tags: [memory/feedback, extracted/auto]
sources: 1
scope: workspace
category: decision
extracted_from: 对外投资基线v4
extracted_reviewer: default
content_hash: 86523e4772e47b9ce3f92464c3219b90
authority: contextual
owner: albedolyu
---

# FR 与技术约定的联动检查

功能需求列表中定义的每条 FR 若涉及后端接口调用，技术约定章节必须补齐对应的接口契约（endpoint、HTTP 方法、请求/响应体结构）。漏报 RC-005 即源于 8 条 FR 与 8 个待定接口的协调性缺失。建议在技术约定审核时新增规则：'FR_API_contract_completeness'。

> 本页面由啄木鸟自动从 `对外投资基线v4` 评审会话中提取 (2026-04-15)
