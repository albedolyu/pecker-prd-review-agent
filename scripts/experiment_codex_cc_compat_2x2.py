#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
任务 4 follow-up: 2x2 isolate (model x prompt) — 2026-04-28.

任务 4 暴露 over-fit 但 X (Sonnet + lineage-aware) vs Y (Opus + minimal) 同时换两变量,
不知道是 model 还是 prompt 主导.

本脚本补跑 Z / W 两个新工况, 凑齐 2x2:
  - X = Sonnet 4.6 + lineage-aware       (任务 4 已跑, 复用)
  - Y = Opus 4.7   + minimal-constraint  (任务 4 已跑, 复用)
  - Z = Opus 4.7   + lineage-aware       (新跑)
  - W = Sonnet 4.6 + minimal-constraint  (新跑)

复用任务 4 的 user_prompt.txt (保证 spec 输入完全一致, isolate 干净).
"""
from __future__ import annotations

import json
import re
import shutil as _shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\Users\20834\Desktop\agent\prd review")
PRD_FILE = ROOT / "workspace-劳动仲裁" / "prd" / "劳动仲裁需求文档 v5.1.md"

# 复用任务 4 已写好的 user_prompt (含 pecker md + prd section + 4 段落要求)
TASK4_DIR = ROOT / "workspace-劳动仲裁" / "output_codex_cc_compat_2026_04_28"
USER_PROMPT_FILE = TASK4_DIR / "user_prompt.txt"

CLAUDE_EXE = _shutil.which("claude") or r"C:\Users\20834\AppData\Roaming\npm\claude.cmd"

SONNET = "claude-sonnet-4-6"
OPUS = "claude-opus-4-7"
JUDGE_MODEL = SONNET

OUT_DIR = ROOT / "workspace-劳动仲裁" / "output_codex_cc_compat_2x2_2026_04_28"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ENDPOINT_DESC = "送达公告列表"
ENDPOINT_METHOD = "GET"
ENDPOINT_PATH = "/api/v1/labour-arbitration/delivery/list"


# ====== prompt 风格 (同任务 4) ======
LINEAGE_AWARE_SYSTEM = """你是 Claude Code 风格的高级 Python 后端工程师 agent.

你的工作风格:
- 强调可追溯性 (lineage): 每个非 PRD 明示的字段都标 `# inferred: <理由>` 或 `# lineage: <issue.id>`
- PM-friendly: 注释里说人话, 不堆术语
- 严格按 Pecker spec 引用 rule_id
- must severity 必须落地并注释 issue.id; should severity 尽量落地; could severity 标 # TODO
- 模糊字段必须标 `# TODO: 待确认 - <原因>`
"""

MINIMAL_CONSTRAINT_SYSTEM = """You are an experienced Python backend engineer.

