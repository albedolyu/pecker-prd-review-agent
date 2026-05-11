from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_confidence_scoring_has_non_legacy_home():
    from review.confidence import compute_confidence

    assert compute_confidence("A") == 0.9
    assert compute_confidence("B") == 0.8
    assert compute_confidence("C") == 0.5
    assert compute_confidence("", is_supplement=True) == 0.32


def test_cuckoo_parser_keeps_compatibility_reexport_only():
    import cuckoo_parser
    from review import confidence

    assert cuckoo_parser.compute_confidence is confidence.compute_confidence
    assert cuckoo_parser.EVIDENCE_CONFIDENCE_BASE is confidence.EVIDENCE_CONFIDENCE_BASE


def test_hot_paths_do_not_import_confidence_from_legacy_parser():
    hot_paths = [
        PROJECT_ROOT / "review" / "worker.py",
        PROJECT_ROOT / "goshawk_advisor.py",
        PROJECT_ROOT / "review_fixer.py",
    ]

    for path in hot_paths:
        source = path.read_text(encoding="utf-8")
        assert "from cuckoo_parser import compute_confidence" not in source, path
