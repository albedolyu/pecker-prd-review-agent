from __future__ import annotations


def test_langgraph_spike_isolates_worker_failures_and_still_merges():
    from review.langgraph_spike import build_langgraph_review_spike

    def worker_runner(dim_key, _state):
        if dim_key == "quality":
            raise RuntimeError("quality timeout")
        return {
            "dimension": dim_key,
            "items": [
                {
                    "id": f"{dim_key}-1",
                    "dimension": dim_key,
                    "severity": "should",
                    "issue": f"{dim_key} issue",
                }
            ],
        }

    graph = build_langgraph_review_spike(
        dimensions=["structure", "quality"],
        worker_runner=worker_runner,
        advisor_policy=lambda _state: False,
    )

    result = graph.invoke({"prd_content": "prd", "wiki_pages": {}})

    assert result["worker_errors"] == {"quality": "quality timeout"}
    assert result["workers"]["quality"]["items"] == []
    assert [item["dimension"] for item in result["merged_items"]] == ["structure"]
    assert result["advisor_ran"] is False
    assert result["trace"] == [
        "run_workers",
        "merge_items",
        "decide_advisor:skip",
    ]


def test_langgraph_spike_runs_advisor_when_policy_requires_it():
    from review.langgraph_spike import build_langgraph_review_spike

    advisor_calls = []

    def worker_runner(dim_key, _state):
        return {
            "dimension": dim_key,
            "items": [
                {
                    "id": f"{dim_key}-1",
                    "dimension": dim_key,
                    "severity": "must",
                    "issue": f"{dim_key} issue",
                }
            ],
        }

    def advisor_runner(items, _state):
        advisor_calls.append([item["id"] for item in items])
        return {"verdict": "REVIEWED", "checked": len(items)}

    graph = build_langgraph_review_spike(
        dimensions=["structure"],
        worker_runner=worker_runner,
        advisor_runner=advisor_runner,
        advisor_policy=lambda state: any(
            item.get("severity") == "must" for item in state.get("merged_items", [])
        ),
    )

    result = graph.invoke({"prd_content": "prd", "wiki_pages": {}})

    assert advisor_calls == [["structure-1"]]
    assert result["advisor_ran"] is True
    assert result["advisor_result"] == {"verdict": "REVIEWED", "checked": 1}
    assert result["trace"][-2:] == ["decide_advisor:run", "run_advisor"]


def test_langgraph_spike_can_checkpoint_state_by_thread_id():
    from langgraph.checkpoint.memory import InMemorySaver

    from review.langgraph_spike import build_langgraph_review_spike

    def worker_runner(dim_key, _state):
        return {
            "dimension": dim_key,
            "items": [{"id": f"{dim_key}-1", "dimension": dim_key, "severity": "should"}],
        }

    graph = build_langgraph_review_spike(
        dimensions=["structure"],
        worker_runner=worker_runner,
        advisor_policy=lambda _state: False,
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "review-001"}}

    result = graph.invoke({"prd_content": "prd", "wiki_pages": {}}, config=config)
    checkpoint = graph.get_state(config)

    assert checkpoint.values["merged_items"] == result["merged_items"]
    assert checkpoint.values["trace"] == [
        "run_workers",
        "merge_items",
        "decide_advisor:skip",
    ]
