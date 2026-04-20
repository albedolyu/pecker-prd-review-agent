# parallel_review.py 拆分方案（已实施 2026-04-19）

> **状态**: 已完成。parallel_review.py 1223 → 78 行 facade,按 Cluster A/B/C/D/E/F 拆到
> review/dimensions.py + prompting.py + worker.py + orchestration.py + evidence_verify.py + aggregation.py。
> 对外 import 路径零改动,pytest 490 passed 零回归。测试 patch 路径已同步迁到 review.worker.*。
>
> 原始方案（保留备查）:
> 1833 行单文件,承担从 dimension 配置 → prompt 构建 → worker 执行 → 编排 → 依据验证 → 合并去重的全部职责。
> 按职责拆为 5 个模块 + 1 个 facade,不改变对外公共 API。工作量预估: 3-4 天。

---

## 一、按现有函数做的职责归类

grep 出的 32 个顶层定义,按职责聚簇如下:

### Cluster A — 配置加载与标签（约 330 行: L28-L354）

| 函数 | 行 | 用途 |
|---|---|---|
| `_add_freshness_note` | 28 | wiki 页新鲜度标注 |
| `build_wiki_manifest` | 42 | wiki 页清单构建 |
| `_get_rule_perf_history_path` | 60 | 反馈历史文件路径 |
| `_cn_label` | 78 | 中文术语映射 |
| `_validate_review_dimensions_yaml` | 231 | YAML schema 校验 |
| `load_review_dimensions` | 257 | 加载 review-dimensions.yaml |
| `get_review_dimensions` | 334 | 带缓存的 getter |
| `get_wiki_keywords` | 342 | 维度关键词提取 |
| `_get_compact_tool_schema` | 354 | 精简版 tool schema |

**职责**: 启动时从 yaml 读配置、从 wiki 建清单、术语转换。无状态,纯数据变换。

### Cluster B — Prompt 构建（约 340 行: L488-L823）

| 函数 | 行 | 用途 |
|---|---|---|
| `_build_worker_system` | 488 | Worker system prompt 组装 |
| `_build_feedback_section` | 523 | 反馈提示注入（impact_score + rejection_rate） |
| `_build_real_refs_section` | 656 | 防幻觉规则/wiki 清单注入 |
| `_maybe_compact_wiki` | 751 | wiki token budget 压缩 |
| `_build_worker_messages` | 762 | user message + PRD/wiki 组装 |

**职责**: 从配置和历史数据生成 Worker prompt。依赖 Cluster A 的输出。

### Cluster C — Worker 执行（约 360 行: L824-L1114）

| 函数 | 行 | 用途 |
|---|---|---|
| `_extract_items_from_response` | 824 | 从 tool_use 抽取 items（含 cross_boundary 校验） |
| `_has_tool_use` | 865 | 响应类型判断 |
| `_extract_text` | 870 | 纯文本抽取 |
| `_parse_items_from_text` | 875 | 文本兜底 JSON 解析 |
| `_worker_core` | 897 | **单 Worker 完整执行（核心）** |
| `_run_worker_async` | 1080 | async 包装 |
| `_run_worker_sync` | 1105 | sync 包装 |

**职责**: 一个 Worker 的完整生命周期。依赖 B 构建 prompt,调用 Claude API,解析输出。

### Cluster D — 并行编排（约 290 行: L1116-L1415）

| 函数 | 行 | 用途 |
|---|---|---|
| `_single_round_async` | 1116 | 4 Worker 单轮并行 |
| `parallel_review` | 1229 | **对外公共 API（async）** |
| `_single_round_sync` | 1292 | 单轮同步版 |
| `parallel_review_sync` | 1360 | **对外公共 API（sync）** |

**职责**: 多 Worker 并行调度 + 多轮投票。依赖 C 执行单 Worker。

### Cluster E — 依据验证（约 230 行: L1417-L1715）

| 函数 | 行 | 用途 |
|---|---|---|
| `_build_wiki_index` | 1417 | wiki 索引构建 |
| `verify_evidence` | 1428 | **A/B/C 三类依据硬验证** |
| `summarize_verification` | 1523 | 验证结果汇总 |
| `_verify_b_class_semantic` | 1571 | B 类语义相似度验证（P2.2） |
| `_find_wiki_page` | 1646 | wiki 页模糊匹配 |
| `_find_rule_reference` | 1681 | 规则编号存在性检查 |

**职责**: Worker 输出后的依据真实性/语义校验。独立于执行链,可以在任何阶段调用。

### Cluster F — 合并去重（约 120 行: L1716-L1833）

| 函数 | 行 | 用途 |
|---|---|---|
| `majority_vote` | 1716 | 多轮结果投票 |
| `merge_and_deduplicate` | 1790 | **跨 Worker items 去重合并** |

**职责**: 多个输出源的聚合。纯数据操作。

---

## 二、建议的目标结构

