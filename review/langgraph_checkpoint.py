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
from typing import Any, Dict, Mapping

from api.sanitize import redact_text
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


def summarize_review_job_checkpoints(
    project_root: str | Path,
    *,
    limit: int = 20,
    include_thread_id: str = "",
) -> Dict[str, Any]:
    """Return safe checkpoint-file metadata without exposing graph state values."""
    root = Path(project_root)
    checkpoint_path = review_job_checkpoint_path(root)
    safe_include_thread_id = _safe_thread_id(include_thread_id) if include_thread_id else ""
    summary: Dict[str, Any] = {
        "status": "missing",
        "exists": checkpoint_path.exists(),
        "checkpoint_path": _safe_relative_path(checkpoint_path, root),
        "thread_count": 0,
        "threads": [],
    }
    if not checkpoint_path.exists():
        return summary

    try:
        stat = checkpoint_path.stat()
        summary["size_bytes"] = stat.st_size
        summary["mtime"] = stat.st_mtime
        with checkpoint_path.open("rb") as fh:
            payload = pickle.load(fh)
    except (OSError, pickle.PickleError, EOFError) as exc:
        summary["status"] = "error"
        summary["error_type"] = type(exc).__name__
        return summary

    storage = payload.get("storage", {}) if isinstance(payload, Mapping) else {}
    if not isinstance(storage, Mapping):
        summary["status"] = "error"
        summary["error_type"] = "InvalidStorage"
        return summary

    threads = [
        _summarize_checkpoint_thread(thread_id, namespaces)
        for thread_id, namespaces in sorted(
            storage.items(),
            key=lambda item: str(item[0]),
        )
    ]
    safe_limit = max(1, int(limit or 20))
    visible_threads = threads[:safe_limit]
    if safe_include_thread_id and not any(
        thread.get("thread_id") == safe_include_thread_id
        for thread in visible_threads
    ):
        matching_thread = next(
            (
                thread
                for thread in threads
                if thread.get("thread_id") == safe_include_thread_id
            ),
            None,
        )
        if matching_thread is not None:
            visible_threads.append(matching_thread)
    summary.update(
        {
            "status": "ready",
            "thread_count": len(threads),
            "threads": visible_threads,
        }
    )
    if len(threads) > safe_limit:
        summary["truncated_threads"] = len(threads) - safe_limit
    return summary


def build_langgraph_checkpoint_observability(
    project_root: str | Path,
    *,
    thread_id: str,
) -> Dict[str, Any]:
    safe_thread_id = _safe_thread_id(thread_id)
    summary = summarize_review_job_checkpoints(
        project_root,
        include_thread_id=safe_thread_id,
    )
    matching_thread = next(
        (
            thread
            for thread in summary.get("threads", [])
            if isinstance(thread, Mapping)
            and str(thread.get("thread_id") or "") == safe_thread_id
        ),
        None,
    )
    return {
        "enabled": True,
        "thread_id": safe_thread_id,
        "status": str(summary.get("status") or "unknown"),
        "checkpoint_path": str(summary.get("checkpoint_path") or ""),
        "checkpoint_exists": bool(summary.get("exists")),
        "thread_found": matching_thread is not None,
        "checkpoint_count": int(
            (matching_thread or {}).get("checkpoint_count") or 0
        ),
    }


def _summarize_checkpoint_thread(thread_id: Any, namespaces: Any) -> Dict[str, Any]:
    namespace_map = namespaces if isinstance(namespaces, Mapping) else {}
    checkpoint_count = 0
    for checkpoints in namespace_map.values():
        if isinstance(checkpoints, Mapping):
            checkpoint_count += len(checkpoints)
    return {
        "thread_id": _safe_thread_id(thread_id),
        "namespace_count": len(namespace_map),
        "checkpoint_count": checkpoint_count,
    }


def _safe_relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(root.resolve(strict=False))).replace("\\", "/")
    except ValueError:
        return path.name


def _safe_thread_id(value: Any) -> str:
    return redact_text(str(value or ""))[:200]
