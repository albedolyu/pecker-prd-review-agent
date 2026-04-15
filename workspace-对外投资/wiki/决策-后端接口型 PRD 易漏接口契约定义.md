---
title: 后端接口型 PRD 易漏接口契约定义
source: 啄木鸟评审提取
created: 2026-04-15
updated: 2026-04-15
tags: [memory/feedback, extracted/auto]
sources: 1
scope: workspace
category: decision
extracted_from: 评审对外投资 PRD
extracted_reviewer: xinshu
content_hash: 1987861e9996717d84d85addc139fdf0
---

# 后端接口型 PRD 易漏接口契约定义

PRD 描述业务功能（FR）依赖后端接口但未定义具体契约。漏报特征：技术约定节仅写基础路径和鉴权方式，未列出各 FR 对应的 endpoint、HTTP 方法、请求/响应体、状态码。检查规则应强制要求：功能数 ≤ 20 的 PRD 需 100% 覆盖接口定义，否则标记为 must-fix。（苍鹰补充 RC-005）

> 本页面由啄木鸟自动从 `评审对外投资 PRD` 评审会话中提取 (2026-04-15)
