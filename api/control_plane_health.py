"""Read-only LangGraph/Langfuse control-plane health snapshot."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any, Dict

from api.deps import get_project_root
from review.langgraph_checkpoint import review_job_checkpoint_path
from review.orchestration import _get_review_orchestrator_mode
from review.langfuse_prompt_provider import prompt_management_status_snapshot


def build_control_plane_health(project_root: str | Path | None = None) -> Dict[str, Any]:
    root = Path(project_root or get_project_root())
    checkpoint_path = review_job_checkpoint_path(root)
    langfuse_enabled = _truthy_env("PECKER_LANGFUSE_ENABLED", "0")
    langfuse_configured = bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY")
        and os.environ.get("LANGFUSE_SECRET_KEY")
    )
    return {
        "orchestrator": {
            "mode": _get_review_orchestrator_mode(),
            "checkpointing": "file",
            "checkpoint_path": _safe_relative_path(checkpoint_path, root),
            "checkpoint_exists": checkpoint_path.exists(),
        },
        "langfuse": {
            "enabled": langfuse_enabled,
            "configured": langfuse_configured,
            "sdk_available": importlib.util.find_spec("langfuse") is not None,
            "host": os.environ.get("LANGFUSE_BASE_URL")
            or os.environ.get("LANGFUSE_HOST")
            or "",
            "prompt_label": os.environ.get("PECKER_LANGFUSE_PROMPT_LABEL")
            or os.environ.get("LANGFUSE_PROMPT_LABEL")
            or "production",
            "prompt_management": prompt_management_status_snapshot(),
        },
    }


def _truthy_env(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _safe_relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(root.resolve(strict=False))).replace("\\", "/")
    except ValueError:
        return ".pecker_checkpoints/langgraph.pkl"
