"""File-backed LangGraph checkpoint helpers for review jobs.

The fallback LangGraph package installed here only includes the in-memory saver.
This wrapper keeps the same saver semantics while writing its serialized state to
an ignored local runtime file, so a restarted API process can inspect the latest
graph state for the same thread id.
"""
from __future__ import annotations

import pickle
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from langgraph.checkpoint.memory import InMemorySaver


def _plain_mapping(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_mapping(item) for key, item in value.items()}
    return value


class FileLangGraphCheckpointSaver(InMemorySaver):
    """Persist LangGraph's in-memory checkpoint store to a local pickle file."""

    def __init__(self, checkpoint_path: str | Path):
        super().__init__()
        self.checkpoint_path = Path(checkpoint_path)
        self._file_lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self.checkpoint_path.exists():
            return
        try:
            with self.checkpoint_path.open("rb") as fh:
                payload = pickle.load(fh)
        except (OSError, pickle.PickleError, EOFError):
            return

        storage = defaultdict(lambda: defaultdict(dict))
        for thread_id, namespaces in payload.get("storage", {}).items():
            storage[thread_id] = defaultdict(dict)
            for namespace, checkpoints in namespaces.items():
                storage[thread_id][namespace] = dict(checkpoints)
        self.storage = storage
        self.writes = defaultdict(dict, payload.get("writes", {}))
        self.blobs = defaultdict()
        self.blobs.update(payload.get("blobs", {}))

    def _flush(self) -> None:
        payload = {
            "storage": _plain_mapping(self.storage),
            "writes": _plain_mapping(self.writes),
            "blobs": _plain_mapping(self.blobs),
        }
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.checkpoint_path.with_suffix(self.checkpoint_path.suffix + ".tmp")
        with tmp_path.open("wb") as fh:
            pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
        tmp_path.replace(self.checkpoint_path)

    def put(self, config, checkpoint, metadata, new_versions):  # type: ignore[no-untyped-def]
        with self._file_lock:
            updated = super().put(config, checkpoint, metadata, new_versions)
            self._flush()
            return updated

    def put_writes(self, config, writes, task_id, task_path=""):  # type: ignore[no-untyped-def]
        with self._file_lock:
            updated = super().put_writes(config, writes, task_id, task_path)
            self._flush()
            return updated


def review_job_checkpoint_path(project_root: str | Path) -> Path:
    return Path(project_root) / ".pecker_checkpoints" / "langgraph.pkl"


def build_review_job_checkpointer(project_root: str | Path) -> FileLangGraphCheckpointSaver:
    return FileLangGraphCheckpointSaver(review_job_checkpoint_path(project_root))
