"""RulePerformanceHistoryStore — workspace/output/rule_performance_history.json 的 thin wrapper.

目的: 项目里三处读写这个 JSON 文件(api/routes/review.py 的 Y/N/E 回流 /
cuckoo_scorer.py 的 eval 聚合 / feedback.py 的 timeline 追加), 每处都重复
"计算 path + load dict + mutate + save" 样板。抽出 path 和 I/O 原语,
业务逻辑(EMA 更新 / 聚合 / timeline)仍留在各 caller 避免耦合。

示例:
    store = RulePerformanceHistoryStore(workspace_dir)
    history = store.load()            # 不存在返回 {} (已自动 migrate)
    history.setdefault("V-08", {...})["stats"]["confirmed"] += 1
    store.save(history)               # 自动写入 __meta__ schema_version

Thread safety: **无锁**。单实例 API 部署下, FastAPI review 请求串行写入风险低
(PECKER_MAX_CONCURRENT 默认 2 + workspace 粒度隔离). 多进程部署需要外部锁。

Schema versioning (2026-04-23 #3 优化):
- 顶层 "__meta__" key 存 {"schema_version": int, "updated_at": ...}
- v0 = 无 __meta__ 的旧格式 (现有生产数据). load() 自动识别并 migrate 到当前版本
- 新增 schema 字段时: 加 _migrate_vN_to_vM 函数 + 更新 _CURRENT_SCHEMA_VERSION
- 下游 caller 继续按 rule_id 访问, __meta__ 不干扰 (rule_id 只会是 V-XX/RC-XX)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Union

from io_utils import try_read_json


PathLike = Union[str, Path]

_CURRENT_SCHEMA_VERSION = 1
_META_KEY = "__meta__"


def _detect_schema_version(data: Dict[str, Any]) -> int:
    """识别 data 的 schema 版本. 无 __meta__ = v0 (旧格式, 现生产数据)。"""
    meta = data.get(_META_KEY)
    if not isinstance(meta, dict):
        return 0
    v = meta.get("schema_version")
    if isinstance(v, int) and v >= 0:
        return v
    return 0


def _migrate_v0_to_v1(data: Dict[str, Any]) -> Dict[str, Any]:
    """v0 (旧 flat 格式) → v1 (加 __meta__). 内容字段不变,只加元信息。"""
    # 除 __meta__ 外的所有 key 视为 rule_id → 保持原样
    return data  # no-op on content, save() 会负责写 __meta__


def _migrate(data: Dict[str, Any], from_version: int) -> Dict[str, Any]:
    """从 from_version 逐步 migrate 到 _CURRENT_SCHEMA_VERSION.

    未来加 v2 时:
        if from_version <= 1:
            data = _migrate_v1_to_v2(data)
    """
    if from_version == 0:
        data = _migrate_v0_to_v1(data)
        from_version = 1
    # ... future: if from_version == 1: data = _migrate_v1_to_v2(data)
    return data


class RulePerformanceHistoryStore:
    """workspace 下的 rule_performance_history.json 读写封装。"""

    FILENAME = "rule_performance_history.json"
    SCHEMA_VERSION = _CURRENT_SCHEMA_VERSION

    def __init__(self, workspace_dir: PathLike):
        self.workspace_dir = Path(workspace_dir)
        self.path = self.workspace_dir / "output" / self.FILENAME

    def load(self) -> Dict[str, Any]:
        """读已有 history; 文件不存在或坏返回空 dict. 自动 migrate 旧 schema。"""
        data = try_read_json(self.path, default={})
        if not isinstance(data, dict):
            return {}
        # 识别版本并 migrate 到当前版本(就地, 不写回 — 下次 save 才落盘)
        v = _detect_schema_version(data)
        if v < _CURRENT_SCHEMA_VERSION:
            data = _migrate(data, v)
        return data

    def save(self, data: Dict[str, Any]) -> None:
        """原子写入: tempfile + os.replace, 防写一半 crash 导致 json 坏.

        自动写入/更新 __meta__ schema_version + updated_at 字段。
        """
        # 注入/更新 __meta__ — 保留现有其他 meta 字段(向前兼容新字段)
        meta = data.get(_META_KEY, {}) if isinstance(data.get(_META_KEY), dict) else {}
        meta["schema_version"] = _CURRENT_SCHEMA_VERSION
        meta["updated_at"] = int(time.time())
        data[_META_KEY] = meta

        import tempfile
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix=".rule_perf_", suffix=".tmp",
            dir=str(self.path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            raise

    def iter_rules(self, data: Dict[str, Any]):
        """遍历 rule 条目时跳过 __meta__. caller 用 iter_rules(history) 代替 history.items()."""
        for key, value in data.items():
            if key == _META_KEY:
                continue
            yield key, value
