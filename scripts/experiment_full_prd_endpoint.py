#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
全 PRD endpoint lineage_quality 饱和率验证 (2026-04-28).

baseline (2026-04-27) 已验证 hearing/list 单 endpoint 上 Pecker 工况 lineage=5/5.
本实验验证 PRD §2.5 所有 4 个 endpoint 是否都饱和:
  - GET /api/v1/labour-arbitration/delivery/list
  - GET /api/v1/labour-arbitration/hearing/list (复跑)
  - GET /api/v1/labour-arbitration/filters
  - GET /api/v1/labour-arbitration/detail

每个 endpoint:
  - Opus 4.7 implement (用 R2 review_items 按 endpoint 关键词过滤)
  - Sonnet 4.6 judge 5 维 + 2 计数

不跑 single-shot / raw 对照 (那是 baseline 的范畴, 本实验聚焦 lineage 跨 endpoint 饱和率).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\Users\20834\Desktop\agent\prd review")
PRD_FILE = ROOT / "workspace-劳动仲裁" / "prd" / "劳动仲裁需求文档 v5.1.md"
PECKER_FILE = ROOT / "workspace-劳动仲裁" / "output" / "review_items_R2_2026_04_28.json"

import shutil as _shutil
CLAUDE_EXE = _shutil.which("claude") or r"C:\Users\20834\AppData\Roaming\npm\claude.cmd"
OPUS_MODEL = "claude-opus-4-7"
SONNET_MODEL = "claude-sonnet-4-6"

OUT_DIR = ROOT / "workspace-劳动仲裁" / "output_full_prd_2026_04_28"
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_FILE = ROOT / "docs" / "full_prd_endpoint_2026_04_28.md"


# 4 个 endpoint 定义, kw 用于按 endpoint 过滤 review_items (中文+英文 keyword)
ENDPOINTS = [
    {
        "name": "delivery/list",
        "method": "GET",
        "path": "/api/v1/labour-arbitration/delivery/list",
        "desc": "送达公告列表",
        "kw": ["delivery", "送达公告", "送达列表", "送达", "publish_date"],
    },
    {
        "name": "hearing/list",
        "method": "GET",
        "path": "/api/v1/labour-arbitration/hearing/list",
        "desc": "开庭公告列表 (baseline 已测, 本次复跑验证 sampling)",
        "kw": ["hearing", "开庭公告", "开庭列表", "开庭", "open_time", "arbitrator", "arbitration_site"],
    },
    {
        "name": "filters",
        "method": "GET",
        "path": "/api/v1/labour-arbitration/filters",
        "desc": "筛选条件 (列表型, 树形)",
        "kw": ["filters", "filter_type", "arbitration_org", "case_reason", "筛选"],
    },
    {
        "name": "detail",
        "method": "GET",
        "path": "/api/v1/labour-arbitration/detail",
        "desc": "公告详情 (table_id+type 两种类型)",
        "kw": ["detail", "详情", "table_id", "content", "recorder"],
    },
]


def load_prd_section() -> str:
    """提取 §2.5 接口规范 (4 endpoints) + §1 名词定义/字段映射 + §2.3 列表语义."""
    text = PRD_FILE.read_text(encoding="utf-8")
    # 取整段 §1 名词定义 - §3 关联系统交付 之间, 含 §2.5 接口规范
    start_match = re.search(r"^## 1\.1 名词定义", text, re.MULTILINE)
    end_match = re.search(r"^## 3\. 关联系统交付", text, re.MULTILINE)
    if start_match and end_match:
        section = text[start_match.start():end_match.start()]
    else:
        section = text
    return section


def load_pecker_issues() -> list[dict[str, Any]]:
    return json.loads(PECKER_FILE.read_text(encoding="utf-8"))


def filter_for_endpoint(issues: list[dict[str, Any]], kws: list[str]) -> list[dict[str, Any]]:
    rel = []
    for it in issues:
        text = " ".join([
            str(it.get("issue", "")),
            str(it.get("location", "")),
            str(it.get("evidence_content", "")),
        ])
        # 同时把所有 中文 key 字段也扫一下 (R2 中有乱码 key 含 suggestion 内容)
        for k, v in it.items():
            if isinstance(v, str):
                text += " " + v
        if any(kw.lower() in text.lower() for kw in kws):
            rel.append(it)
    return rel


