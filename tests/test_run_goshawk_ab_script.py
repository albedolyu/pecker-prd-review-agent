def test_goshawk_ab_parser_defaults_to_final_only_and_safe_compact_budget():
    from scripts.run_goshawk_ab import parse_args

    args = parse_args(["--workspace", "C:/workspace"])

    assert args.workspace == "C:/workspace"
    assert args.mode == "final-only"
    assert args.compact_chars == 25000
    assert args.record_langfuse is False


def test_goshawk_ab_parser_accepts_local_route_profile():
    from scripts.run_goshawk_ab import parse_args

    args = parse_args(
        [
            "--workspace",
            "C:/workspace",
            "--routes-file",
            "model_routes.pro_cli.yaml",
        ]
    )

    assert args.routes_file == "model_routes.pro_cli.yaml"


def test_goshawk_ab_parser_accepts_variant_order():
    from scripts.run_goshawk_ab import parse_args

    args = parse_args(
        [
            "--workspace",
            "C:/workspace",
            "--variant-order",
            "compact,full",
        ]
    )

    assert args.variant_order == "compact,full"


def test_goshawk_ab_variant_env_explicitly_controls_compaction():
    from scripts.run_goshawk_ab import variant_env

    assert variant_env("full", compact_chars=12345) == {
        "PECKER_GOSHAWK_COMPACT_WIKI": "0",
        "PECKER_GOSHAWK_WIKI_CHARS": "12345",
    }
    assert variant_env("compact", compact_chars=12345) == {
        "PECKER_GOSHAWK_COMPACT_WIKI": "1",
        "PECKER_GOSHAWK_WIKI_CHARS": "12345",
    }


def test_goshawk_ab_uses_candidate_trace_for_comparison_scores():
    from scripts.run_goshawk_ab import comparison_trace_id

    summary = {
        "baseline": {"trace": {"trace_id": "11111111111111111111111111111111"}},
        "candidate": {"trace": {"trace_id": "22222222222222222222222222222222"}},
    }

    assert comparison_trace_id(summary) == "22222222222222222222222222222222"


def test_goshawk_ab_normalizes_variant_order():
    from scripts.run_goshawk_ab import normalize_variant_order

    assert normalize_variant_order("compact,full") == ["compact", "full"]
    assert normalize_variant_order("full,compact") == ["full", "compact"]
    assert normalize_variant_order("") == ["full", "compact"]
