from __future__ import annotations


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
