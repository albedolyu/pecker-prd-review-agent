"""Regression tests for importing eval consistency helpers safely."""
from __future__ import annotations

import importlib
import os
import sys


def test_importing_consistency_eval_does_not_load_dotenv(monkeypatch):
    """Pure helper imports must not mutate process auth env during pytest collection."""
    import dotenv

    sentinel = "unit-test-jwt-secret-at-least-32-chars-aaaa"
    calls = []

    def fake_load_dotenv(*args, **kwargs):
        calls.append((args, kwargs))
        os.environ["PECKER_JWT_SECRET"] = "dotenv-overrode-secret"
        return True

    monkeypatch.setenv("PECKER_JWT_SECRET", sentinel)
    monkeypatch.setattr(dotenv, "load_dotenv", fake_load_dotenv)
    sys.modules.pop("eval.consistency_eval", None)

    try:
        importlib.import_module("eval.consistency_eval")
    finally:
        sys.modules.pop("eval.consistency_eval", None)

    assert calls == []
    assert os.environ["PECKER_JWT_SECRET"] == sentinel
