---
title: 啄木鸟 v1.0 历史快照
status: frozen
do_not_edit: true
superseded_by: ../ (v1.2+)
---

# 历史快照 - 勿编辑

本目录是 **啄木鸟 v1.0 发布快照**，用于:

- 对比 v1.0 与主线(v1.2+)的代码差异
- 回溯历史 Agent 行为
- 发布版本号追溯

## 约定

**不要编辑本目录的任何文件。**

主线代码在项目根目录,所有新功能、bug fix、重构都只改根目录。

pyproject.toml 的 `[tool.pytest.ini_options].norecursedirs` 已显式排除本目录,pytest 不会 collect 这里的测试。

Grep 搜索时请手动过滤(`--glob '!pecker-release/**'` 或类似)。

如果 v1.0 有 bug 需要回 patch,走 git tag 发新分支,不在本目录原地修改。

## 关键时间线

- v1.0 冻结: 见 git log -- pecker-release/
- v1.1: PRD 评审 Agent 稳定版
- v1.2: harness 闭环 + 方法论沉淀(E5 加本文件)

归档由 Phase 5 E5 任务引入,目的是让 pecker-release/ 不再污染主线开发工作流。
