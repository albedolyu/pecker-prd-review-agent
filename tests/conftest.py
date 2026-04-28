"""Pytest fixtures shared by the local regression suite."""
from __future__ import annotations

import hashlib
import itertools
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import pytest


_TMP_COUNTER = itertools.count()
_TMP_RUN_ID = f"{os.getpid()}-{time.time_ns()}"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOCAL_TEMP_ROOT = _PROJECT_ROOT / ".tmp-pytest" / "python-temp" / _TMP_RUN_ID
_LOCAL_TEMP_ROOT.mkdir(parents=True, exist_ok=False)

for _name in ("TEMP", "TMP", "TMPDIR"):
    os.environ[_name] = str(_LOCAL_TEMP_ROOT)
os.environ["PECKER_TEST_TEMP_ROOT"] = str(_LOCAL_TEMP_ROOT)
_SITECUSTOMIZE_DIR = _PROJECT_ROOT / "tests" / "_sitecustomize"
os.environ["PYTHONPATH"] = (
    str(_SITECUSTOMIZE_DIR)
    if not os.environ.get("PYTHONPATH")
    else str(_SITECUSTOMIZE_DIR) + os.pathsep + os.environ["PYTHONPATH"]
)
tempfile.tempdir = str(_LOCAL_TEMP_ROOT)


def _safe_mkdtemp(suffix=None, prefix=None, dir=None):
    suffix = "" if suffix is None else str(suffix)
    prefix = "tmp" if prefix is None else str(prefix)
    base = Path(dir or _LOCAL_TEMP_ROOT)
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


@pytest.fixture
def tmp_path(request) -> Path:
    """Return a per-test temp dir without relying on platform temp ACLs.

    In the Windows Codex sandbox, pytest's built-in tmp_path can create
    tempfile-managed directories that become unreadable during the same session.
    The suite only needs an empty Path per test, so a repo-local ignored
    directory is more stable and keeps tests independent of the developer's
    global Temp ACL state.
    """
    digest = hashlib.sha1(request.node.nodeid.encode("utf-8")).hexdigest()[:16]
    idx = next(_TMP_COUNTER)
    path = _LOCAL_TEMP_ROOT / "tmp-path" / f"{idx:04d}-{digest}"
    path.mkdir(parents=True, exist_ok=False)
    return path
