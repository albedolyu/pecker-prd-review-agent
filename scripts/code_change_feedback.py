"""Build weak review feedback signals from downstream source-code diffs."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.sanitize import redact_text
from review.code_change_feedback import (
    build_code_change_feedback,
    record_code_change_feedback_scores,
)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Infer implementation adoption signals from review findings and git diff."
    )
    parser.add_argument("--findings-json", required=True, help="Review result JSON or items JSON.")
    parser.add_argument("--diff-file", default="", help="Unified diff file. If omitted, run git diff.")
    parser.add_argument("--repo", default=".", help="Repository directory for git diff fallback.")
    parser.add_argument("--base", default="", help="Base ref for git diff fallback.")
    parser.add_argument("--head", default="HEAD", help="Head ref for git diff fallback.")
    parser.add_argument("--output-json", default="", help="Output JSON path. Defaults to stdout.")
    parser.add_argument("--record-langfuse", action="store_true", help="Write aggregate scores to Langfuse.")
    parser.add_argument("--session-id", default="", help="Langfuse session id for score recording.")
    parser.add_argument("--trace-id", default="", help="Langfuse trace id for score recording.")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    findings_payload = _read_json(Path(args.findings_json))
    findings = _extract_findings(findings_payload)
    diff_text = (
        Path(args.diff_file).read_text(encoding="utf-8")
        if args.diff_file
        else _git_diff(Path(args.repo), base=args.base, head=args.head)
    )
    result = build_code_change_feedback(findings, diff_text)
    if args.record_langfuse:
        result["langfuse_scores"] = record_code_change_feedback_scores(
            result,
            trace_id=args.trace_id,
            session_id=args.session_id or "code-change-feedback",
        )
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output_json:
        out = Path(args.output_json).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


def _read_json(path: Path) -> Any:
    return json.loads(path.expanduser().resolve().read_text(encoding="utf-8-sig"))


def _extract_findings(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("items", "findings", "merged_items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    review_result = payload.get("review_result")
    if isinstance(review_result, Mapping):
        return _extract_findings(review_result)
    return []


def _git_diff(repo: Path, *, base: str, head: str) -> str:
    repo_path = repo.expanduser().resolve()
    args = ["git", "-C", str(repo_path), "diff"]
    if base:
        args.append(f"{base}..{head or 'HEAD'}")
    completed = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(redact_text(completed.stderr or completed.stdout or "git diff failed"))
    return completed.stdout


if __name__ == "__main__":
    raise SystemExit(main())
