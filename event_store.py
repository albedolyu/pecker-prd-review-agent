"""
Pattern 21: Session Event Sourcing + Pattern 22: Compact + Transcript Preservation (CC 模式)

JSONL 追加写入的事件溯源,记录一次评审 session 的全生命周期事件。
路径: {workspace}/output/sessions/{review_id}.jsonl

用法:
    store = EventStore(workspace="/path/to/workspace", review_id="rev_xxx")
    store.append("review_started", {"prd_name": "xxx"})
    store.append("worker_done", {"dim": "structure", "items": 3})
    store.append("checkpoint", {"workers_done": 4})
    events = store.replay()
"""

import json
from datetime import datetime
from pathlib import Path

from logger import get_logger

log = get_logger("event_store")


class EventStore:
    """CC 模式: JSONL 追加写入的事件溯源。"""

    def __init__(self, workspace: str, review_id: str):
        self.path = Path(workspace) / "output" / "sessions" / f"{review_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event_type: str, data: dict = None):
        """追加一条事件到 JSONL 文件。"""
        event = {
            "ts": datetime.now().isoformat(),
            "type": event_type,
            **(data or {}),
        }
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning(f"[event_store] write failed: {e}")

    def replay(self) -> list:
        """回放所有事件,返回 list[dict]。"""
        if not self.path.exists():
            return []
        try:
            text = self.path.read_text(encoding="utf-8").strip()
            return [json.loads(line) for line in text.split("\n") if line]
        except (OSError, json.JSONDecodeError) as e:
            log.warning(f"[event_store] replay failed: {e}")
            return []

    def last_checkpoint(self) -> dict | None:
        """找到最后一个 checkpoint 事件(用于断点续跑)。"""
        for e in reversed(self.replay()):
            if e.get("type") == "checkpoint":
                return e
        return None

    # ------------------------------------------------------------------
    # Pattern 22: Compact + Transcript Preservation (留钩子)
    # ------------------------------------------------------------------

    def save_transcript(self, messages: list, label: str = ""):
        """保存完整对话 transcript 到独立文件(预留接口)。

        当前只 log,不真的写文件。未来可按 label 写到
        {workspace}/output/sessions/{review_id}_{label}.transcript.json
        """
        log.info(
            f"[event_store] save_transcript called: label={label}, "
            f"messages={len(messages)}"
        )

    def compact_with_ref(self, messages: list, summary: str = "") -> list:
        """压缩对话历史,保留引用(预留接口)。

        当前直接返回原 messages,不做真正的压缩。
        未来实现时会用 summary 替换中间轮次,只保留首尾 + 工具调用结果。
        """
        log.info(
            f"[event_store] compact_with_ref called: messages={len(messages)}, "
            f"summary_len={len(summary)}"
        )
        return messages