Your style:
- Concise, idiomatic code. No verbose comments.
- Trust your judgment on naming, types, and structure.
- Focus on getting it working. Tests should be practical.
- Prioritize clean architecture over excessive documentation.
"""


# 4 工况 (X / Y 已跑, 只跑 Z / W; X / Y 复用任务 4 的产物)
NEW_CONDITIONS = [
    # label, model, system, system_label
    ("agent_Z", OPUS,   LINEAGE_AWARE_SYSTEM,    "lineage-aware"),
    ("agent_W", SONNET, MINIMAL_CONSTRAINT_SYSTEM, "minimal-constraint"),
]


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


def call_claude(model: str, system_prompt: str, user_prompt: str) -> tuple[str, dict]:
    """同任务 4: claude CLI subprocess + stdin 拼 system + user."""
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


def load_prd_section() -> str:
    text = PRD_FILE.read_text(encoding="utf-8")
    start_match = re.search(r"^## 1\.1 名词定义", text, re.MULTILINE)
    end_match = re.search(r"^## 3\. 关联系统交付", text, re.MULTILINE)
    if start_match and end_match:
        return text[start_match.start():end_match.start()]
    return text


def main():
    print("="*60, flush=True)
    print("Codex/CC 兼容性 2x2 isolate (2026-04-28)", flush=True)
    print(f"X (Sonnet + lineage)   = 复用任务 4", flush=True)
    print(f"Y (Opus + minimal)     = 复用任务 4", flush=True)
    print(f"Z (Opus + lineage)     = 新跑", flush=True)
    print(f"W (Sonnet + minimal)   = 新跑", flush=True)
    print(f"Judge = {JUDGE_MODEL}", flush=True)
    print("="*60, flush=True)

    if not USER_PROMPT_FILE.exists():
        print(f"FATAL: user_prompt.txt 缺 {USER_PROMPT_FILE}", flush=True)
        sys.exit(1)

    user_prompt = USER_PROMPT_FILE.read_text(encoding="utf-8")
    prd_section = load_prd_section()
    print(f"\nuser_prompt: {len(user_prompt)} chars", flush=True)
    print(f"prd_section: {len(prd_section)} chars", flush=True)

    # 跑 Z / W
    new_results = {}
    total_dur = 0.0

    for label, model, system, system_label in NEW_CONDITIONS:
        print(f"\n{'='*40}\n[{label}] {model} + {system_label}\n{'='*40}", flush=True)
        impl_text, impl_usage = call_claude(model, system, user_prompt)
        print(f"  impl done. {impl_usage}", flush=True)
        (OUT_DIR / f"impl_{label}.md").write_text(impl_text, encoding="utf-8")

        print(f"  [judge] {JUDGE_MODEL}...", flush=True)
        judge_text, judge_usage = call_claude(
            JUDGE_MODEL,
            "你是中立资深 reviewer.",
            JUDGE_PROMPT.format(
                method=ENDPOINT_METHOD,
                path=ENDPOINT_PATH,
                endpoint_desc=ENDPOINT_DESC,
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
        new_results[label] = {
            "model": model,
            "system_style": system_label,
            "impl_usage": impl_usage,
            "judge_usage": judge_usage,
            "judge": judge,
            "duration_s": round(ep_dur, 1),
        }

    # 复用 X / Y
    task4_summary = json.loads((TASK4_DIR / "summary.json").read_text(encoding="utf-8"))
    x_judge = task4_summary["results"]["agent_X"]["judge"]
    y_judge = task4_summary["results"]["agent_Y"]["judge"]

    all_results = {
        "agent_X": {
            "model": SONNET,
            "system_style": "lineage-aware",
            "judge": x_judge,
            "_source": "复用任务 4",
        },
        "agent_Y": {
            "model": OPUS,
            "system_style": "minimal-constraint",
            "judge": y_judge,
            "_source": "复用任务 4",
        },
        "agent_Z": new_results["agent_Z"],
        "agent_W": new_results["agent_W"],
    }

    summary = {
        "endpoint": {"method": ENDPOINT_METHOD, "path": ENDPOINT_PATH, "desc": ENDPOINT_DESC},
        "judge_model": JUDGE_MODEL,
        "total_new_duration_s": round(total_dur, 1),
        "results": all_results,
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    print("\n" + "="*60, flush=True)
    print("FINAL SUMMARY (2x2)", flush=True)
    print("="*60, flush=True)
    score_keys = ["field_correctness", "field_completeness", "lineage_quality",
                  "ambiguity_handling", "buildability"]
    for label, r in all_results.items():
        j = r["judge"]
        total = sum(j.get(k, 0) for k in score_keys if isinstance(j.get(k), (int, float)))
        print(f"  {label}: {r['model']} + {r['system_style']:20s} "
              f"lineage={j.get('lineage_quality')} "
              f"total={total}/25", flush=True)
    print(f"\n新跑 duration: {round(total_dur, 1)}s", flush=True)
    print(f"产物: {OUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
