"""consistency_eval imports must not mutate test/runtime secrets.

Full pytest collection imports eval.route_eval.scorers.cuckoo_adapter, which
used to import eval.consistency_eval and reload .env with override=True. On a
developer machine with a real .env this replaced the API auth test secret before
tests/test_api_auth.py executed.
"""
from __future__ import annotations

import importlib
import os
import sys

import pytest


def test_scorer_import_does_not_override_existing_jwt_secret(monkeypatch):
    sentinel = "unit-test-jwt-secret-at-least-32-chars-sentinel"
    monkeypatch.setenv("PECKER_JWT_SECRET", sentinel)

    for name in (
        "eval.consistency_eval",
        "eval.route_eval.scorers.consistency_adapter",
        "eval.route_eval.scorers.cuckoo_adapter",
        "eval.route_eval.scorers",
    ):
        sys.modules.pop(name, None)

    importlib.import_module("eval.route_eval.scorers.cuckoo_adapter")

    if os.environ.get("PECKER_JWT_SECRET") != sentinel:
        pytest.fail("importing scorer modules must not override PECKER_JWT_SECRET")
