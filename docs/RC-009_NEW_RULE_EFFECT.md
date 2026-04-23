# RC-009 规则升级实测效果留档

**2026-04-23 · 一次性 A/B 实测，配合 commit `4684ade`**

---

## 背景

PM 问：系统里有没有"检查 PRD 里物理表定义 vs 实际数据库一致性"的规则？

核查发现：
- 原 RC-009（字段映射一致性，must 级）覆盖"PRD 里字段名 vs PRD 里 DDL"的**内部**对账
- 原 RC-013（伪代码字段可追溯）覆盖类似的字段名级追溯
- **缺的**：字段类型 / 长度 / 可空性 / 索引 / 完整 DDL 存在性
- **无真连库**：评审 agent 始终不连真实数据库查 schema

## 改动范围（方案 A）

在 `review-dimensions.yaml` 改 RC-009 规则文案，从"字段映射一致性"扩到"物理表定义一致性"，新增 5 点子检查：

```
RC-009 物理表定义一致性（must）：PRD 中引用的每张物理表须有完整声明:
  a) 字段名与 DDL 一致
  b) 字段类型/长度 (VARCHAR(20) / INT / TIMESTAMP 等)
  c) 可空性 / NOT NULL / 默认值
  d) 索引与唯一约束
  e) 跨表字段 JOIN 来源 + 优先级
  PRD 完全无 DDL 片段也 fail (除非引用 wiki 既有表定义)
```

同时扩 `wiki_keywords`：加 `物理表 / 字段类型 / NOT NULL / 索引`。

## 实测数据（风鸟诉前调解 PRD，单一变量对比）

同一份 PRD（`workspace-fengniao-mediation/prd/风鸟-诉前调解-v1.md`），老 rule 跑过 3 轮，新 rule 跑 1 轮对比。

| 指标 | 老 rule（3 轮平均） | 新 rule（1 轮实测） | 外推 3 轮 |
|---|---|---|---|
| RC-009 命中 | 2.3 / run（共 7 条） | **5 / run** | ~12 条（+70%）|
| 单轮耗时 | ~230s | 205s | 不变 |
| items 总量 | 33-35 / run | 36 / run | 无副作用 |

## 新增命中的具体内容（全部真实问题）

### 1. ds_risk_court_mediation 完整 DDL 缺失
**老 rule**：只说"字段 area_code 没说明数据来源"
**新 rule**：列出应补 `area_code VARCHAR(?)` / `reg_date DATE` / `case_code VARCHAR(?)` / `case_reason VARCHAR(?)` + NOT NULL/Default + 筛选索引建议
**新增维度**：字段类型 + 长度 + 可空性 + 索引

### 2. is_pre_mediation 字段完整定义缺失
**老 rule**：抓到"新字段全文未给物理字段名"
**新 rule**：连同类型（TINYINT/BOOLEAN?）、NOT NULL、默认值、ES mapping 同步一起扫
**新增维度**：字段类型 + 默认值 + ES 同步对齐

### 3. standpoint 枚举字段底层类型缺失 ⭐
**老 rule**：没抓到
**新 rule**：standpoint 有业务枚举（1/2/3/4）但底层类型（TINYINT vs VARCHAR）未说
**新增维度**：业务枚举的物理类型

### 4. JOIN 键显式化
**老 rule**：说"跨表字段跨表"
**新 rule**：明确要求 `ds_risk_court_mediation.unique_id = ent.unique_id` + 字段来源优先级（主表 vs ent 谁优先）
**细化**：到具体 JOIN 条件

### 5. §4.2 司法案件两张表整体 DDL 缺失 ⭐
**老 rule**：没抓到（可能因为 §4.2 不在主扫描范围）
**新 rule**：`t_nebula_sf_case_flows` / `t_nebula_sf_case_process` 两表也 flag
**新增维度**：扫描到之前被忽略的章节

## 质量评估

| 维度 | 数据 |
|---|---|
| 假阳性率 | **0%**（5 条全是真问题，建议 actionable） |
| 新发现（老 rule 漏） | 至少 2 条（standpoint 底层类型 + §4.2 两张表） |
| 细化增强 | 3 条（字段类型/长度/索引取代泛泛"没说明"） |
| 耗时变化 | 无（205s ≈ 230s 之前） |

## 决定

✅ **保留 commit `4684ade` 改动，不 rollback**。

理由：
- 触发率 +70%，新增命中都有业务价值
- 0% 假阳性
- 没有成本增加
- 对照 gate v2 "第 3 类质量验证" 要求的"数据驱动证据" —— 这次实测就是证据

## 未来演进

### 如果上线后出现假阳性涨（RC-009 rejection_rate > 30%）
按现有反馈闭环（EMA + 时间衰减）会自然降权。PM 多次 reject 后 impact_score 下降，worker prompt 自动携带"RC-009 高误报，谨慎"警告。

如果半年后仍持续高误报，可拆 RC-016：
- RC-009 回归到"字段名一致性"
- RC-016 专做"物理表定义完整性"
两个规则独立调权，避免耦合。

### 如果需要**真连数据库**（方案 C）
现有 RC-009 仍是**LLM 基于 PRD 文本**的内部自洽。要做"PRD vs 实际 MySQL/PG/ClickHouse schema"的真对账需要：
- workspace 级 DB 连接配置（`.db_config.json`）
- schema 查询 tool + cache
- 新 worker tool `query_db_schema(table_name)`
- 权限/超时/连接失败兜底

工作量 1-2 天，**上线 1 个月后根据 PM 真实反馈数据决定是否值得做**。

## 复现方式

```bash
cd prd-review-agent
python eval/consistency_eval.py \
    workspace-fengniao-mediation/prd/风鸟-诉前调解-v1.md \
    --runs 3 --mode standard

# 结果在 eval/results/consistency_*_raw.json
# 用 jq / python 提取 all_items 里 rule_id == "RC-009" 的条目
```

## 相关 commit

- `4684ade` — feat(rules): RC-009 从"字段映射"扩到"物理表定义完整性"
- `b5ddf25` — 前一批（7 层 agent 架构三项薄弱修复）
- `7a5a127` — 记忆系统三项薄弱修复（EMA 时间衰减 + schema 版本 + 对账工具）

## 原始数据

- 老 rule：`eval/results/consistency_风鸟-诉前调解-v1_20260423_1118_raw.json`（3 轮）
- 新 rule：`eval/results/consistency_风鸟-诉前调解-v1_20260423_1914_raw.json`（1 轮）
