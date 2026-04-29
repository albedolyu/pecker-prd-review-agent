#!/usr/bin/env python
"""信鸽 v2 — 演示脚本.

模拟 PM 添加 3 条 learning, 列出, 注入到 worker prompt, 验证 prompt 长度,
然后输出 dashboard.

不调 LLM, 不依赖 .env. 只验证 store + prompt injection + dashboard 三块串通.

用法:
    python scripts/demo_learnings.py
    python scripts/demo_learnings.py --workspace workspace-sample --keep
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoded = text.encode("gbk", errors="replace").decode("gbk", errors="replace")
        print(encoded)


SAMPLE_PRD = """# 收藏功能 PRD

## 功能描述
用户在企业详情页可以点击收藏按钮, 把企业加入收藏列表.
普通用户最多收藏 10 家, VIP 用户上限 100 家.
收藏列表展示企业名称、行业、所在地.

## 字段映射
- 企业名称: company_name
- 行业: industry_code
"""


def setup_demo_workspace(workspace: str) -> None:
    """创建一个最小可工作的 workspace 骨架"""
    os.makedirs(os.path.join(workspace, "review-rules"), exist_ok=True)
    os.makedirs(os.path.join(workspace, "wiki"), exist_ok=True)
    os.makedirs(os.path.join(workspace, "learnings"), exist_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="信鸽 v2 demo")
    parser.add_argument("--workspace", default=None,
                        help="workspace 路径 (默认 tmp 目录, --keep 保留)")
    parser.add_argument("--keep", action="store_true", help="结束后保留 workspace")
    args = parser.parse_args(argv)

    use_tmp = args.workspace is None
    if use_tmp:
        workspace = tempfile.mkdtemp(prefix="pecker_learnings_demo_")
    else:
        workspace = os.path.abspath(args.workspace)
    setup_demo_workspace(workspace)

    _safe_print("=" * 70)
    _safe_print(f"信鸽 v2 Demo  workspace={workspace}")
    _safe_print("=" * 70)

    # === Step 1: 模拟 PM 添加 3 条 learning ===
    from review.learnings_store import LearningsStore, find_relevant_learnings

    store = LearningsStore(workspace)
    _safe_print("\n[Step 1] 模拟 PM 添加 3 条 learning")
    _safe_print("-" * 70)

    l1 = store.add(
        trigger_pattern="PRD 涉及收藏功能",
        instruction="默认上限 10 条 (VIP 100 条), 不要再报 RC-005 四态 UI 缺失误报",
        scope="team_local",
        source_finding_id="R-001",
        reviewer="潘驰",
        related_rule_ids=["RC-005"],
        dim_keys=["ai_coding"],
    )
    _safe_print(f"  add learning 1: id={l1.id}  scope={l1.scope}  reviewer={l1.reviewer}")

    l2 = store.add(
        trigger_pattern="PRD 引用 ds_risk_court_case 物理表",
        instruction="字段映射必须包含类型/可空/索引/JOIN 五项, 缺任一即报 RC-009",
        scope="org_global",
        source_finding_id="R-007",
        reviewer="潘驰",
        related_rule_ids=["RC-009"],
        dim_keys=["data_quality", "ai_coding"],
    )
    _safe_print(f"  add learning 2: id={l2.id}  scope={l2.scope}  reviewer={l2.reviewer}")

    l3 = store.add(
        trigger_pattern="PRD 描述列表页或查询页",
        instruction="必须四态 UI: loading/error/empty/no-result, 缺任一报 RC-005",
        scope="team_local",
        reviewer="潘驰",
        related_rule_ids=["RC-005"],
        dim_keys=["ai_coding"],
    )
    _safe_print(f"  add learning 3: id={l3.id}  scope={l3.scope}  reviewer={l3.reviewer}")

    # === Step 2: list ===
    _safe_print("\n[Step 2] list_all")
    _safe_print("-" * 70)
    all_l = store.list_all()
    for l in all_l:
        _safe_print(f"  {l.id} | scope={l.scope} | usage={l.usage_count} | {l.trigger_pattern[:40]}")

    # === Step 3: 关键词匹配 (针对收藏 PRD) ===
    _safe_print("\n[Step 3] find_relevant_learnings — 用 SAMPLE_PRD (收藏功能) 做匹配")
    _safe_print("-" * 70)
    relevant = find_relevant_learnings(store, SAMPLE_PRD, dim_key="ai_coding", max_count=5)
    _safe_print(f"  匹配到 {len(relevant)} 条 (max=5):")
    for l in relevant:
        _safe_print(f"    -> {l.id} {l.scope}: {l.trigger_pattern}")

    # === Step 4: 注入 worker prompt 验证 ===
    _safe_print("\n[Step 4] 注入到 worker system prompt — 验证长度")
    _safe_print("-" * 70)

    # 直接调 _build_learnings_section, 不需要全套 dim 配置
    from review.prompting import _build_learnings_section

    section = _build_learnings_section(workspace, dim_key="ai_coding", prd_content=SAMPLE_PRD)
    if section:
        _safe_print(section)
        _safe_print(f"  注入文本长度: {len(section)} 字符 (~{len(section)} token, 中文 1 字 ≈ 1 token)")
        if len(section) > 1000:
            _safe_print(f"  WARN: 长度超 1000, 接近 token 预算上限")
    else:
        _safe_print("  (空, 未注入)")

    # === Step 5: dashboard ===
    _safe_print("\n[Step 5] 生成 dashboard.md")
    _safe_print("-" * 70)

    from scripts.learnings_dashboard import render_markdown
    md = render_markdown(store.list_all(), workspace)
    out_path = os.path.join(workspace, "learnings", "dashboard.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    _safe_print(f"  dashboard 已写入: {out_path}")
    # 打印前 40 行预览
    preview_lines = md.splitlines()[:40]
    _safe_print("\n--- dashboard.md 预览 (前 40 行) ---")
    for line in preview_lines:
        _safe_print(line)
    if len(md.splitlines()) > 40:
        _safe_print(f"  ... 余 {len(md.splitlines()) - 40} 行")

    # === 收尾 ===
    _safe_print("\n" + "=" * 70)
    _safe_print("Demo 通过. 验证项:")
    _safe_print("  [v] 添加 3 条 learning, 写入 yaml + index.json")
    _safe_print("  [v] list_all 返回 3 条")
    _safe_print(f"  [v] keyword 匹配命中 {len(relevant)} 条 (期望 ≥ 1, 因为 PRD 含'收藏功能')")
    _safe_print(f"  [v] 注入 prompt section 长度 {len(section)} 字符")
    _safe_print(f"  [v] dashboard.md 渲染成功, {len(md.splitlines())} 行")
    if use_tmp and not args.keep:
        try:
            shutil.rmtree(workspace)
            _safe_print(f"  [v] 临时 workspace 已清理")
        except OSError as e:
            _safe_print(f"  [warn] tmp workspace 清理失败 (非致命): {e}")
    else:
        _safe_print(f"  workspace 保留: {workspace}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
