from __future__ import annotations

import json
import pickle


def test_file_langgraph_checkpointer_survives_new_instance(tmp_path):
    from review.langgraph_checkpoint import FileLangGraphCheckpointSaver
    from review.langgraph_spike import build_langgraph_review_spike

    checkpoint_path = tmp_path / "langgraph-checkpoints.pkl"
    config = {"configurable": {"thread_id": "review-job:rjob_001"}}

    def worker_runner(dim_key, _state):
        return {
            "dimension": dim_key,
            "items": [
                {"id": f"{dim_key}-1", "dimension": dim_key, "severity": "should"}
            ],
        }

    first_graph = build_langgraph_review_spike(
        dimensions=["structure"],
        worker_runner=worker_runner,
        advisor_policy=lambda _state: False,
        checkpointer=FileLangGraphCheckpointSaver(checkpoint_path),
    )
    result = first_graph.invoke({"prd_content": "prd", "wiki_pages": {}}, config=config)

    second_graph = build_langgraph_review_spike(
        dimensions=["structure"],
        worker_runner=worker_runner,
        advisor_policy=lambda _state: False,
        checkpointer=FileLangGraphCheckpointSaver(checkpoint_path),
    )
    checkpoint = second_graph.get_state(config)

    assert checkpoint.values["merged_items"] == result["merged_items"]
    assert checkpoint.values["trace"] == [
        "run_workers",
        "merge_items",
        "decide_advisor:skip",
    ]


def test_langgraph_checkpoint_summary_exposes_only_safe_thread_metadata(tmp_path):
    from review.langgraph_checkpoint import (
        build_langgraph_checkpoint_observability,
        FileLangGraphCheckpointSaver,
        summarize_review_job_checkpoints,
    )
    from review.langgraph_spike import build_langgraph_review_spike

    checkpoint_path = tmp_path / ".pecker_checkpoints" / "langgraph.pkl"
    config = {"configurable": {"thread_id": "review-job:rjob_secret"}}

    def worker_runner(dim_key, _state):
        return {
            "dimension": dim_key,
            "items": [
                {
                    "id": f"{dim_key}-1",
                    "dimension": dim_key,
                    "problem": "raw finding body must not leak",
                }
            ],
        }

    graph = build_langgraph_review_spike(
        dimensions=["structure"],
        worker_runner=worker_runner,
        advisor_policy=lambda _state: False,
        checkpointer=FileLangGraphCheckpointSaver(checkpoint_path),
    )
    graph.invoke(
        {"prd_content": "raw PRD body must not leak", "wiki_pages": {}},
        config=config,
    )

    summary = summarize_review_job_checkpoints(tmp_path)

    assert summary["status"] == "ready"
    assert summary["exists"] is True
    assert summary["checkpoint_path"] == ".pecker_checkpoints/langgraph.pkl"
    assert summary["thread_count"] == 1
    assert summary["threads"][0]["thread_id"] == "review-job:rjob_secret"
    assert summary["threads"][0]["checkpoint_count"] >= 1
    serialized = json.dumps(summary, ensure_ascii=False)
    assert "raw PRD body must not leak" not in serialized
    assert "raw finding body must not leak" not in serialized

    observability = build_langgraph_checkpoint_observability(
        tmp_path,
        thread_id="review-job:rjob_secret",
    )

    assert observability == {
        "enabled": True,
        "thread_id": "review-job:rjob_secret",
        "status": "ready",
        "checkpoint_path": ".pecker_checkpoints/langgraph.pkl",
        "checkpoint_exists": True,
        "thread_found": True,
        "checkpoint_count": summary["threads"][0]["checkpoint_count"],
    }


def test_checkpoint_observability_finds_thread_beyond_admin_summary_limit(tmp_path):
    from review.langgraph_checkpoint import (
        build_langgraph_checkpoint_observability,
        summarize_review_job_checkpoints,
    )

    checkpoint_path = tmp_path / ".pecker_checkpoints" / "langgraph.pkl"
    checkpoint_path.parent.mkdir(parents=True)
    storage = {
        f"review-job:rjob_{idx:03d}": {"": {f"checkpoint-{idx}": {}}}
        for idx in range(25)
    }
    storage["review-job:rjob_999"] = {
        "": {
            "checkpoint-a": {},
            "checkpoint-b": {},
        }
    }
    with checkpoint_path.open("wb") as fh:
        pickle.dump({"storage": storage, "writes": {}, "blobs": {}}, fh)

    admin_summary = summarize_review_job_checkpoints(tmp_path, limit=20)
    assert admin_summary["thread_count"] == 26
    assert admin_summary["truncated_threads"] == 6
    assert all(
        thread["thread_id"] != "review-job:rjob_999"
        for thread in admin_summary["threads"]
    )

    observability = build_langgraph_checkpoint_observability(
        tmp_path,
        thread_id="review-job:rjob_999",
    )

    assert observability["thread_found"] is True
    assert observability["checkpoint_count"] == 2
