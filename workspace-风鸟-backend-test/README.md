---
title: 风鸟后端测试 Agent 工作区
scope: riskbird-backend
category: test-agent-workspace
---

# workspace-风鸟-backend-test

风鸟后端测试侧 Agent(代号**百灵**)的工作区。

## 设计来源

借鉴三份材料综合设计:
- **胶水编程(天猫)**:让 AI 抄测试样板,不从零写
- **智能单测进化(快手)**:三段闭环 — 代码知识库 → 规则+知识驱动生成 → 编译+执行反馈修复
- **Claude Code 源码**:工具自包含 + Worktree 隔离 + 三层记忆

## 目录结构

```
workspace-风鸟-backend-test/
├── knowledge/              # 代码知识库(W1 产物)
│   ├── backend_call_graph.json  # Service 层调用图 + Mock 依赖清单
│   └── mock_templates/          # Mock 模板库
│       ├── shiro_auth.java.tmpl
│       ├── jpa_repository.java.tmpl
│       └── redis_cache.java.tmpl
├── reference/              # 测试样板间(未来 W2 扩)
├── output/
│   └── generated_tests/    # Agent 产出的测试代码
├── prd/                    # 占位(本 workspace 不做 PRD 评审)
└── wiki/                   # 占位(检索走 riskbird-knowledge MCP 或 wiki 路径)
```

## 风鸟后端源码路径

`C:\Users\20834\Desktop\RiskBirdApi\riskbird-core\src\main\java\com\xinshucredit\riskbird\`

- `service/` — 555 个 .java, 87 个 *Impl.java(本 agent 的主要目标)
- `dao/` — JPA Repository
- `bean/entity/` — JPA 实体
- `security/` — Shiro 配置
