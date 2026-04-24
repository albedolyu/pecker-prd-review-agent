# PM Reject Reason Schema v1

> **问题**: 当前 reject 只是负反馈,不告诉你"该修规则、修知识库、还是修模型链路"
>
> **目标**: 每次 reject 必须带 7 选 1 的 reason 分类,下游按 reason 路由到具体修法靶点

**立项日期**: 2026-04-24
**承接**: `legacy/app.py:356` 的 `"reason": ""` 自由文本字段,升级为枚举
**Sprint 关联**: [sprint-real-prd-calibration-evidence-governance.md](sprint-real-prd-calibration-evidence-governance.md) 主线 C+A 交叉

---

## 一、7 种 reason 枚举

```python
# models.py 新增
from enum import Enum

class RejectReason(str, Enum):
    GOOD_ISSUE = "good_issue"             # 实际是好问题 (手滑 / 改主意)
    FALSE_POSITIVE = "false_positive"     # 误报,PRD 确实没这问题
    KNOWN_TRADEOFF = "known_tradeoff"     # 已知取舍,业务允许
    WIKI_MISSING = "wiki_missing"         # 知识库缺上下文导致误判
    RULE_TOO_STRICT = "rule_too_strict"   # 规则太严,不适用本 PRD
    IMPL_DETAIL = "impl_detail"           # 实现细节,不该 PRD 管
    MODEL_NOISE = "model_noise"           # 模型噪音,无业务意义
```

---

## 二、每种 reason 的修法路由

| reason | 下游信号 | 修法靶点 | 自动化? |
|---|---|---|---|
| `good_issue` | 忽略 (用户体验,非校准信号) | — | — |
| `false_positive` | rule precision ↓,若触发 noisy 阈值降级 | `review-dimensions.yaml` rule `status` / `rule_perf_store` | ✓ 阈值触发 |
| `known_tradeoff` | 加 workspace 级 pin 或 project 级 ignore | `review-rules/ignore_list.yaml` | ✗ PM 手工 |
| `wiki_missing` | 补 canonical wiki 页 + 指定 owner | `wiki/{category}-{topic}.md` new page | ✗ PM 手工 |
| `rule_too_strict` | 规则改写 / 改 checklist / 加白名单 | `review-dimensions.yaml` rule 正文 | ✗ PM+研发 |
| `impl_detail` | 规则 scope 收窄到仅 PRD 级 | rule 描述加 "不涵盖实现细节" 约束 | ✗ PM 手工 |
| `model_noise` | 模型/prompt 调优 signal | worker prompt 迭代队列 | ✗ 迭代 |

**核心原则**: reject 不只是一个负样本,是一条**指向具体工程动作**的 work item 种子。

---

## 三、Schema 改动

### 3.1 前端/后端传输层

`decisions` payload 从:
```json
{"R-001": {"action": "reject", "reason": "太严了"}}
```
扩展为:
```json
{
  "R-001": {
    "action": "reject",
    "reason_category": "rule_too_strict",
    "reason_note": "规则要求 API 契约完整,但本 PRD 是前端交互文档不涉及后端"
  }
}
```

**向后兼容**:
- `reason` (旧字段,自由文本) → 读取时映射到 `reason_note`,不再写入
- `reason_category` 缺失时按 `"model_noise"` 记账 (最保守的假设,让 PM 尽快补上不阻塞流程)
- `action != "reject"` 时 `reason_category` 忽略

### 3.2 models.py

```python
# models.py 新增,渐进迁移

@dataclass
class PMDecision:
    item_id: str
    action: str                               # "accept" | "reject" | "edit"
    reason_category: str = ""                 # RejectReason value,仅 reject 时有效
    reason_note: str = ""                     # 可选自由文本补充
    edited_content: dict = field(default_factory=dict)   # action=edit 时的修改后内容

    @classmethod
    def from_dict(cls, item_id: str, d: dict) -> PMDecision:
        return cls(
            item_id=item_id,
            action=d.get("action", ""),
            reason_category=d.get("reason_category", d.get("reason", "")),
            reason_note=d.get("reason_note", d.get("reason", "")),
            edited_content=d.get("edited_content", {}),
        )
```