def serialize_pecker_for_implement(issues: list[dict[str, Any]], endpoint_name: str) -> str:
    lines = [f"# Pecker review 输出 (劳动仲裁 {endpoint_name} 相关)"]
    lines.append(f"\n共 {len(issues)} 条 issue, 按 severity 分组.\n")
    by_sev = {"must": [], "should": [], "could": []}
    for it in issues:
        sev = it.get("severity", "could")
        by_sev.setdefault(sev, []).append(it)
    for sev in ["must", "should", "could"]:
        if not by_sev.get(sev):
            continue
        lines.append(f"\n## severity = {sev} ({len(by_sev[sev])} 条)\n")
        for it in by_sev[sev]:
            lines.append(f"\n### [{it.get('id')}] rule_id={it.get('rule_id')} dimension={it.get('dimension')}")
            lines.append(f"- **location**: {it.get('location', '')}")
            lines.append(f"- **issue**: {it.get('issue', '')}")
            # R2 中 suggestion 在乱码 key 里, 兜底找 'suggestion' 字段或扫所有 str 字段拼接
            sug = it.get("suggestion", "")
            if not sug:
                # 把所有非常用 key 的 str 字段当 suggestion 来源 (R2 乱码 fallback)
                for k, v in it.items():
                    if k in ("rule_id", "location", "issue", "severity", "evidence_type", "evidence_content",
                            "evidence_chain", "id", "confidence_score", "dimension", "is_cross_section",
                            "status", "verification_status", "verification_reason", "verification_details",
                            "advisor_note", "gate_log"):
                        continue
                    if isinstance(v, str) and len(v) > 30:
                        sug += v + " | "
            lines.append(f"- **suggestion**: {sug[:500]}")
            ev_type = it.get("evidence_type", "")
            ev_content = it.get("evidence_content", "")
            if ev_content:
                ev_str = str(ev_content)[:300]
                lines.append(f"- **evidence ({ev_type})**: {ev_str}")
            vs = it.get("verification_status", "")
            if vs:
                lines.append(f"- **verification_status**: {vs}")
    return "\n".join(lines)