```
parallel_review/                  (原单文件 → 包)
├── __init__.py                   facade: 暴露原有 public API,保持 import 兼容
├── config.py                     Cluster A (~330 行)
├── prompting.py                  Cluster B (~340 行)
├── worker.py                     Cluster C (~360 行)
├── orchestration.py              Cluster D (~290 行)
├── evidence.py                   Cluster E (~230 行)
└── merging.py                    Cluster F (~120 行)
```

### `__init__.py` facade 示例（约 30 行）

```python
"""parallel_review 包 facade —— 保持对外 import 完全兼容

历史路径 `from parallel_review import parallel_review` 仍然可用。
"""
from .orchestration import parallel_review, parallel_review_sync
from .worker import _worker_core  # 允许 goshawk_advisor 等处直接引用
from .evidence import verify_evidence, summarize_verification
from .merging import merge_and_deduplicate, majority_vote
from .config import load_review_dimensions, get_review_dimensions, get_wiki_keywords

__all__ = [
    "parallel_review",
    "parallel_review_sync",
    "verify_evidence",
    "summarize_verification",
    "merge_and_deduplicate",
    "majority_vote",
    "load_review_dimensions",
    "get_review_dimensions",
    "get_wiki_keywords",
]
```

---

## 三、依赖方向与反模式检查

```
config  ←  prompting  ←  worker  ←  orchestration
                ↑             ↑
                └─ evidence ──┘  (可被 worker 内调或 orchestration 后调)
                              ↑
                              └─ merging  (仅被 orchestration 调)
```

- **单向依赖,无循环**: config 是叶子,merging 是树根,中间层向上引用
- **evidence 是横切关注点**: 可以被多处调用,不强制放到任一链路上
- **facade 只聚合不逻辑**: `__init__.py` 禁止放任何业务代码

---

## 四、迁移步骤（Big Bang 不推荐,分阶段）

### 阶段 0 — 准备（0.5 天）
- 建 `parallel_review/` 空包 + 空 `__init__.py`
- 在 CI 增加 `test_import_compat.py`,确保每个阶段后 `from parallel_review import *` 的符号集不变

### 阶段 1 — 最独立的 Cluster A 先出（0.5 天）
- 把 9 个函数搬到 `config.py`
- `__init__.py` 重新 export
- 跑 pytest,确保零回归

### 阶段 2 — Cluster F 合并去重（0.5 天）
- 纯数据逻辑,无外部依赖,风险最低
- 搬完后再跑 pytest

### 阶段 3 — Cluster E 依据验证（0.5 天）
- 搬到 `evidence.py`
- 唯一风险点: `_verify_b_class_semantic` 可能依赖 embedding client 初始化,注意 module-level 副作用

### 阶段 4 — Cluster B/C 一起搬（1 天）
- prompt 构建和 worker 执行耦合最深,一起搬更稳
- `_build_worker_system` ↔ `_worker_core` 有多个内部调用,拆两次会有大量 import 改动

### 阶段 5 — Cluster D 编排（0.5 天）
- 最后搬,依赖全部 cluster
- 搬完后,原 `parallel_review.py` 可变成空壳或删除

### 阶段 6 — 清理（0.5 天）
- 删除原 `parallel_review.py`
- 全局 grep 检查无人再直接 `from parallel_review.xxx` 走错路径
- 更新 `ARCHITECTURE.md` 的 File Mapping 表

---

## 五、风险点

1. **`_worker_core` 函数超长（~180 行）**: 拆分过程中不要顺手重构,保持函数边界不变,只移动。重构另算一次工作量
2. **模块级常量和配置**: 多个函数共享 `MAX_ITEMS_PER_WORKER`、`MAX_WORKER_TURNS` 等常量。建议集中放到 `config.py` 导出
3. **`_get_rule_perf_history_path`** 同时被 worker 和 orchestration 用到, 放 config 层
4. **test fixture 路径**: 现有 `tests/` 里若有 `from parallel_review import ...`  的私有函数,需要一起改 import
5. **`app.py` / `goshawk_advisor.py` 等上游引用**: 通过 facade 保持零改动

---

## 六、何时不该拆

- **如果近 2 周内有大的 harness 升级规划**: 拆分和功能开发同时进行会造成 merge 痛苦,先做功能
- **如果测试覆盖率 < 60%**: 拆分属于激进重构,没有测试兜底风险高
- **如果当前就 1 人维护**: 单文件的"坏"部分在多人协作,1 人维护情况下"好找"可能胜过"职责清晰"

当前项目测试 105 个基本覆盖核心链路,且维护者清楚每块逻辑。拆分动作适合在**两次 harness 大改之间的稳定期**做。

---

## 七、不推荐的替代方案

- **函数内部拆小函数**: 治标不治本,文件仍然长
- **按"新增 vs 老"切分**: 会产生 `parallel_review_v2.py` 这种反模式
- **全面重写**: 105 个 tests 的回归成本远超拆分收益

---

## 八、执行触发条件

建议满足以下任一条件后再启动本方案:

- [ ] 新增功能让 parallel_review.py 突破 2000 行
- [ ] 超过 1 个新贡献者加入项目
- [ ] 单次修改需要同时 touch 3 个以上 cluster
- [ ] 出现一次"改 A 区意外影响 B 区"的回归 bug
