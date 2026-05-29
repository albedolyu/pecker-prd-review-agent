"""Build a local LangGraph/Langfuse audit snapshot for one Pecker review run."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from api.sanitize import redact_sensitive, redact_text


def build_langfuse_run_audit(
    review_result: Dict[str, Any],
    *,
    confirmation_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    telemetry = _dict_at(review_result, "telemetry")
    observability = _dict_at(telemetry, "observability")
    langfuse = _dict_at(observability, "langfuse")
    evidence = _dict_at(observability, "langfuse_evidence")
    checkpoint = _dict_at(observability, "langgraph_checkpoint")
    pm_feedback = _dict_at(confirmation_result or {}, "langfuse_feedback")
    prompt_versions = _collect_prompt_versions(review_result)
    langgraph = _langgraph_snapshot(review_result)

    missing = _missing_fields(
        orchestrator=_text(telemetry.get("orchestrator") or review_result.get("orchestrator")),
        langgraph=langgraph,
        langfuse=langfuse,
        evidence=evidence,
        checkpoint=checkpoint,
        pm_feedback=pm_feedback,
        prompt_versions=prompt_versions,
        review_item_count=_review_item_count(review_result),
    )
    trace_url = _safe_url(langfuse.get("trace_url"))
    trace_id = _safe_trace_id(langfuse.get("trace_id"))
    checkpoint_snapshot = _checkpoint_snapshot(checkpoint)
    session_checkpoint = _session_checkpoint_status(langfuse, checkpoint_snapshot)
    ok = not missing
    audit = {
        "ok": ok,
        "status": "ready" if ok else "missing",
        "missing_count": len(missing),
        "review_id": _text(review_result.get("review_id")),
        "workspace": _text(review_result.get("workspace")),
        "prd_name": _text(review_result.get("prd_name")),
        "orchestrator": _text(telemetry.get("orchestrator") or review_result.get("orchestrator")),
        "session_checkpoint_linked": session_checkpoint["linked"],
        "session_checkpoint_mismatch": session_checkpoint["mismatch"],
        "langfuse": {
            "status": _text(langfuse.get("status")),
            "configured": bool(langfuse.get("configured")),
            "enabled": bool(langfuse.get("enabled")),
            "session_id": _text(langfuse.get("session_id")),
            "trace_id": trace_id,
            "trace_url": trace_url,
            "trace_link_ready": bool(trace_url),
            "prompt_versions": prompt_versions,
            "evidence_scores": _score_snapshot(
                evidence,
                extra_keys=("reliability", "caveat", "retracted"),
                trace_id=trace_id,
            ),
            "pm_feedback_scores": _score_snapshot(
                pm_feedback,
                extra_keys=("aggregate_acceptance_rate",),
                trace_id=trace_id,
            ),
        },
        "langgraph": langgraph,
        "langgraph_checkpoint": checkpoint_snapshot,
        "missing": missing,
    }
    return redact_sensitive(audit)


def build_langfuse_run_audit_snapshot(
    audit: Dict[str, Any],
    *,
    json_path: str,
    markdown_path: str,
    status: str | None = None,
) -> Dict[str, Any]:
    langfuse = _dict_at(audit, "langfuse")
    langgraph = _dict_at(audit, "langgraph")
    checkpoint = _dict_at(audit, "langgraph_checkpoint")
    missing = audit.get("missing", [])
    snapshot = {
        "ok": bool(audit.get("ok")),
        "status": status or str(audit.get("status") or ("ready" if audit.get("ok") else "missing")),
        "json_path": json_path,
        "markdown_path": markdown_path,
        "missing": missing,
        "missing_count": (
            audit.get("missing_count")
            if isinstance(audit.get("missing_count"), int)
            else len(missing)
        ),
        "trace_link_ready": bool(langfuse.get("trace_link_ready")),
        "graph_trace_ready": bool(langgraph.get("graph_trace_ready")),
        "graph_trace_order_ready": bool(langgraph.get("graph_trace_order_ready")),
        "worker_nodes_ready": bool(langgraph.get("worker_nodes_ready")),
        "checkpoint_ready": bool(
            checkpoint.get("status") == "ready"
            and checkpoint.get("thread_found")
            and checkpoint.get("checkpoint_exists", True)
        ),
        "session_checkpoint_linked": bool(
            audit.get("session_checkpoint_linked")
        ),
        "session_checkpoint_mismatch": bool(
            audit.get("session_checkpoint_mismatch")
            or _missing_has_prefix(missing, "langfuse.session_checkpoint_thread")
        ),
        "evidence_score_failure": _missing_has_prefix(missing, "langfuse_evidence"),
        "feedback_score_failure": _missing_has_prefix(missing, "langfuse_feedback"),
    }
    return redact_sensitive(snapshot)


def _missing_fields(
    *,
    orchestrator: str,
    langgraph: Dict[str, Any],
    langfuse: Dict[str, Any],
    evidence: Dict[str, Any],
    checkpoint: Dict[str, Any],
    pm_feedback: Dict[str, Any],
    prompt_versions: list[Dict[str, Any]],
    review_item_count: int,
) -> list[str]:
    missing = []
    trace_id = _safe_trace_id(langfuse.get("trace_id"))
    if orchestrator != "langgraph":
        missing.append("telemetry.orchestrator")
    else:
        if not langgraph.get("graph_trace_ready"):
            missing.append("langgraph.graph_trace")
            for node in langgraph.get("missing_worker_trace_nodes") or []:
                missing.append(f"langgraph.graph_trace.{node}")
            if (
                langgraph.get("graph_trace_order_ready") is False
                and not langgraph.get("missing_worker_trace_nodes")
                and langgraph.get("graph_trace")
            ):
                missing.append("langgraph.graph_trace.order")
        if not langgraph.get("worker_node_statuses"):
            missing.append("langgraph.worker_node_statuses")
        elif not langgraph.get("worker_nodes_named"):
            missing.append("langgraph.worker_node_statuses.dimension")
        elif not langgraph.get("worker_nodes_ready"):
            missing.append("langgraph.worker_node_statuses.status")
    if not langfuse.get("enabled"):
        missing.append("langfuse.enabled")
    if not langfuse.get("configured"):
        missing.append("langfuse.configured")
    for key in ("session_id", "trace_id", "trace_url"):
        if not langfuse.get(key):
            missing.append(f"langfuse.{key}")
    if langfuse.get("status") not in {"started", "done"}:
        missing.append("langfuse.status")
    if review_item_count > 0 and not evidence:
        missing.append("langfuse_evidence")
    if evidence and evidence.get("status") != "recorded":
        missing.append("langfuse_evidence.status")
    if evidence and not _score_trace_linked(evidence, trace_id):
        missing.append("langfuse_evidence.trace_id")
    if _score_delivery_missing(evidence):
        missing.append("langfuse_evidence.scores_sent")
    if not checkpoint:
        missing.append("langgraph_checkpoint")
    else:
        if not checkpoint.get("enabled"):
            missing.append("langgraph_checkpoint.enabled")
        if checkpoint.get("status") != "ready":
            missing.append("langgraph_checkpoint.status")
        if not checkpoint.get("thread_found"):
            missing.append("langgraph_checkpoint.thread_found")
        if not checkpoint.get("checkpoint_exists"):
            missing.append("langgraph_checkpoint.checkpoint_exists")
        session_id = _text(langfuse.get("session_id"))
        checkpoint_thread_id = _text(checkpoint.get("thread_id"))
        if not checkpoint_thread_id:
            missing.append("langgraph_checkpoint.thread_id")
        if session_id and checkpoint_thread_id and session_id != checkpoint_thread_id:
            missing.append("langfuse.session_checkpoint_thread")
    if pm_feedback and pm_feedback.get("status") != "recorded":
        missing.append("langfuse_feedback.status")
    if pm_feedback and not _score_trace_linked(pm_feedback, trace_id):
        missing.append("langfuse_feedback.trace_id")
    if _score_delivery_missing(pm_feedback):
        missing.append("langfuse_feedback.scores_sent")
    if not prompt_versions:
        missing.append("worker_prompts")
    elif langgraph.get("worker_node_statuses"):
        prompt_workers = {
            _text(prompt.get("worker"))
            for prompt in prompt_versions
            if _text(prompt.get("worker"))
        }
        for worker in _required_prompt_workers(langgraph):
            if worker not in prompt_workers:
                missing.append(f"worker_prompt.{worker}")
    for prompt in prompt_versions:
        prefix = f"worker_prompt.{prompt.get('worker') or 'unknown'}"
        if prompt.get("source") != "langfuse":
            missing.append(f"{prefix}.source")
        if prompt.get("status") != "ready":
            missing.append(f"{prefix}.status")
        if prompt.get("source") == "langfuse" and not prompt.get("label"):
            missing.append(f"{prefix}.label")
        if prompt.get("version") in {None, ""}:
            missing.append(f"{prefix}.version")
        if prompt.get("source") == "langfuse" and not prompt.get("hash"):
            missing.append(f"{prefix}.hash")
    return missing


def _collect_prompt_versions(review_result: Dict[str, Any]) -> list[Dict[str, Any]]:
    telemetry = _dict_at(review_result, "telemetry")
    workers = _dict_at(telemetry, "workers")
    prompts = []
    for worker, worker_telemetry in sorted(workers.items()):
        if not isinstance(worker_telemetry, dict):
            continue
        prompt = worker_telemetry.get("prompt")
        if not isinstance(prompt, dict):
            continue
        prompts.append(_prompt_version_snapshot(worker, prompt))
    seen = {(prompt.get("worker"), prompt.get("name")) for prompt in prompts}
    for worker in review_result.get("workers") or []:
        if not isinstance(worker, dict):
            continue
        worker_telemetry = worker.get("telemetry")
        if not isinstance(worker_telemetry, dict):
            continue
        prompt = worker_telemetry.get("prompt")
        if not isinstance(prompt, dict):
            continue
        worker_name = worker.get("dimension") or worker.get("dimension_name") or "worker"
        candidate = _prompt_version_snapshot(worker_name, prompt)
        key = (candidate.get("worker"), candidate.get("name"))
        if key in seen:
            continue
        seen.add(key)
        prompts.append(candidate)
    prompts.sort(key=lambda prompt: (str(prompt.get("worker") or ""), str(prompt.get("name") or "")))
    return prompts


def _required_prompt_workers(langgraph: Dict[str, Any]) -> list[str]:
    workers = []
    seen = set()
    for item in _dict_list(langgraph.get("worker_node_statuses")):
        worker = _text(item.get("dimension"))
        if not worker or worker in seen:
            continue
        seen.add(worker)
        workers.append(worker)
    return workers


def _prompt_version_snapshot(worker: Any, prompt: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "worker": _text(worker),
        "name": _text(prompt.get("name")),
        "source": _text(prompt.get("source")),
        "status": _text(prompt.get("status")),
        "label": _text(prompt.get("label")),
        "version": prompt.get("version"),
        "hash": _text(prompt.get("hash")),
    }


def _langgraph_snapshot(review_result: Dict[str, Any]) -> Dict[str, Any]:
    telemetry = _dict_at(review_result, "telemetry")
    graph_trace = _text_list(telemetry.get("graph_trace") or review_result.get("graph_trace"))
    worker_node_statuses = [
        _worker_node_status_snapshot(item)
        for item in _dict_list(telemetry.get("worker_node_statuses") or review_result.get("worker_node_statuses"))
    ]
    resilience = _dict_at(telemetry, "resilience") or _dict_at(review_result, "resilience")
    worker_nodes_named = bool(worker_node_statuses) and all(
        item.get("dimension") for item in worker_node_statuses
    )
    required_worker_trace_nodes = [
        f"worker.{item.get('dimension')}"
        for item in worker_node_statuses
        if item.get("dimension")
    ]
    missing_worker_trace_nodes = [
        node
        for node in required_worker_trace_nodes
        if _trace_node_index(graph_trace, node) is None
    ]
    graph_trace_order_ready = _graph_trace_order_ready(graph_trace, required_worker_trace_nodes)
    graph_trace_ready = (
        bool(graph_trace)
        and _trace_node_index(graph_trace, "prepare_round") is not None
        and _trace_node_index(graph_trace, "finalize_review") is not None
        and not missing_worker_trace_nodes
        and graph_trace_order_ready
    )
    worker_nodes_ready = worker_nodes_named and all(
        item.get("status") in {"success", "ok", "completed", "done"}
        for item in worker_node_statuses
    )
    return {
        "graph_trace": graph_trace,
        "graph_trace_ready": graph_trace_ready,
        "graph_trace_order_ready": graph_trace_order_ready,
        "missing_worker_trace_nodes": missing_worker_trace_nodes,
        "worker_node_statuses": worker_node_statuses,
        "worker_nodes_named": worker_nodes_named,
        "worker_nodes_ready": worker_nodes_ready,
        "failed_workers": _safe_int(resilience.get("failed_workers")),
        "recovered_workers": _safe_int(resilience.get("recovered_workers")),
        "recommended_batch_size": _safe_int(resilience.get("recommended_batch_size")),
    }


def _graph_trace_order_ready(graph_trace: list[str], worker_trace_nodes: list[str]) -> bool:
    prepare_index = _trace_node_index(graph_trace, "prepare_round")
    finalize_index = _trace_node_index(graph_trace, "finalize_review")
    if not graph_trace or prepare_index is None or finalize_index is None:
        return False
    if prepare_index >= finalize_index:
        return False
    for node in worker_trace_nodes:
        node_index = _trace_node_index(graph_trace, node)
        if node_index is None or not prepare_index < node_index < finalize_index:
            return False
    return True


def _trace_node_index(graph_trace: list[str], node: str) -> int | None:
    for index, entry in enumerate(graph_trace):
        if _trace_entry_matches_node(entry, node):
            return index
    return None


def _trace_entry_matches_node(entry: str, node: str) -> bool:
    if entry == node:
        return True
    if node == "prepare_round":
        return entry.startswith("prepare_round:")
    if node == "finalize_round":
        return entry.startswith("finalize_round:")
    if node == "finalize_review":
        return entry.startswith("finalize_review:")
    if node.startswith("worker."):
        dim = node.split(".", 1)[1]
        return (
            entry.startswith(f"worker.{dim}:")
            or entry.startswith(f"worker:{dim}:")
            or f":{dim}:" in entry and entry.startswith("worker:")
        )
    return False


def _worker_node_status_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "dimension": _text(payload.get("dimension")),
        "status": _text(payload.get("status")),
        "error_type": _text(payload.get("error_type")),
    }


def _score_snapshot(
    payload: Dict[str, Any],
    *,
    extra_keys: tuple[str, ...],
    trace_id: str,
) -> Dict[str, Any]:
    score_trace_id = _safe_trace_id(payload.get("trace_id"))
    snapshot = {
        "status": _text(payload.get("status")),
        "scored_items": _safe_int(payload.get("scored_items")),
        "scores_sent": _safe_int(payload.get("scores_sent")),
    }
    if payload:
        snapshot["trace_id"] = score_trace_id
        snapshot["trace_linked"] = bool(trace_id and score_trace_id == trace_id)
    for key in extra_keys:
        if key in payload:
            snapshot[key] = payload.get(key)
    return snapshot


def _session_checkpoint_status(
    langfuse: Dict[str, Any],
    checkpoint: Dict[str, Any],
) -> Dict[str, bool]:
    session_id = _text(langfuse.get("session_id"))
    checkpoint_thread_id = _text(checkpoint.get("thread_id"))
    linked = bool(session_id and checkpoint_thread_id and session_id == checkpoint_thread_id)
    mismatch = bool(session_id and checkpoint_thread_id and session_id != checkpoint_thread_id)
    return {"linked": linked, "mismatch": mismatch}


def _score_trace_linked(payload: Dict[str, Any], trace_id: str) -> bool:
    if not payload:
        return True
    if not trace_id:
        return False
    return _safe_trace_id(payload.get("trace_id")) == trace_id


def _score_delivery_missing(payload: Dict[str, Any]) -> bool:
    if not payload or payload.get("status") != "recorded":
        return False
    return _safe_int(payload.get("scored_items")) > 0 and _safe_int(payload.get("scores_sent")) <= 0


def _review_item_count(review_result: Dict[str, Any]) -> int:
    for key in ("items", "merged_items"):
        value = review_result.get(key)
        if isinstance(value, list):
            return len([item for item in value if isinstance(item, dict)])
    return 0


def _checkpoint_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "enabled": bool(payload.get("enabled")),
        "thread_id": _text(payload.get("thread_id")),
        "status": _text(payload.get("status")),
        "checkpoint_path": _text(payload.get("checkpoint_path")),
        "checkpoint_exists": bool(payload.get("checkpoint_exists")),
        "thread_found": bool(payload.get("thread_found")),
        "checkpoint_count": _safe_int(payload.get("checkpoint_count")),
    }


def _dict_at(payload: Optional[Dict[str, Any]], key: str) -> Dict[str, Any]:
    value = payload.get(key) if isinstance(payload, dict) else None
    return value if isinstance(value, dict) else {}


def _missing_has_prefix(missing: Any, prefix: str) -> bool:
    values = missing if isinstance(missing, list) else []
    return any(_text(item).startswith(prefix) for item in values)


def _dict_list(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for text in (_text(item) for item in value) if text][:40]


def _text(value: Any) -> str:
    return redact_text(str(value or ""))[:300]


def _safe_url(value: Any) -> str:
    text = _text(value)
    if text.startswith(("https://", "http://")):
        return text[:500]
    return ""


def _safe_trace_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    if len(text) == 32 and all(char in "0123456789abcdef" for char in text):
        return text
    return ""


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _render_markdown(audit: Dict[str, Any]) -> str:
    langfuse = audit["langfuse"]
    langgraph = audit.get("langgraph") or {}
    checkpoint = audit.get("langgraph_checkpoint") or {}
    missing = audit.get("missing") or []
    ok = bool(audit.get("ok"))
    status = str(audit.get("status") or ("ready" if ok else "missing"))
    missing_count = (
        audit.get("missing_count")
        if isinstance(audit.get("missing_count"), int)
        else len(missing)
    )
    session_id = langfuse.get("session_id") or ""
    checkpoint_thread_id = checkpoint.get("thread_id") or ""
    session_checkpoint_linked = bool(
        session_id and checkpoint_thread_id and session_id == checkpoint_thread_id
    )
    session_checkpoint_mismatch = bool(
        audit.get("session_checkpoint_mismatch")
        or (session_id and checkpoint_thread_id and session_id != checkpoint_thread_id)
    )
    lines = [
        f"# Langfuse Run Audit: {audit.get('review_id') or '-'}",
        "",
        f"- status: `{status}`",
        f"- ok: `{ok}`",
        f"- missing_count: `{missing_count}`",
        f"- orchestrator: `{audit.get('orchestrator') or '-'}`",
        f"- session_id: `{session_id or '-'}`",
        f"- trace_id: `{langfuse.get('trace_id') or '-'}`",
        f"- trace_url: {langfuse.get('trace_url') or '-'}",
        f"- evidence_scores: `{langfuse['evidence_scores'].get('status') or '-'}`",
        f"- evidence_trace_linked: `{langfuse['evidence_scores'].get('trace_linked')}`",
        f"- pm_feedback_scores: `{langfuse['pm_feedback_scores'].get('status') or '-'}`",
        f"- pm_feedback_trace_linked: `{langfuse['pm_feedback_scores'].get('trace_linked')}`",
        f"- graph_trace_ready: `{langgraph.get('graph_trace_ready')}`",
        f"- graph_trace_order_ready: `{langgraph.get('graph_trace_order_ready')}`",
        f"- worker_nodes_ready: `{langgraph.get('worker_nodes_ready')}`",
        f"- recovered_workers: `{langgraph.get('recovered_workers') or 0}`",
        f"- checkpoint_status: `{checkpoint.get('status') or '-'}`",
        f"- checkpoint_thread_id: `{checkpoint_thread_id or '-'}`",
        f"- session_checkpoint_linked: `{session_checkpoint_linked}`",
        f"- session_checkpoint_mismatch: `{session_checkpoint_mismatch}`",
        f"- checkpoint_thread_found: `{checkpoint.get('thread_found')}`",
        f"- checkpoint_count: `{checkpoint.get('checkpoint_count') or 0}`",
        "",
        "## LangGraph Trace",
        "",
        " -> ".join(langgraph.get("graph_trace") or []) or "-",
        "",
        "## Worker Prompts",
        "",
        "| worker | prompt | source | status | label | version | hash |",
        "|---|---|---|---|---|---:|---|",
    ]
    for prompt in langfuse["prompt_versions"]:
        lines.append(
            "| {worker} | {name} | {source} | {status} | {label} | {version} | {hash} |".format(
                worker=prompt.get("worker") or "-",
                name=prompt.get("name") or "-",
                source=prompt.get("source") or "-",
                status=prompt.get("status") or "-",
                label=prompt.get("label") or "-",
                version=prompt.get("version") or "-",
                hash=prompt.get("hash") or "-",
            )
        )
    if missing:
        lines.extend(["", "## Missing", ""])
        lines.extend(f"- `{item}`" for item in missing)
    return "\n".join(lines)


def render_langfuse_run_audit_markdown(audit: Dict[str, Any]) -> str:
    return _render_markdown(audit)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build a local Langfuse audit for one Pecker review")
    parser.add_argument("--review-result", required=True, help="Path to a review result JSON object")
    parser.add_argument("--confirmation-result", help="Optional confirm response JSON object")
    parser.add_argument("--format", choices=("json", "markdown", "snapshot"), default="json")
    parser.add_argument("--output-json", help="Optional path to write the audit JSON artifact")
    parser.add_argument("--output-markdown", help="Optional path to write the audit Markdown artifact")
    parser.add_argument("--output-snapshot", help="Optional path to write the compact audit snapshot JSON")
    parser.add_argument("--snapshot-json-path", help="Path stored in snapshot.json_path")
    parser.add_argument("--snapshot-markdown-path", help="Path stored in snapshot.markdown_path")
    parser.add_argument("--require-ready", action="store_true", help="Exit 1 when required audit fields are missing")
    args = parser.parse_args(argv)

    review_result = _load_json(Path(args.review_result))
    confirmation_result = _load_json(Path(args.confirmation_result)) if args.confirmation_result else None
    audit = build_langfuse_run_audit(
        review_result,
        confirmation_result=confirmation_result,
    )
    if args.output_json:
        _write_text_artifact(
            Path(args.output_json),
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        )
    if args.output_markdown:
        _write_text_artifact(
            Path(args.output_markdown),
            _render_markdown(audit) + "\n",
        )
    snapshot = None
    if args.output_snapshot or args.format == "snapshot":
        snapshot = build_langfuse_run_audit_snapshot(
            audit,
            json_path=args.snapshot_json_path or args.output_json or "",
            markdown_path=args.snapshot_markdown_path or args.output_markdown or "",
        )
    if args.output_snapshot:
        _write_text_artifact(
            Path(args.output_snapshot),
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        )
    if args.format == "markdown":
        print(_render_markdown(audit))
    elif args.format == "snapshot":
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 1 if args.require_ready and not audit.get("ok") else 0


def _write_text_artifact(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
