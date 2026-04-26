---
title: 投资数据源和 API 基础约定
source: 啄木鸟评审提取
created: 2026-04-15
updated: 2026-04-15
tags: [memory/reference, extracted/auto]
sources: 1
scope: workspace
category: constraint
extracted_from: 对外投资基线v8
extracted_reviewer: default
content_hash: d11bf8a99979552022c024d7090a85ab
authority: contextual
owner: albedolyu
---

# 投资数据源和 API 基础约定

数据源名：ds_invest_alpha（PostgreSQL）。DDL 特征：schema 前缀 ds_company、nextval() 序列、端口 5432。API 基础路径：/api/v1。鉴权：JWT。参考 PRD：对外投资基线v8 §2.0 & 技术约定节。

> 本页面由啄木鸟自动从 `对外投资基线v8` 评审会话中提取 (2026-04-15)