def call_claude(model: str, prompt: str) -> tuple[str, dict]:
    t0 = time.time()
    try:
        result = subprocess.run(
            [CLAUDE_EXE, "-p", "--model", model],
            input=prompt,
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


# implement prompt: 跟 baseline 工况 A 完全同款, 只换 endpoint 描述
IMPL_PROMPT = """你是一位资深 Python 后端工程师 (FastAPI + Pydantic + PostgreSQL).
你的任务: 严格根据给定的输入 spec, 实现 {method} {path} endpoint ({desc}).

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
- 涉及"模糊"或"我不确定"的字段, 必须明确标 `# TODO: 待确认 - <原因>` 或在注释里说明默认值.
- 凡是从 spec 自己推断 (PRD 没明示) 的字段, 必须在注释加 `# inferred: <理由>`.
- 代码风格: 简洁、可运行、无 import 错误.

**输入 spec**: 下面是 Pecker (PRD review agent) 的结构化输出. 每条 issue 带 severity (must/should/could) / rule_id / location / suggestion. 你必须:

1. **must severity issue**: 严格按 suggestion 落地, 必须在代码注释引用 issue.id (例: `# lineage: R-007 [RC-008]`)
2. **should severity issue**: 尽量按 suggestion 落地, 在注释提一下
3. **could severity issue**: 标 `# TODO`

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
- **inferred_field_count**: PRD 没明示但实现自加的字段数 (例: PRD 没说 `status` 字段但实现加了)

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
    print("Full PRD endpoint lineage_quality 饱和率验证", flush=True)
    print(f"PRD: {PRD_FILE}", flush=True)
    print(f"Pecker (R2): {PECKER_FILE}", flush=True)
    print(f"Endpoints: {len(ENDPOINTS)}", flush=True)
    print("="*60, flush=True)

    prd_section = load_prd_section()
    print(f"\nPRD section: {len(prd_section)} chars", flush=True)

    issues_all = load_pecker_issues()
    print(f"R2 issues: {len(issues_all)} total", flush=True)

    results = []
    total_dur = 0.0

    for ep in ENDPOINTS:
        name = ep["name"]
        print(f"\n{'='*40}\n[{name}] start\n{'='*40}", flush=True)
        rel = filter_for_endpoint(issues_all, ep["kw"])
        print(f"  filtered issues: {len(rel)}", flush=True)
        sev_dist = {s: sum(1 for i in rel if i.get("severity") == s) for s in ("must", "should", "could")}
        print(f"  severity: {sev_dist}", flush=True)

        pecker_md = serialize_pecker_for_implement(rel, name)
        slug = name.replace("/", "_")
        (OUT_DIR / f"pecker_{slug}.md").write_text(pecker_md, encoding="utf-8")

        # implement
        print(f"  [implement] {OPUS_MODEL}...", flush=True)
        impl_text, impl_usage = call_claude(
            OPUS_MODEL,
            IMPL_PROMPT.format(
                method=ep["method"],
                path=ep["path"],
                desc=ep["desc"],
                pecker_md=pecker_md,
                prd_section=prd_section,
            ),
        )
        print(f"    done. {impl_usage}, {len(impl_text)} chars", flush=True)
        (OUT_DIR / f"impl_{slug}.md").write_text(impl_text, encoding="utf-8")

        # judge
        print(f"  [judge] {SONNET_MODEL}...", flush=True)
        judge_text, judge_usage = call_claude(
            SONNET_MODEL,
            JUDGE_PROMPT.format(
                method=ep["method"],
                path=ep["path"],
                endpoint_desc=ep["desc"],
                prd_section=prd_section,
                implementation=impl_text,
            ),
        )
        judge = parse_judge_json(judge_text)
        print(f"    done. parse_ok={'_parse_error' not in judge}, scores={judge.get('field_correctness')}/{judge.get('field_completeness')}/{judge.get('lineage_quality')}/{judge.get('ambiguity_handling')}/{judge.get('buildability')}", flush=True)
        (OUT_DIR / f"judge_{slug}.json").write_text(
            json.dumps(judge, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        ep_dur = impl_usage.get("duration_s", 0) + judge_usage.get("duration_s", 0)
        total_dur += ep_dur

        results.append({
            "endpoint": ep,
            "filtered_issues": len(rel),
            "severity_dist": sev_dist,
            "filtered_ids": [(i.get("id"), i.get("severity"), i.get("rule_id")) for i in rel],
            "impl_usage": impl_usage,
            "judge_usage": judge_usage,
            "judge": judge,
            "ep_duration_s": round(ep_dur, 1),
        })

    # 汇总 JSON
    summary = {
        "model_implement": OPUS_MODEL,
        "model_judge": SONNET_MODEL,
        "spec_source": str(PECKER_FILE),
        "total_duration_s": round(total_dur, 1),
        "results": results,
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    # 报告
    print("\n[report] Generating...", flush=True)
    rows = []
    rows.append("| endpoint | issues | sev (m/s/c) | field_correct | field_complete | lineage | ambig | build | clar | inferred | sum |")
    rows.append("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    saturated = 0
    not_saturated = []
    for r in results:
        ep = r["endpoint"]
        j = r["judge"]
        sd = r["severity_dist"]
        sevtag = f"{sd['must']}/{sd['should']}/{sd['could']}"
        scores5 = [j.get(k, 0) if isinstance(j.get(k), (int, float)) else 0
                   for k in ("field_correctness", "field_completeness", "lineage_quality",
                             "ambiguity_handling", "buildability")]
        total5 = sum(scores5)
        rows.append(f"| {ep['name']} | {r['filtered_issues']} | {sevtag} | "
                    f"{j.get('field_correctness','?')} | {j.get('field_completeness','?')} | "
                    f"**{j.get('lineage_quality','?')}** | {j.get('ambiguity_handling','?')} | "
                    f"{j.get('buildability','?')} | {j.get('clarification_count','?')} | "
                    f"{j.get('inferred_field_count','?')} | {total5} |")
        if j.get("lineage_quality") == 5:
            saturated += 1
        else:
            not_saturated.append((ep['name'], j.get('lineage_quality'), j.get('summary', '')))

    summaries_md = "\n".join(f"- **{r['endpoint']['name']}**: {r['judge'].get('summary', '?')}"
                             for r in results)
    notsat_md = "\n".join(f"- **{n}**: lineage={l}, summary={s}" for n, l, s in not_saturated) if not_saturated else "(全部饱和)"

    table_md = "\n".join(rows)

    report = f"""# Pecker 全 PRD endpoint lineage_quality 饱和率验证 (2026-04-28)

## 任务

- PRD: 劳动仲裁需求文档 v5.1 (`{PRD_FILE.name}`)
- spec 来源: R2 review_items (任务 2 干净 setup, 0 幻觉 ID, 18 issues)
  - file: `workspace-劳动仲裁/output/review_items_R2_2026_04_28.json`
- {len(ENDPOINTS)} endpoint × Opus 4.7 implement × Sonnet 4.6 judge
- 不跑 single-shot/raw 对照 (baseline 已覆盖, 本实验只关心 lineage 跨 endpoint 饱和率)

## Endpoint 清单

{chr(10).join(f"- {ep['method']} `{ep['path']}` — {ep['desc']}" for ep in ENDPOINTS)}

## Endpoint × judge 评分表

{table_md}

## lineage_quality 饱和率分析

- **饱和率**: {saturated}/{len(ENDPOINTS)} endpoint lineage=5
- **未饱和**:
{notsat_md}

## Judge 1 句话总评

{summaries_md}

## vs 1 endpoint baseline (工况 A 5/5, hearing/list)

baseline (2026-04-27) 在 hearing/list 上 lineage=5, total=25/25.

| 比较 | hearing/list (baseline) | hearing/list (本次) |
|---|---:|---:|
| field_correctness | (见 baseline) | {results[1]['judge'].get('field_correctness', '?')} |
| lineage_quality | 5 | **{results[1]['judge'].get('lineage_quality', '?')}** |

## Verdict

(见末尾 `## 6. 结论` 段, 由实测填.)

## 风险记录

- **R2 中文 key 乱码 (Windows 默认编码)**: 大部分中文 key 是 mojibake, 影响 `suggestion` 字段提取 — 已用 fallback 扫所有 str 字段聚合作为 suggestion.
- **R2 全 endpoint hit 重叠**: R-002 / R-006 / R-011 / R-023 等 must issue 命中 ≥3 个 endpoint (因为是 PRD 全局规则), 不只是单 endpoint 私有 issue.

## 5. 成本与时间

| endpoint | impl duration (s) | judge duration (s) | ep total (s) |
|---|---:|---:|---:|
{chr(10).join(f"| {r['endpoint']['name']} | {r['impl_usage'].get('duration_s','?')} | {r['judge_usage'].get('duration_s','?')} | {r['ep_duration_s']} |" for r in results)}
| **合计** | | | **{round(total_dur, 1)}** |

## 6. 结论

(由 lineage_quality 饱和率 + judge summary 综合判定 — 详见汇总表头部数字.)

## 附: 原始产物路径

- summary.json: `workspace-劳动仲裁/output_full_prd_2026_04_28/summary.json`
{chr(10).join(f"- impl_{r['endpoint']['name'].replace('/','_')}.md / judge_{r['endpoint']['name'].replace('/','_')}.json / pecker_{r['endpoint']['name'].replace('/','_')}.md" for r in results)}
"""

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(report, encoding="utf-8")
    print(f"\n报告已写入: {REPORT_FILE}", flush=True)

    print("\n" + "="*60, flush=True)
    print("FINAL SUMMARY", flush=True)
    print("="*60, flush=True)
    print(table_md, flush=True)
    print(f"\nsaturated lineage=5: {saturated}/{len(ENDPOINTS)}", flush=True)
    print(f"total duration: {round(total_dur, 1)}s", flush=True)


if __name__ == "__main__":
    main()