### 3.3 api/routes/review.py 改动

**3 处改动**:

#### 3.3.1 L593 附近 — rule_perf 回流时区分 reject 亚型

```python
# 老:
elif action == "reject":
    entry["stats"]["rejected"] += 1

# 新:
elif action == "reject":
    entry["stats"]["rejected"] += 1
    # 按 reason 分桶 (帮助周度 rule slim 判断)
    reason_cat = decision.get("reason_category", "model_noise")
    reject_by_reason = entry["stats"].setdefault("reject_by_reason", {})
    reject_by_reason[reason_cat] = reject_by_reason.get(reason_cat, 0) + 1
```

**收益**: 下游 `scripts/rule_lifecycle.py` 可以区分 "这条规则 rejection_rate 0.5,但其中 90% 是 `rule_too_strict`" vs "其中 90% 是 `false_positive`" — 前者改写,后者降级。

#### 3.3.2 L587-594 — reject delta 按 reason 分档

```python
# 老:
elif action == "reject":
    delta = -0.5

# 新:
elif action == "reject":
    reason_cat = decision.get("reason_category", "model_noise")
    # 只有明确"规则本身有问题"的 reason 才强惩罚
    delta_by_reason = {
        "false_positive": -0.5,     # 规则精度问题,强惩罚
        "rule_too_strict": -0.5,    # 规则严度问题,强惩罚
        "model_noise": -0.3,        # 模型问题,中等
        "wiki_missing": -0.1,       # 知识库问题,不该规则背锅,弱惩罚
        "known_tradeoff": -0.1,     # 业务取舍,弱惩罚
        "impl_detail": -0.3,        # 规则 scope 问题,中等
        "good_issue": 0.3,          # PM 手滑,正向微调回拨
    }
    delta = delta_by_reason.get(reason_cat, -0.3)
```

**收益**: `wiki_missing` 不再把规则打成 noisy (本来规则没错,只是缺背景),`good_issue` 甚至给正向反馈。EMA `impact_score` 更准确反映"规则本身好不好"。

#### 3.3.3 L641-648 — ground truth 记 reason

```python
# 老:
gt_items.append({
    "id": item_id,
    "rule_id": item.get("rule_id", ""),
    "location": item.get("location", ""),
    "severity": item.get("severity", ""),
    "action": action,
    "is_true_positive": action in ("accept", "edit"),
})

# 新:
gt_items.append({
    "id": item_id,
    "rule_id": item.get("rule_id", ""),
    "location": item.get("location", ""),
    "severity": item.get("severity", ""),
    "action": action,
    "reason_category": decision.get("reason_category", ""),  # NEW
    "reason_note": decision.get("reason_note", "")[:200],     # NEW,截断防爆
    "is_true_positive": action in ("accept", "edit"),
})
```

**收益**: `eval/ground_truth/*.json` 自动积累 reason 分类,主线 A 校准集分析时可以按 reason 切片。

---

## 四、Frontend (后做,本 spec 先不改前端)

Phase 3 reject 按钮点击后弹出 dropdown:
```
❌ 驳回
  ┬─ ❓ 其实是好问题
  ├─ 🚫 误报
  ├─ ⚖️ 已知取舍
  ├─ 📚 知识库缺失
  ├─ 🔒 规则太严
  ├─ 🛠 实现细节(不该 PRD 管)
  └─ 🎲 模型噪音
```

**前端 v1 落地前的兼容**: 老前端只传 `action: "reject"`,后端按 `"model_noise"` 默认记账。周报聚合上会看到"80% reject 是 model_noise" → 提示前端升级优先级高。

---

## 五、聚合与报告

### 5.1 周报 (`scripts/reject_reason_report.py`)

