"""Pecker信鸽反馈闭环 — 下游 AI Coding 仓库注册表。

只存最小字段: repo_path / workspace / scope / prd / last_scanned_commit / last_scan_at。
不存 report 路径(易过期,scan 时 glob 取最新 mtime)。

并发控制: os.replace 原子写,单用户本地工具够用。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict


class RegistryEntry(TypedDict, total=False):
    repo_path: str
    workspace: str
    scope: str
    prd: str
    last_scanned_commit: str
    last_scan_at: str
    registered_at: str


def _normalize_path(p: str) -> str:
    """规范化仓库路径: 绝对路径 + Windows 下小写驱动器。

    防 `C:\\foo` vs `c:\\foo` 产生重复注册条目。
    """
    abs_p = str(Path(p).resolve())
    if sys.platform.startswith("win") and len(abs_p) >= 2 and abs_p[1] == ":":
        abs_p = abs_p[0].lower() + abs_p[1:]
    return abs_p


def load_registry(path: str) -> Dict[str, Any]:
    """读 .pecker_registry.json,缺失或损坏都返回空壳。"""
    if not os.path.isfile(path):
        return {"version": "1", "repos": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "repos" not in data:
            return {"version": "1", "repos": []}
        return data
    except (json.JSONDecodeError, OSError):
        return {"version": "1", "repos": []}


def save_registry(path: str, reg: Dict[str, Any]) -> None:
    """原子写 registry: 先写 .tmp 再 os.replace (跨平台安全,防止写一半崩溃导致 JSON 损坏)"""
    parent_dir = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(parent_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".pecker_reg_",
        suffix=".tmp",
        dir=parent_dir,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def register_repo(
    registry_path: str,
    repo_path: str,
    *,
    workspace: str,
    scope: str,
    prd: str,
) -> None:
    """注册/更新一个下游仓库条目(按 normalized path 去重,后写覆盖前写)。"""
    reg = load_registry(registry_path)
    normalized = _normalize_path(repo_path)
    entry: RegistryEntry = {
        "repo_path": normalized,
        "workspace": workspace,
        "scope": scope,
        "prd": prd,
        "last_scanned_commit": "",  # 空串表示"从未扫过"
        "last_scan_at": "",
        "registered_at": datetime.now().isoformat(timespec="seconds"),
    }
    # 去重: 去掉同路径的老条目
    reg["repos"] = [r for r in reg["repos"] if r.get("repo_path") != normalized]
    reg["repos"].append(entry)
    save_registry(registry_path, reg)


def _get_head_sha(repo_path: str) -> Optional[str]:
    """跑 `git rev-parse HEAD`,空仓/损坏仓/不存在都返回 None。"""
    if not os.path.isdir(repo_path):
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        sha = result.stdout.strip()
        return sha if sha and len(sha) >= 7 else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def list_pending(reg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """返回所有 HEAD != last_scanned_commit 的仓库(不可达的静默跳过)。

    每个返回条目在原 entry 基础上加一个 `current_sha` 字段。
    """
    pending = []
    for entry in reg.get("repos", []):
        repo_path = entry.get("repo_path", "")
        current = _get_head_sha(repo_path)
        if current is None:
            continue  # 仓库不可达,静默跳过
        if current != entry.get("last_scanned_commit", ""):
            pending.append({
                **entry,
                "current_sha": current,
            })
    return pending


def mark_scanned(registry_path: str, repo_path: str, sha: str) -> None:
    """更新某个仓库的 last_scanned_commit / last_scan_at。"""
    reg = load_registry(registry_path)
    normalized = _normalize_path(repo_path)
    now = datetime.now().isoformat(timespec="seconds")
    for entry in reg.get("repos", []):
        if entry.get("repo_path") == normalized:
            entry["last_scanned_commit"] = sha
            entry["last_scan_at"] = now
            break
    save_registry(registry_path, reg)
