"""啄木鸟 v2 路线图步骤 2+3 演示 — InternalFinding ↔ RenderedFinding + profile 过滤.

用 mock items 渲染 chill 和 strict 两版报告, 打印对比:
- chill: 隐藏 could (nitpick) + should 中 confidence ≤ 0.8 的不展示
- strict: 全部 print (历史行为)

同时验证 InternalFinding ↔ dict 互转 (向后兼容现有 review_items.json 裸 dict 格式).

运行:
    cd "C:/Users/20834/Desktop/agent/prd review"
    python scripts/demo_schema_profile.py
"""
import io
import json
import sys
from pathlib import Path

# Windows GBK 终端兼容: 强制 stdout UTF-8 (中文 + 箭头符号才能 print)
if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent.parent))

from review.finding_schema import (
    InternalFinding,
    RenderedFinding,
    PROFILE_CHILL,
    PROFILE_STRICT,
    filter_by_profile,
    to_rendered,
)
from report_builder import build_actionable_report


# ============================================================
# Mock items (覆盖 must / should / could 三档 + 不同 confidence)
# ============================================================
MOCK_ITEMS = [
    {
        "id": "R-001",
        "rule_id": "V-04",
        "severity": "must",
        "evidence_type": "A",
        "location": "二、企业主页 / 1.4 脱敏规则",
        "issue": "规则写双星号但示例只有 1 颗星, 1 字名到底打几颗?",
        "suggestion": "改成「保留姓氏, 名字部分每字替换为一个*」, 并补充: 张三→张*, 张三丰→张**",
        "evidence_content": "[A] 规则原文「姓+**」与示例「欧阳修→欧阳*」星号数量不一致",
        "dimension": "结构层",
        "confidence_score": 0.9,
        "status": "pending",
        "verification_status": "verified",
    },
    {
        "id": "R-002",
        "rule_id": "RC-005",
        "severity": "should",
        "evidence_type": "B",
        "location": "三、搜索结果页 / 2.1 排序",
        "issue": "默认排序未给出明确规则, 多结果时无法预判先后",
        "suggestion": "在 2.1 节加一行: 默认按相关度降序, 同分按注册时间倒序",
        "evidence_content": "RC-005 要求所有列表交互必须指定默认排序",
        "dimension": "交互层",
        "confidence_score": 0.85,  # >0.8, chill 模式仍展示
        "status": "pending",
        "verification_status": "verified",
    },
    {
        "id": "R-003",
        "rule_id": "RC-007",
        "severity": "should",
        "evidence_type": "B",
        "location": "三、搜索结果页 / 2.3 分页",
        "issue": "分页大小未给, 首屏可能截断重要数据",
        "suggestion": "建议 pageSize=20, 详见 RC-007",
        "evidence_content": "RC-007 列表分页规范",
        "dimension": "交互层",
        "confidence_score": 0.6,  # ≤0.8, chill 模式隐藏
        "status": "pending",
        "verification_status": "unchecked",
    },
    {
        "id": "R-004",
        "rule_id": "EV-02",
        "severity": "could",
        "evidence_type": "C",
        "location": "二、企业主页 / 1.5 收藏",
        "issue": "收藏数量上限未给, 可能导致 VIP 与普通用户体感无差异",
        "suggestion": "在 1.5 节加: 收藏数量上限 10 条 (VIP 100 条)",
        "evidence_content": "外部参考: ⚠️ 待确定 (竞品企查查上限 50 条)",
        "dimension": "完整层",
        "confidence_score": 0.5,
        "status": "pending",
        "verification_status": "unchecked",
        "facet_of": "R-001",  # 苍鹰冲突合并保留的同源条
    },
]


PRD_MOCK = """# 企业信息查询 PRD v1.0
## 二、企业主页
### 1.4 脱敏规则
| 申请人/被申请人中的自然人 | 姓+** | 张三 → 张** / 欧阳修 → 欧阳*（注意「复姓」的打码） |

### 1.5 收藏
- 用户可对企业页执行收藏操作
- VIP 用户拥有更多权益

## 三、搜索结果页
### 2.1 排序
搜索结果支持按时间/相关度/规模排序

### 2.3 分页
列表支持上下翻页
"""


# ============================================================
# Demo 1: InternalFinding ↔ dict 互转
# ============================================================
def demo_dataclass_roundtrip():
    print("=" * 70)
    print("[Demo 1] InternalFinding ↔ dict 互转 (向后兼容验证)")
    print("=" * 70)

    raw = MOCK_ITEMS[0]
    finding = InternalFinding.from_dict(raw)
    print(f"\n  dict → InternalFinding:")
    print(f"    id={finding.id}, severity={finding.severity}")
    print(f"    rule_id={finding.rule_id}, confidence={finding.confidence_score}")
    print(f"    issue={finding.issue[:40]}...")

    back = finding.to_dict()
    print(f"\n  InternalFinding → dict (字段数 {len(back)}):")
    for k in sorted(back.keys())[:6]:
        print(f"    {k!r:25} -> {str(back[k])[:50]!r}")
    print(f"    ... (共 {len(back)} 字段)")

    # 缺字段容错: 只塞 id + severity
    minimal = InternalFinding.from_dict({"id": "R-X", "severity": "must"})
    print(f"\n  容错 (缺字段走默认值):")
    print(f"    id={minimal.id}, evidence_type={minimal.evidence_type!r} (空)")
    print(f"    confidence_score={minimal.confidence_score} (默认 0.5)")

    # 兼容 problem 字段 (cuckoo_parser 老 schema)
    legacy = InternalFinding.from_dict({"id": "R-Y", "problem": "老 parser 用 problem"})
    print(f"\n  兼容 cuckoo_parser problem 字段:")
    print(f"    issue={legacy.issue!r} (从 problem 转入)")
    print()


