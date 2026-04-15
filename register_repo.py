"""CLI: 把一个下游 AI Coding 本地仓库注册到啄木鸟反馈闭环。

用法:
    python register_repo.py /path/to/ai-coding-repo \\
        --workspace workspace-对外投资 \\
        --scope 对外投资 \\
        --prd 投资.md

注册后:
- run_session.py 启动时会自检该仓库 HEAD 是否前进,弹 [y/N/s] 提示
- feedback.py --scan-registered-repos 会定时扫描并采集信号
"""
from __future__ import annotations

import argparse
import os
import sys

from registry import (
    register_repo as _register,
    load_registry,
    _normalize_path,
)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="注册下游 AI Coding 仓库到啄木鸟信鸽反馈闭环",
    )
    parser.add_argument("repo_path", help="下游 AI Coding 仓库的本地路径(绝对或相对皆可,会自动规范化)")
    parser.add_argument("--workspace", required=True,
                        help="啄木鸟 workspace 名或路径,如 workspace-对外投资")
    parser.add_argument("--scope", required=True,
                        help="信号过滤关键词,如 对外投资")
    parser.add_argument("--prd", required=True,
                        help="关联 PRD 文件名,如 投资.md")
    parser.add_argument("--registry-path", default=".pecker_registry.json",
                        help="注册表文件路径(默认项目根下 .pecker_registry.json)")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.repo_path):
        print(f"[错误] 仓库路径不存在或不是目录: {args.repo_path}", file=sys.stderr)
        return 1

    if not os.path.isdir(os.path.join(args.repo_path, ".git")):
        print(f"[警告] {args.repo_path} 下没有 .git,可能不是一个 git 仓库(仍然注册)")

    _register(
        args.registry_path,
        args.repo_path,
        workspace=args.workspace,
        scope=args.scope,
        prd=args.prd,
    )

    reg = load_registry(args.registry_path)
    normalized = _normalize_path(args.repo_path)
    print(f"[成功] 已注册到 {args.registry_path}")
    print(f"  repo_path (规范化): {normalized}")
    print(f"  workspace:          {args.workspace}")
    print(f"  scope:              {args.scope}")
    print(f"  prd:                {args.prd}")
    print(f"  当前共 {len(reg['repos'])} 个注册仓库")
    return 0


if __name__ == "__main__":
    sys.exit(main())
