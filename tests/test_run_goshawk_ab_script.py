def test_goshawk_ab_parser_defaults_to_final_only_and_safe_compact_budget():
    from scripts.run_goshawk_ab import parse_args

    args = parse_args(["--workspace", "C:/workspace"])

    assert args.workspace == "C:/workspace"
    assert args.mode == "final-only"
    assert args.compact_chars == 25000
    assert args.record_langfuse is False


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