# ============================================================
# Demo 2: RenderedFinding 字段对比 (Internal 14+ 字段 vs Rendered 4 surface 字段)
# ============================================================
def demo_internal_vs_rendered():
    print("=" * 70)
    print("[Demo 2] InternalFinding vs RenderedFinding 字段差")
    print("=" * 70)

    finding = InternalFinding.from_dict(MOCK_ITEMS[0])
    rendered = to_rendered(finding, quote="姓+** | 张三 → 张** / 欧阳修 → 欧阳*")

    internal_fields = list(finding.to_dict().keys())
    rendered_surface = ["title_with_location", "problem", "fix", "optional_quote"]
    rendered_meta = ["meta_location", "meta_severity", "meta_evidence_type",
                     "meta_dimension", "meta_rule_id", "meta_diff_status"]

    print(f"\n  InternalFinding: {len(internal_fields)} 字段 (给苍鹰/verifier/eval 全链路)")
    print(f"    {internal_fields}")
    print(f"\n  RenderedFinding surface: {len(rendered_surface)} 字段 (PM 报告主体)")
    for f in rendered_surface:
        v = getattr(rendered, f)
        print(f"    {f:25} -> {str(v)[:60]}")
    print(f"\n  RenderedFinding meta (sub 行, parser 抓): {len(rendered_meta)} 字段")
    for f in rendered_meta:
        v = getattr(rendered, f)
        if v:
            print(f"    {f:25} -> {v}")
    print()


# ============================================================
# Demo 3: profile 过滤对比
# ============================================================
def demo_profile_filter():
    print("=" * 70)
    print("[Demo 3] profile 过滤对比 (chill vs strict)")
    print("=" * 70)

    print(f"\n  原始 items: {len(MOCK_ITEMS)} 条")
    for it in MOCK_ITEMS:
        print(f"    {it['id']} severity={it['severity']:6} confidence={it['confidence_score']:.2f} - {it['issue'][:30]}")

    chill_items = filter_by_profile(MOCK_ITEMS, profile=PROFILE_CHILL)
    print(f"\n  chill 过滤后: {len(chill_items)} 条 (must 全留 + should >0.8 留 + could 隐藏)")
    for it in chill_items:
        print(f"    {it['id']} severity={it['severity']:6} confidence={it['confidence_score']:.2f}")

    strict_items = filter_by_profile(MOCK_ITEMS, profile=PROFILE_STRICT)
    print(f"\n  strict 过滤后: {len(strict_items)} 条 (全留)")
    for it in strict_items:
        print(f"    {it['id']} severity={it['severity']:6} confidence={it['confidence_score']:.2f}")
    print()


# ============================================================
# Demo 4: 完整报告渲染对比 (chill vs strict)
# ============================================================
def demo_full_report():
    print("=" * 70)
    print("[Demo 4] 完整报告渲染对比")
    print("=" * 70)

    chill_report = build_actionable_report(
        MOCK_ITEMS, PRD_MOCK, "企业信息查询 PRD v1.0",
        reviewer="demo", profile=PROFILE_CHILL,
    )
    strict_report = build_actionable_report(
        MOCK_ITEMS, PRD_MOCK, "企业信息查询 PRD v1.0",
        reviewer="demo", profile=PROFILE_STRICT,
    )

    print(f"\n  chill 报告: {len(chill_report)} 字符, "
          f"R-XXX 出现 {chill_report.count('### R-')} 次")
    print(f"  strict 报告: {len(strict_report)} 字符, "
          f"R-XXX 出现 {strict_report.count('### R-')} 次")

    print("\n" + "-" * 70)
    print("【chill 报告 摘要 (前 60 行)】")
    print("-" * 70)
    print("\n".join(chill_report.splitlines()[:60]))

    print("\n" + "-" * 70)
    print("【strict 报告 摘要 (前 60 行)】")
    print("-" * 70)
    print("\n".join(strict_report.splitlines()[:60]))
    print()


if __name__ == "__main__":
    demo_dataclass_roundtrip()
    demo_internal_vs_rendered()
    demo_profile_filter()
    demo_full_report()
    print("=" * 70)
    print("Demo 完成. 关键验证点:")
    print("  ✓ InternalFinding.from_dict 容忍缺字段 + 兼容 problem 字段")
    print("  ✓ RenderedFinding 只 surface 4 字段, 多余下沉到 meta sub")
    print("  ✓ chill 模式隐藏 could + 低置信 should, strict 全展示")
    print("=" * 70)
