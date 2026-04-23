"""RulePerformanceHistoryStore — workspace/output/rule_performance_history.json 的 thin wrapper.

目的: 项目里三处读写这个 JSON 文件(api/routes/review.py 的 Y/N/E 回流 /
cuckoo_scorer.py 的 eval 聚合 / feedback.py 的 timeline 追加), 每处都重复
"计算 path + load dict + mutate + save" 样板。抽出 path 和 I/O 原语,
业务逻辑(EMA 更新 / 聚合 / timeline)仍留在各 caller 避免耦合。

示例:
    store = RulePerformanceHistoryStore(workspace_dir)
    history = store.load()            # 不存在返回 {}
    history.setdefault("V-08", {...})["stats"]["confirmed"] += 1
    store.save(history)

Thread safety: **无锁**。单实例 API 部署下, FastAPI review 请求串行写入风险低
(PECKER_MAX_CONCURRENT 默认 2 + workspace 粒度隔离). 多进程部署需要外部锁。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Union

from io_utils import try_read_json


PathLike = Union[str, Path]


class RulePerformanceHistoryStore:
    """workspace 下的 rule_performance_history.json 读写封装。"""

    FILENAME = "rule_performance_history.json"

    def __init__(self, workspace_dir: PathLike):
        self.workspace_dir = Path(workspace_dir)
        self.path = self.workspace_dir / "output" / self.FILENAME

    def load(self) -> Dict[str, Any]:
        """读已有 history; 文件不存在或坏返回空 dict。"""
        data = try_read_json(self.path, default={})
        # 防御: 被写坏成 list 或 None 时仍返回 {}, 下游 setdefault 才安全
        if not isinstance(data, dict):
            return {}
        return data

    def save(self, data: Dict[str, Any]) -> None:
        """原子写入: tempfile + os.replace, 防写一半 crash 导致 json 坏。"""
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
