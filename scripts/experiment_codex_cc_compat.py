#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
任务4: Pecker 跨 agent 风格兼容性 (Path B 模拟, 2026-04-28).

没 OPENAI_API_KEY 走 Path B: 用 Anthropic 模拟跨 vendor.
- Agent X = Sonnet 4.6 + lineage-aware system prompt (Claude Code 风格)
- Agent Y = Opus 4.7 + minimal-constraint system prompt (Codex 风格模拟)
- Judge = Sonnet 4.6 (5 维 + 2 计数)
- baseline endpoint: GET /api/v1/labour-arbitration/delivery/list
- spec: review_items_R2_2026_04_28.json (干净)
"""
from __future__ import annotations

import json
import os
import re
import shutil as _shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\Users\20834\Desktop\agent\prd review")
PRD_FILE = ROOT / "workspace-劳动仲裁" / "prd" / "劳动仲裁需求文档 v5.1.md"
PECKER_MD = ROOT / "workspace-劳动仲裁" / "output_full_prd_2026_04_28" / "pecker_delivery_list.md"

CLAUDE_EXE = _shutil.which("claude") or r"C:\Users\20834\AppData\Roaming\npm\claude.cmd"

AGENT_X_MODEL = "claude-sonnet-4-6"
AGENT_Y_MODEL = "claude-opus-4-7"
JUDGE_MODEL = "claude-sonnet-4-6"

OUT_DIR = ROOT / "workspace-劳动仲裁" / "output_codex_cc_compat_2026_04_28"
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_FILE = ROOT / "docs" / "codex_cc_compat_2026_04_28.md"


# Endpoint 信息 (跟任务1 baseline 一致)
ENDPOINT = {
    "name": "delivery/list",
    "method": "GET",
    "path": "/api/v1/labour-arbitration/delivery/list",
    "desc": "送达公告列表",
}


def load_prd_section() -> str:
    """同任务1: 取 §1 名词定义到 §3 关联系统交付."""
    text = PRD_FILE.read_text(encoding="utf-8")
    start_match = re.search(r"^## 1\.1 名词定义", text, re.MULTILINE)
    end_match = re.search(r"^## 3\. 关联系统交付", text, re.MULTILINE)
    if start_match and end_match:
        return text[start_match.start():end_match.start()]
    return text


def call_claude(model: str, system_prompt: str, user_prompt: str) -> tuple[str, dict]:
    """
    用 claude CLI subprocess 调. system + user 用 stdin 拼接.
    --append-system-prompt 仅 CLI 接受 -p 模式下系统消息附加.
    我们走 user prompt 内拼 [SYSTEM] 块的方式 (跟任务1一致, 但显式分块).
    """
    full = f"{system_prompt}\n\n---\n\n{user_prompt}"
    t0 = time.time()
    try:
        result = subprocess.run(
            [CLAUDE_EXE, "-p", "--model", model],
            input=full,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return "", {"error": "timeout", "duration_s": 600.0, "model": model}
    dt = time.time() - t0
    text = result.stdout or ""
    if result.returncode != 0:
        text = f"[STDERR]\n{result.stderr}\n[STDOUT]\n{text}"
    usage = {
        "duration_s": round(dt, 1),
        "model": model,
        "stdout_chars": len(result.stdout or ""),
        "returncode": result.returncode,
    }
    return text, usage


# ====== Agent X: Claude Code 风格 (lineage-aware) ======
AGENT_X_SYSTEM = """你是 Claude Code 风格的高级 Python 后端工程师 agent.

你的工作风格:
- 强调可追溯性 (lineage): 每个非 PRD 明示的字段都标 `# inferred: <理由>` 或 `# lineage: <issue.id>`
- PM-friendly: 注释里说人话, 不堆术语
- 严格按 Pecker spec 引用 rule_id
- must severity 必须落地并注释 issue.id; should severity 尽量落地; could severity 标 # TODO
- 模糊字段必须标 `# TODO: 待确认 - <原因>`
"""

# ====== Agent Y: Codex 风格 (minimal-constraint) ======
AGENT_Y_SYSTEM = """You are an experienced Python backend engineer.

