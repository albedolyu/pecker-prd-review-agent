"""把不健康的 session 归档到 sessions/_archive/,降低 STATUS 报告的历史噪音。

归档条件(任一即归档):
- 含 "Worker 超时(NNNs)" 错误(timeout 修复前的擦边切)
- 含 "hit your limit" / "usage limit" / quota_exhausted (CLI 配额耗尽,ops 噪声)
- 含 "cannot import name" (老 base.py 漏导出 GOSHAWK_TIMEOUT 之类的,代码已修)
- 含 'api_error_status":401' / "authentication_error" (CLI OAuth token 失效)

不算"不健康":
- worker 跑出 items=0 但 error=null(可能本来就该静默)
- final_reviewer_started 后没 done(可能 Phase 3 用户主动中断)

`scripts/generate_status.py` 的 glob `workspace-*/output/sessions/*.jsonl` 不匹配
`_archive/` 子目录,归档后 STATUS 自动跳过这些 session,反映"修复后"的现状。

用法:
    python scripts/archive_unhealthy_sessions.py --workspace workspace-对外投资 --dry-run
    python scripts/archive_unhealthy_sessions.py --workspace workspace-对外投资 --confirm
    python scripts/archive_unhealthy_sessions.py --all --dry-run    # 扫所有 workspace
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 归档触发指纹(顺序是输出展示用,不是优先级)
PATTERNS = {
    "timeout":      re.compile(r"Worker 超时\(\d+s\)"),
    "quota":        re.compile(r"hit your limit|usage limit|QuotaExhausted", re.I),
    "import_error": re.compile(r"cannot import name"),
    "auth_401":     re.compile(r'api_error_status":401|authentication_error', re.I),
}


def classify(jsonl_path: Path) -> list:
    """返回该 session 命中的归档原因列表(可能多个)。空 = healthy 不归档。"""
    try:
        text = jsonl_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ["unreadable"]
    return [name for name, pat in PATTERNS.items() if pat.search(text)]


def find_targets(workspace: Path) -> dict:
    """扫一个 workspace,返回 {session_path: [reasons]}。"""
    sessions_dir = workspace / "output" / "sessions"
    if not sessions_dir.is_dir():
        return {}
    out = {}
    for f in sessions_dir.glob("*.jsonl"):  # 不递归,_archive/ 自动跳过
        reasons = classify(f)
        if reasons:
            out[f] = reasons
    return out


def archive(workspace: Path, targets: dict, dry_run: bool) -> int:
    """实际移动文件,返回操作计数。"""
    archive_dir = workspace / "output" / "sessions" / "_archive"
    if not dry_run:
        archive_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for src, reasons in sorted(targets.items()):
        reason_str = ",".join(reasons)
        if dry_run:
            print(f"[dry] {src.name}  ←  {reason_str}")
        else:
            shutil.move(str(src), str(archive_dir / src.name))
            print(f"[mv]  {src.name}  ←  {reason_str}")
        moved += 1
    return moved


def main():
    parser = argparse.ArgumentParser(description="归档不健康 session 降噪 STATUS")
    parser.add_argument("--workspace", help="单个 workspace 路径(相对项目根)")
    parser.add_argument("--all", action="store_true", help="扫所有 workspace-*/")
    parser.add_argument("--dry-run", action="store_true", help="只列不移")
    parser.add_argument("--confirm", action="store_true", help="实际移动")
    args = parser.parse_args()

    if args.workspace and args.all:
        print("[error] --workspace 和 --all 互斥")
        sys.exit(2)
    if not (args.dry_run or args.confirm):
        print("[error] 必须指定 --dry-run 或 --confirm")
        sys.exit(2)

    if args.all:
        workspaces = [p for p in ROOT.glob("workspace-*") if p.is_dir()]
    elif args.workspace:
        workspaces = [ROOT / args.workspace]
    else:
        print("[error] 必须指定 --workspace 或 --all")
        sys.exit(2)

    total_moved = 0
    for ws in workspaces:
        if not ws.is_dir():
            print(f"[skip] {ws} 不存在")
            continue
        targets = find_targets(ws)
        if not targets:
            print(f"[ok]  {ws.name}: 0 个不健康 session")
            continue
        print(f"\n=== {ws.name}: {len(targets)} 个待归档 ===")
        total_moved += archive(ws, targets, dry_run=args.dry_run)

    suffix = "(dry-run,未实际移动)" if args.dry_run else ""
    print(f"\n[done] 共 {total_moved} 个 session 归档 {suffix}")


if __name__ == "__main__":
    main()
