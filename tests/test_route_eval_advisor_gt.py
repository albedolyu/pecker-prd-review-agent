"""advisor_conflicts GT normalization for route_eval metrics."""
from __future__ import annotations


def test_advisor_resolution_ground_truth_scores_by_merged_ids():
    from eval.route_eval import metrics
    from eval.route_eval import runner

    dataset = [
        {
            "workspace": "workspace-x",
            "worker_outputs": [
                {
                    "id": "R-001",
                    "rule_id": "V-04",
                    "location": "3.1",
                    "issue": "字段缺失导致实现歧义",
                    "severity": "must",
                },
                {
                    "id": "R-002",
                    "rule_id": "V-04",
                    "location": "3.1",
                    "issue": "字段缺失导致实现歧义",
                    "severity": "must",
                },
            ],
            "ground_truth_resolution": {
                "merged": ["R-002"],
                "dropped": [{"id": "R-001", "reason": "duplicate"}],
                "conflict_severity_correct": "must",
            },
        }
    ]

    ground_truth = runner._collect_ground_truth(dataset)
    scores = metrics.compute_capability(
        [[{"id": "R-002", "location": "3.1", "issue": "字段缺失导致实现歧义", "severity": "must"}]],
        ground_truth,
    )

    assert len(ground_truth) == 1
    assert ground_truth[0]["id"] == "workspace-x::R-002"
    assert scores["hits"] == 1
    assert scores["f1"] == 1.0