Your style:
- Concise, idiomatic code. No verbose comments.
- Trust your judgment on naming, types, and structure.
- Focus on getting it working. Tests should be practical.
- Prioritize clean architecture over excessive documentation.
"""


# 用户 prompt 同款 (两个 agent 完全一样, 只换 system)
USER_PROMPT = """你的任务: 严格根据给定的输入 spec, 实现 {method} {path} endpoint ({desc}).

**必须输出 4 个段落 (markdown 标题严格按下列, 不要加多余标题)**:

## 1. DDL
PostgreSQL `CREATE TABLE` 语句 (1-2 张表, 字段含 type / nullability / 注释).

## 2. Pydantic schema
请求 query params 与 response 的 Pydantic v2 model.

## 3. FastAPI handler
完整 handler 函数 (含 db query 实现, 用 SQLAlchemy 或裸 sql 都行, 注释清晰).

## 4. Tests
5 个 pytest 用例, 覆盖 happy path + 边界 (空数据, page 越界 / 错误 type, 必填校验 等, 按 endpoint 实际语义选).

**约束**:
- 字段命名严格按 PRD / spec 来, 不要自己改名.
- 代码风格: 简洁、可运行、无 import 错误.

**输入 spec**: 下面是 Pecker (PRD review agent) 的结构化输出. 每条 issue 带 severity (must/should/could) / rule_id / location / suggestion.

PRD 也喂一份相关章节供查字段, 但 Pecker 的 issue 是真理之源.

---
## Pecker review 输出 (本 endpoint 相关)
{pecker_md}

---
## PRD 相关章节 (查字段用)
{prd_section}

---
现在开始按 4 段落输出实现.
"""


JUDGE_PROMPT = """你是高级架构师 + 资深 reviewer. 你的任务: 客观评估一份"劳动仲裁 {endpoint_desc}"({method} {path}) 的实现质量.

评估时, **必须严格根据 PRD 真实意图判定**, 不被实现的"看起来高级"误导.

## PRD 真实意图 (评估基准)
---
{prd_section}
---

## 待评估的实现
---
{implementation}
---

## 评分

按以下 5 个维度 1-5 评分 (整数), 1=极差, 5=极好:

1. **field_correctness**: 字段名/类型/约束是否符合 PRD (5=完全符合无错; 3=部分错或多了若干臆造字段; 1=多数错或大量编造)
2. **field_completeness**: 关键字段是否齐 (5=PRD 列表/接口的关键字段全有; 3=漏 1-2 个核心; 1=漏多个核心)
3. **lineage_quality**: 代码注释/spec 是否引用 PRD 章节 / Pecker rule_id / 标注 inferred (5=每非 PRD 明示字段都有溯源; 3=部分有; 1=完全编造无引用)
4. **ambiguity_handling**: 模糊字段是否标 `# TODO`/`# 待确认`/默认值 (5=主动标且给默认; 3=部分标; 1=瞎写没标)
5. **buildability**: 语法/类型/导入正确性 (5=能直接 pytest; 3=需小改; 1=语法错或缺关键 import)

外加 2 个计数 (整数):

- **clarification_count**: 实现里出现 `TODO` / `待确认` / `需要确认` 的次数
- **inferred_field_count**: PRD 没明示但实现自加的字段数

最后给 1 句话总评 (≤30 字).

