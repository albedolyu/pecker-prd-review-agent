"""Seed Pecker worker system prompts into Langfuse.

The codebase still owns runtime checklist, examples, learnings, and refs
assembly. Langfuse stores the base system template with runtime placeholders.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from review.dimensions import get_review_dimensions
from review.langfuse_prompt_provider import worker_prompt_name
from review.prompting import _WORKER_SHARED_RULES, _WORKER_SYSTEM_TEMPLATE


ClientFactory = Callable[[], Any]
DEFAULT_DIM_KEYS = ("structure", "quality", "ai_coding", "data_quality")
_PLACEHOLDER_KEYS = (
    "codename",
    "dimension_name",
    "dimension_rules",
    "checklist_list",
    "tone_instructions_block",
)


def langfuse_worker_prompt_template() -> str:
    template = _WORKER_SYSTEM_TEMPLATE.replace("{shared_rules}", _WORKER_SHARED_RULES)
    for key in _PLACEHOLDER_KEYS:
        template = template.replace("{" + key + "}", "{{" + key + "}}")
    return template


def seed_worker_prompts(
    *,
    dim_keys: Iterable[str] = DEFAULT_DIM_KEYS,
    label: str = "production",
    dry_run: bool = False,
    client_factory: Optional[ClientFactory] = None,
) -> Dict[str, Any]:
    dimensions = get_review_dimensions()
    template = langfuse_worker_prompt_template()
    client = None if dry_run else (client_factory or _default_langfuse_client_factory)()
    prompts = []

    for dim_key in dim_keys:
        if dim_key not in dimensions:
            raise ValueError(f"unknown review dimension: {dim_key}")
        name = worker_prompt_name(dim_key)
        prompt_info = {
            "name": name,
            "dim_key": dim_key,
            "kind": "system",
            "label": label,
            "dry_run": dry_run,
        }
        if client is not None:
            client.create_prompt(
                name=name,
                prompt=template,
                labels=[label],
                tags=["pecker", "worker", "system", "worker_system_base", f"dim:{dim_key}"],
                type="text",
                config={
                    "managed_by": "pecker",
                    "dim_key": dim_key,
                    "template": "worker_system_base",
                    "dynamic_sections": [
                        "checklist",
                        "examples",
                        "learnings",
                        "real_refs",
                        "feedback",
                    ],
                },
                commit_message="Seed Pecker worker system prompt",
            )
        prompts.append(prompt_info)

    return {
        "ok": True,
        "created_count": 0 if dry_run else len(prompts),
        "prompts": prompts,
    }


def _default_langfuse_client_factory() -> Any:
    try:
        from langfuse import get_client
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("langfuse package is not available") from exc
    return get_client()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Seed Pecker worker system prompts into Langfuse")
    parser.add_argument("--label", default="production", help="Langfuse label to attach to created prompts")
    parser.add_argument("--dim", action="append", dest="dims", help="Dimension key to seed; repeatable")
    parser.add_argument("--dry-run", action="store_true", help="Preview prompt names without writing to Langfuse")
    args = parser.parse_args(argv)

    result = seed_worker_prompts(
        dim_keys=args.dims or DEFAULT_DIM_KEYS,
        label=args.label,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
