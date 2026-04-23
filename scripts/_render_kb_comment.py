"""把 doc_coherence 的 JSON 输出渲染成 PR 评论 markdown.

CI-only helper (文件名前缀 _ 表示内部用), 被 .github/workflows/kb-lint.yml 调用.
用法: python scripts/_render_kb_comment.py coherence.json > kb-comment.md
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict


def render(path: str) -> str:
    lines = ["## 🔍 Knowledge Base Lint", ""]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        lines.append(f"_coherence.json 读取失败: {e}_")
        return "\n".join(lines)

    findings = data.get("findings", [])
    count = len(findings)

    if count == 0:
        lines.append("✅ `doc_coherence` 三项检查全绿 (endpoints / env_vars / file_paths)")
        lines.append("")
        lines.append("_Kakapo wiki scan 见 Actions → `kb-lint-reports` artifact。_")
        return "\n".join(lines)

    lines.append(
        f"`scripts/doc_coherence.py` 发现 **{count}** 条 finding（warn-only, 不阻塞 merge）:"
    )
    lines.append("")

    by_check: dict[str, list] = defaultdict(list)
    for f in findings:
        by_check[f.get("check", "unknown")].append(f)

    # 按固定顺序输出,有数据才展示
    for check in ("endpoints", "env_vars", "file_paths"):
        items = by_check.get(check, [])
        if not items:
            continue
        lines.append(f"### `{check}` ({len(items)})")
        lines.append("")
        for it in items:
            where = f" — `{it['where']}`" if it.get("where") else ""
            # 去掉 message 末尾可能的句号,保持 bullet 风格一致
            msg = (it.get("message") or "").rstrip("。.")
            lines.append(f"- ⚠️ {msg}{where}")
        lines.append("")

    lines.append("---")
    lines.append(
        "_Kakapo wiki scan 结果见 Actions → `kb-lint-reports` artifact。"
        "本评论由 kb-lint workflow 自动维护,PR 每次更新都会刷新。_"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "coherence.json"
    # Windows-safe stdout write
    out = render(path)
    try:
        print(out)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")
