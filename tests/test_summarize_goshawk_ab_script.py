import json


def test_summarize_goshawk_ab_script_writes_json_and_markdown(tmp_path):
    from scripts.summarize_goshawk_ab import main

    (tmp_path / "run1.json").write_text(
        json.dumps(
            {
                "batch_id": "run1",
                "ab": {
                    "metrics": {
                        "compact_pass": True,
                        "input_token_savings_ratio": 0.4,
                        "elapsed_savings_ratio": 0.1,
                        "final_rule_jaccard": 1.0,
                        "final_signature_jaccard": 1.0,
                        "false_positive_delta": -1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "run2.json").write_text(
        json.dumps(
            {
                "batch_id": "run2",
                "ab": {
                    "metrics": {
                        "compact_pass": False,
                        "input_token_savings_ratio": 0.4,
                        "elapsed_savings_ratio": -0.2,
                        "final_rule_jaccard": 0.8,
                        "final_signature_jaccard": 0.8,
                        "false_positive_delta": 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    output_json = tmp_path / "summary.json"
    output_md = tmp_path / "summary.md"

    code = main(
        [
            "--input-dir",
            str(tmp_path),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--min-runs-for-canary",
            "2",
        ]
    )

    assert code == 2
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    markdown = output_md.read_text(encoding="utf-8")
    assert payload["recommendation"]["action"] == "keep_disabled"
    assert payload["summary"]["run_count"] == 2
    assert "Goshawk A/B Suite Summary" in markdown
    assert "keep_disabled" in markdown