**严格输出格式 (纯 JSON, 无前后语句, 无 ```json 围栏, 不写任何解释文字)**:

{{
  "field_correctness": <int 1-5>,
  "field_completeness": <int 1-5>,
  "lineage_quality": <int 1-5>,
  "ambiguity_handling": <int 1-5>,
  "buildability": <int 1-5>,
  "clarification_count": <int>,
  "inferred_field_count": <int>,
  "summary": "<1 句话总评>"
}}
"""


def parse_judge_json(text: str) -> dict:
    clean = text.strip()
    first = clean.find("{")
    last = clean.rfind("}")
    if first >= 0 and last >= 0 and last > first:
        clean = clean[first:last+1]
    try:
        return json.loads(clean)
    except Exception as e:
        return {
            "_parse_error": str(e),
            "_raw": text[:1000],
            "field_correctness": 0,
            "field_completeness": 0,
            "lineage_quality": 0,
            "ambiguity_handling": 0,
            "buildability": 0,
            "clarification_count": 0,
            "inferred_field_count": 0,
            "summary": "(judge parse failed)",
        }


def main():
    print("="*60, flush=True)
    print("Codex/CC 兼容性 (Path B 模拟, 2026-04-28)", flush=True)
    print(f"PRD: {PRD_FILE}", flush=True)
    print(f"Pecker spec (delivery/list filtered): {PECKER_MD}", flush=True)
    print(f"Agent X = {AGENT_X_MODEL} + lineage-aware", flush=True)
    print(f"Agent Y = {AGENT_Y_MODEL} + minimal-constraint", flush=True)
    print(f"Judge   = {JUDGE_MODEL}", flush=True)
    print("="*60, flush=True)

    if not PECKER_MD.exists():
        print(f"FATAL: pecker spec not found at {PECKER_MD}", flush=True)
        sys.exit(1)

    prd_section = load_prd_section()
    pecker_md = PECKER_MD.read_text(encoding="utf-8")
    print(f"\nPRD section: {len(prd_section)} chars", flush=True)
    print(f"Pecker md: {len(pecker_md)} chars", flush=True)

    user_prompt = USER_PROMPT.format(
        method=ENDPOINT["method"],
        path=ENDPOINT["path"],
        desc=ENDPOINT["desc"],
        pecker_md=pecker_md,
        prd_section=prd_section,
    )
    (OUT_DIR / "user_prompt.txt").write_text(user_prompt, encoding="utf-8")

    results = {}
    total_dur = 0.0

    for label, system, model in [
        ("agent_X", AGENT_X_SYSTEM, AGENT_X_MODEL),
        ("agent_Y", AGENT_Y_SYSTEM, AGENT_Y_MODEL),
    ]:
        print(f"\n{'='*40}\n[{label}] implement ({model})\n{'='*40}", flush=True)
        impl_text, impl_usage = call_claude(model, system, user_prompt)
        print(f"  done. {impl_usage}", flush=True)
        (OUT_DIR / f"impl_{label}.md").write_text(impl_text, encoding="utf-8")

        print(f"  [judge] {JUDGE_MODEL}...", flush=True)
        judge_text, judge_usage = call_claude(
            JUDGE_MODEL,
            "你是中立资深 reviewer.",
            JUDGE_PROMPT.format(
                method=ENDPOINT["method"],
                path=ENDPOINT["path"],
                endpoint_desc=ENDPOINT["desc"],
                prd_section=prd_section,
                implementation=impl_text,
            ),
        )
        judge = parse_judge_json(judge_text)
        print(f"    parse_ok={'_parse_error' not in judge}, "
              f"scores={judge.get('field_correctness')}/{judge.get('field_completeness')}/"
              f"{judge.get('lineage_quality')}/{judge.get('ambiguity_handling')}/"
              f"{judge.get('buildability')}", flush=True)
        (OUT_DIR / f"judge_{label}.json").write_text(
            json.dumps(judge, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        ep_dur = impl_usage.get("duration_s", 0) + judge_usage.get("duration_s", 0)
        total_dur += ep_dur
        results[label] = {
            "model": model,
            "system_style": "lineage-aware" if label == "agent_X" else "minimal-constraint",
            "impl_usage": impl_usage,
            "judge_usage": judge_usage,
            "judge": judge,
            "duration_s": round(ep_dur, 1),
        }

    # 汇总
    summary = {
        "endpoint": ENDPOINT,
        "spec_source": str(PECKER_MD),
        "judge_model": JUDGE_MODEL,
        "path_b_caveat": "用 Anthropic 模拟跨 vendor (没 OPENAI_API_KEY)",
        "total_duration_s": round(total_dur, 1),
        "results": results,
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    # 报告
    jx = results["agent_X"]["judge"]
    jy = results["agent_Y"]["judge"]
    score_keys = ["field_correctness", "field_completeness", "lineage_quality",
                  "ambiguity_handling", "buildability"]
    total_x = sum(jx.get(k, 0) for k in score_keys if isinstance(jx.get(k), (int, float)))
    total_y = sum(jy.get(k, 0) for k in score_keys if isinstance(jy.get(k), (int, float)))
    lineage_delta = (jx.get("lineage_quality", 0) or 0) - (jy.get("lineage_quality", 0) or 0)

    delta_table = []
    for k in score_keys:
        vx = jx.get(k, 0) if isinstance(jx.get(k), (int, float)) else 0
        vy = jy.get(k, 0) if isinstance(jy.get(k), (int, float)) else 0
        delta_table.append(f"| {k} | {vx} | {vy} | {vx - vy:+d} |")

    # transferable verdict (heuristic)
    if abs(lineage_delta) <= 1 and (jx.get("lineage_quality", 0) or 0) >= 4 and (jy.get("lineage_quality", 0) or 0) >= 4:
        verdict_lineage = "**lineage_quality 跨 agent 风格 transferable** (双方 >= 4 且 Δ <= 1)"
    elif abs(lineage_delta) <= 1:
        verdict_lineage = f"**lineage 跨风格表现一致但偏低** (Δ={lineage_delta}, 双方都 < 4 — spec 没起到 lineage 拉动作用)"
    else:
        verdict_lineage = f"**lineage 跨风格显著差异** (Δ={lineage_delta}, X={jx.get('lineage_quality')} vs Y={jy.get('lineage_quality')}) — spec 可能 over-fit X 的风格"

    over_fit_verdict = "spec 跨风格输出基本一致" if abs(total_x - total_y) <= 3 else f"spec 在 X 风格优势明显 (Δtotal={total_x - total_y})"

    report = f"""# Pecker 跨 agent 风格兼容性 (2026-04-28) — Path B 模拟

## 任务

- baseline endpoint: GET /api/v1/labour-arbitration/delivery/list (跟任务 1 baseline 一致)
- spec 输入: `workspace-劳动仲裁/output/review_items_R2_2026_04_28.json` (干净 setup, 0 幻觉 ID)
- 用任务1已 filter 好的 `pecker_delivery_list.md` 作为 spec md (复用 task1 setup)
- Agent X = `{AGENT_X_MODEL}` + lineage-aware system prompt (Claude Code 风格)
- Agent Y = `{AGENT_Y_MODEL}` + minimal-constraint system prompt (Codex 风格模拟)
- Judge   = `{JUDGE_MODEL}` (5 维 + 2 计数)

## Path B Caveat

**没 OPENAI_API_KEY 配置, 走 Path B**: 用 Anthropic 模拟跨 vendor.

- 测的不是真跨 vendor (Codex API)
- 测的是 **不同 model + 不同 prompt 风格** 在同一份 Pecker spec 上的输出差异
- 真跨 vendor 验证需等 PM 配 OPENAI_API_KEY 后用 Path A 跑

## 评分对比表

| agent | model | 风格 | field_correct | field_complete | lineage | ambig | buildability | clar | inferred | 总分 (5维) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| X | {AGENT_X_MODEL} | lineage-aware | {jx.get('field_correctness','?')} | {jx.get('field_completeness','?')} | **{jx.get('lineage_quality','?')}** | {jx.get('ambiguity_handling','?')} | {jx.get('buildability','?')} | {jx.get('clarification_count','?')} | {jx.get('inferred_field_count','?')} | {total_x} |
| Y | {AGENT_Y_MODEL} | minimal-constraint | {jy.get('field_correctness','?')} | {jy.get('field_completeness','?')} | **{jy.get('lineage_quality','?')}** | {jy.get('ambiguity_handling','?')} | {jy.get('buildability','?')} | {jy.get('clarification_count','?')} | {jy.get('inferred_field_count','?')} | {total_y} |

## Δ 维度细分

| 维度 | X | Y | Δ (X-Y) |
|---|---:|---:|---:|
{chr(10).join(delta_table)}

## Verdict

- **lineage Δ (X-Y)**: {lineage_delta:+d}
- {verdict_lineage}
- **Spec over-fit 判定**: {over_fit_verdict}
- **vs 任务 1 baseline (delivery/list lineage=5)**: X={jx.get('lineage_quality')}, Y={jy.get('lineage_quality')} —
  {"双方均饱和, lineage 跨风格仍稳" if (jx.get('lineage_quality',0) or 0) == 5 and (jy.get('lineage_quality',0) or 0) == 5 else ("仅 X 饱和, 提示 spec 在 lineage 上对 Claude Code 风格友好" if (jx.get('lineage_quality',0) or 0) == 5 else ("仅 Y 饱和, 反直觉" if (jy.get('lineage_quality',0) or 0) == 5 else "双方都掉档, 跨风格未饱和"))}

## Judge 1 句话总评

- **agent_X**: {jx.get('summary', '?')}
- **agent_Y**: {jy.get('summary', '?')}

## Caveat

- **Path B 模拟**: Codex 用 Anthropic Opus 4.7 + minimal prompt 模拟. 真 Codex API 风格 (e.g. system 提示风格, 单次输出长度, tool use 行为) 未覆盖. 等 PM 配 OPENAI_API_KEY 后跑 Path A.
- **判定单点**: 只跑了 1 endpoint × 1 次 implement, 没做 multi-run sampling. lineage Δ 可能受 sampling noise 影响 ±1 分.
- **Judge 同 vendor**: Sonnet 4.6 既评 Sonnet 4.6 也评 Opus 4.7, 同 vendor 自评偏差未控.

## 风险记录

- API failure: {"无" if all(r["impl_usage"].get("returncode") == 0 and r["judge_usage"].get("returncode") == 0 for r in results.values()) else "X impl rc={} judge rc={} | Y impl rc={} judge rc={}".format(results['agent_X']['impl_usage'].get('returncode'), results['agent_X']['judge_usage'].get('returncode'), results['agent_Y']['impl_usage'].get('returncode'), results['agent_Y']['judge_usage'].get('returncode'))}
- judge parse: {"全部 OK" if "_parse_error" not in jx and "_parse_error" not in jy else f"X parse_err={'_parse_error' in jx}, Y parse_err={'_parse_error' in jy}"}
- empty output: X impl chars={results['agent_X']['impl_usage'].get('stdout_chars',0)}, Y impl chars={results['agent_Y']['impl_usage'].get('stdout_chars',0)}

## 成本与时间

| step | duration (s) |
|---|---:|
| agent_X (impl + judge) | {results['agent_X']['duration_s']} |
| agent_Y (impl + judge) | {results['agent_Y']['duration_s']} |
| **合计** | **{round(total_dur, 1)}** |

## 附: 原始产物路径

- `workspace-劳动仲裁/output_codex_cc_compat_2026_04_28/summary.json`
- `workspace-劳动仲裁/output_codex_cc_compat_2026_04_28/impl_agent_X.md`
- `workspace-劳动仲裁/output_codex_cc_compat_2026_04_28/impl_agent_Y.md`
- `workspace-劳动仲裁/output_codex_cc_compat_2026_04_28/judge_agent_X.json`
- `workspace-劳动仲裁/output_codex_cc_compat_2026_04_28/judge_agent_Y.json`
- `workspace-劳动仲裁/output_codex_cc_compat_2026_04_28/user_prompt.txt`
"""

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(report, encoding="utf-8")
    print(f"\n报告已写入: {REPORT_FILE}", flush=True)

    print("\n" + "="*60, flush=True)
    print("FINAL SUMMARY", flush=True)
    print("="*60, flush=True)
    print(f"X total: {total_x}/25, lineage={jx.get('lineage_quality')}", flush=True)
    print(f"Y total: {total_y}/25, lineage={jy.get('lineage_quality')}", flush=True)
    print(f"lineage Δ (X-Y): {lineage_delta:+d}", flush=True)
    print(f"total duration: {round(total_dur, 1)}s", flush=True)


if __name__ == "__main__":
    main()
