from __future__ import annotations

import json


def test_promptopt_global_eval_cli_writes_json_markdown_and_scores(tmp_path):
    from scripts.promptopt_global_eval import main

    input_path = tmp_path / "cases.json"
    output_json = tmp_path / "result.json"
    output_md = tmp_path / "result.md"
    scores_json = tmp_path / "scores.json"
    input_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "a",
                        "baseline": {"items": [{"rule_id": "R1", "location": "1", "issue": "same"}]},
                        "candidate": {"items": [{"rule_id": "R1", "location": "1", "issue": "same"}]},
                    },
                    {
                        "case_id": "b",
                        "baseline": {"items": [{"rule_id": "R2", "location": "2", "issue": "same"}]},
                        "candidate": {"items": [{"rule_id": "R2", "location": "2", "issue": "same"}]},
                    },
                    {
                        "case_id": "c",
                        "baseline": {"items": [{"rule_id": "R3", "location": "3", "issue": "same"}]},
                        "candidate": {"items": [{"rule_id": "R3", "location": "3", "issue": "same"}]},
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    code = main(
        [
            "--input",
            str(input_path),
            "--prompt-variant",
            "compact-v2",
            "--batch-id",
            "batch-1",
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--scores-json",
            str(scores_json),
            "--trace-id",
            "abc123abc123abc123abc123abc123ab",
        ]
    )

    assert code == 0
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["pass"] is True
    assert payload["metadata"]["batch_id"] == "batch-1"
    assert "# Prompt Optimization Global Eval" in output_md.read_text(encoding="utf-8")
    scores = json.loads(scores_json.read_text(encoding="utf-8"))
    assert any(score["name"] == "pecker.promptopt.global_score" for score in scores)
    assert all(score["trace_id"] == "abc123abc123abc123abc123abc123ab" for score in scores)


def test_promptopt_global_eval_cli_returns_nonzero_on_failed_gate(tmp_path):
    from scripts.promptopt_global_eval import main

    input_path = tmp_path / "cases.json"
    input_path.write_text(
        json.dumps(
            [
                {
                    "case_id": "only-one",
                    "baseline": {"items": [{"rule_id": "R1", "location": "1", "issue": "same"}]},
                    "candidate": {"items": []},
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "--input",
                str(input_path),
                "--prompt-variant",
                "bad",
                "--batch-id",
                "batch-2",
                "--output-json",
                str(tmp_path / "failed.json"),
                "--output-md",
                str(tmp_path / "failed.md"),
            ]
        )
        == 2
    )
