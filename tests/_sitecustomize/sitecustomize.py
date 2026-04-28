"""Test-only tempfile compatibility for Python subprocesses.

Activated only when PECKER_TEST_TEMP_ROOT is set by tests/conftest.py.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path


_ROOT = os.environ.get("PECKER_TEST_TEMP_ROOT")

if _ROOT:
    _ROOT_PATH = Path(_ROOT)
    _ROOT_PATH.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(_ROOT_PATH)

    def _safe_mkdtemp(suffix=None, prefix=None, dir=None):
        suffix = "" if suffix is None else str(suffix)
        prefix = "tmp" if prefix is None else str(prefix)
        base = Path(dir or _ROOT_PATH)
        base.mkdir(parents=True, exist_ok=True)
        for _ in range(100):
            path = base / f"{prefix}{uuid.uuid4().hex[:12]}{suffix}"
            try:
                path.mkdir()
                return str(path)
            except FileExistsError:
                continue
        raise FileExistsError(f"could not create unique temp dir under {base}")

    class _SafeTemporaryDirectory:
        def __init__(self, suffix=None, prefix=None, dir=None, ignore_cleanup_errors=False):
            self.name = _safe_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)
            self._ignore_cleanup_errors = ignore_cleanup_errors

        def cleanup(self):
            shutil.rmtree(self.name, ignore_errors=self._ignore_cleanup_errors or True)

        def __enter__(self):
            return self.name

        def __exit__(self, exc_type, exc, tb):
            self.cleanup()
            return False

        def __del__(self):
            self.cleanup()

    tempfile.mkdtemp = _safe_mkdtemp
    tempfile.TemporaryDirectory = _SafeTemporaryDirectory