```python
# 聚合 eval/ground_truth/*.json 过去 7 天的 reject 分布
# 输出:
#
#   Top 5 规则 by rejection_rate:
#     1. RC-009  reject=47%  主因: rule_too_strict (32%) / false_positive (10%) ...
#                            → 建议: 改写规则,scope 收窄到 /api 节
#     2. RC-013  reject=38%  主因: wiki_missing (30%)
#                            → 建议: PM 补 3 个 wiki canonical 页,不动规则
```

### 5.2 每类 reason 的追踪指标

| reason | 追踪 | 响应阈值 |
|---|---|---|
| `false_positive` 占比 > 30% of rejects on a rule | 规则质量问题 | 自动降级到 experimental |
| `wiki_missing` 占比 > 40% | 知识库空洞 | 周报高亮,PM 补 wiki |
| `rule_too_strict` 占比 > 40% | 规则 scope 问题 | 周报高亮,PM + 研发 review 规则 |
| `model_noise` 占比 > 30% 且全局 | prompt 问题 | 下阶段 prompt 迭代 |

---

## 六、Migration 顺序

1. **Phase 0 (本 PR)**: 仅 spec 文档,不改代码
2. **Phase 1**: `models.py` 加 `RejectReason` enum + `PMDecision` dataclass (不强制调用)
3. **Phase 2**: `api/routes/review.py` 3 处改动 — 读 `reason_category` 字段,缺失时默认 `model_noise`,向后兼容;改 delta 按 reason 分档
4. **Phase 3**: 单测覆盖 7 种 reason × rule_perf 更新 × ground truth 写入
5. **Phase 4**: 前端 Phase 3 加 dropdown UI (另发 PR)
6. **Phase 5**: `scripts/reject_reason_report.py` 周报 CLI

**关键路径**: Phase 2 落地后就能开始积累 reason 分布 (即使前端还没改,`model_noise` 默认值至少让 schema 稳住),一周后就有数据可聚合。

---

## 七、测试策略

- 单测覆盖:
  - 7 种 reason × 正常 decision 写入 → rule_perf `reject_by_reason` 桶正确 +1
  - 7 种 reason × delta 分档 → impact_score 变化符合预期
  - `reason_category` 缺失 → 默认 `model_noise`
  - 旧 payload `{"action": "reject", "reason": "自由文本"}` → 读取时 `reason_note=自由文本` 不破坏
- 集成测:
  - 跑一次 Phase 3 confirm,7 条 reject × 7 种 reason,验证 `eval/ground_truth/*.json` 里每条都有 `reason_category`
  - rule_perf_store 的 `reject_by_reason` 桶聚合正确

---

## 八、Open questions

1. **`reason_category` 是否允许多选?** 当前单选。如果 PM 想说"既是 rule_too_strict 又是 wiki_missing",多选可能更准。→ 暂单选,观察第一周数据后再议。
2. **`edited_content` 也应该带 reason?** 当前 `action=edit` 是"问题真实但建议话术不好",不需要 reason。PM edit 本身已经是正反馈。→ 不加 reason
3. **默认值应该是 `model_noise` 还是空?** 空会让后端不写 `reject_by_reason` 桶,但 EMA 就没 delta。选 `model_noise` 默认值兜底,至少有数据。

---

## 九、首批落地 checklist

- [ ] `models.py` 加 `RejectReason` 枚举 + `PMDecision` dataclass
- [ ] `api/routes/review.py:575-605` 三处改动 + 兼容旧 payload
- [ ] `api/routes/review.py:641-648` `_save_eval_ground_truth` 加 `reason_category` + `reason_note`
- [ ] 单测: 7 种 reason × delta + rule_perf 分桶 + 兼容旧字段
- [ ] 跑一次集成测 (Phase 3 confirm 真走一遍) 确认 ground truth 产出符合 schema

---

**一句话**: reject 从"这条不要"升级为"这条不要,因为规则/知识库/模型的 X 处有问题"。
