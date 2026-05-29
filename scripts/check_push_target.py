"""Guard against pushing sensitive Pecker artifacts to public remotes."""
from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, List


@dataclass(frozen=True)
class PushEvaluation:
    allowed: bool
    blocked_files: list[str]
    reason: str


def evaluate_push(remote_url: str, changed_files: Iterable[str]) -> PushEvaluation:
    if os.environ.get("PECKER_PUSH_GUARD", "1").strip() == "0":
        return PushEvaluation(allowed=True, blocked_files=[], reason="disabled")
    if not _is_public_remote(remote_url):
        return PushEvaluation(allowed=True, blocked_files=[], reason="trusted_remote")
    blocked = [path for path in changed_files if _is_sensitive_path(path)]
    return PushEvaluation(
        allowed=not blocked,
        blocked_files=blocked,
        reason="sensitive_paths" if blocked else "ok",
    )


def _is_public_remote(remote_url: str) -> bool:
    low = (remote_url or "").lower()
    return "github.com" in low or "gitlab.com" in low


def _is_sensitive_path(path: str) -> bool:
    normalized = str(PurePosixPath(str(path).replace("\\", "/"))).lstrip("/")
    basename = normalized.rsplit("/", 1)[-1]
    if _is_private_workspace_path(normalized):
        return True
    patterns = (
        "eval_reports/**/*_pm_revision.md",
        "eval_reports/**/*_zhiqu_handoff.md",
        "eval_reports/*_pm_revision.md",
        "eval_reports/*_zhiqu_handoff.md",
        ".pecker_drafts/**",
        "shared-wiki/**",
    )
    if basename.startswith("finding_outcomes.db"):
        return True
    if basename.startswith(".env") and basename != ".env.example":
        return True
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def _is_private_workspace_path(normalized: str) -> bool:
    root = normalized.split("/", 1)[0].lower()
    if root == "workspace":
        return True
    if root.startswith("workspace-") and root != "workspace-sample":
        return True
    return False


def changed_files_for_push(remote: str = "origin") -> List[str]:
    base_candidates = [f"{remote}/main", "origin/main", "main"]
    for base in base_candidates:
        if _git_ok(["git", "rev-parse", "--verify", base]):
            files = _git_output(["git", "diff", "--name-only", f"{base}...HEAD"])
            if files:
                return [line.strip() for line in files.splitlines() if line.strip()]
    files = _git_output(["git", "diff", "--name-only", "HEAD"])
    return [line.strip() for line in files.splitlines() if line.strip()]


def remote_url(remote: str, provided_url: str = "") -> str:
    if provided_url:
        return provided_url
    return _git_output(["git", "remote", "get-url", remote]).strip()


def _git_ok(cmd: List[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _git_output(cmd: List[str]) -> str:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Block sensitive files when pushing to public remotes.")
    parser.add_argument("--remote", default="origin", help="Git remote name.")
    parser.add_argument("--url", default="", help="Remote URL passed by git pre-push.")
    parser.add_argument("--changed-file", action="append", default=[], help="Changed file; repeat for tests/manual use.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    url = remote_url(args.remote, args.url)
    changed = args.changed_file or changed_files_for_push(args.remote)
    result = evaluate_push(url, changed)
    if result.allowed:
        return 0
    print("[push-guard] FAIL: 公网 remote 命中敏感路径，push 已阻塞")
    print(f"[push-guard] remote={args.remote} url={url}")
    for path in result.blocked_files:
        print(f"[push-guard] - {path}")
    print("[push-guard] 公司 GitLab 可正常推送；如确认无风险，可用 git push --no-verify 人工绕过。")
    print("[push-guard] 也可临时设置 PECKER_PUSH_GUARD=0。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
