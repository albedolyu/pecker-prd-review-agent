"""小型 I/O 工具函数 — 消除 `try: open+json.load except (OSError, JSONDecodeError): fallback` 的重复 pattern。

只处理项目里 20+ 处重复的 "读 JSON 文件, 失败返回 default" 模式. 不是通用 util 库
(不引入功能), 仅 dedup 现有代码. legacy / scripts / 一次性工具里的同模式不强求
全部替换, 先在 api/ hot path + 新模块用起来。

设计约束:
- 不隐藏错误类型: 只吞 OSError / JSONDecodeError, 其他异常(KeyboardInterrupt / MemoryError)照抛
- default 可以是任意类型(dict / list / None / ...), 不做类型检查
- 不做原子写(那是 write 侧的事, 不属于 read util)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union


PathLike = Union[str, Path]


def try_read_json(path: PathLike, default: Any = None) -> Any:
    """读 JSON 文件, 失败(文件不存在 / IO 错 / JSON 坏)返回 default。

    Examples:
        >>> history = try_read_json("output/rule_perf.json", default={})
        >>> acl = try_read_json(ws / ".pecker_acl.json", default=None)
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default
