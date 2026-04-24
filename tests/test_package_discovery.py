"""P1 #3 (2026-04-24): pyproject.toml 子包声明回归。

背景:
pyproject.toml 原先只有 py-modules (顶层单文件), packages 缺失 → pip install . 或
wheel 发布时 api/ review/ clients/ 全部漏装。dev 不踩坑因为走源码,但任何部署路径
(docker multi-stage wheel / pip install -e . 到 venv) 都会 ModuleNotFoundError。

修复: 加 packages = ["api", "api.routes", "review", "clients"]。
此测试两件事:
1. 声明的每个包真的可以 import (防止 typo)
2. pyproject.toml 的 packages 键存在且非空 (防止被人回滚)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestPackagesAreImportable:
    """每个 packages 里声明的子包必须能 import,否则 pip install 装出来的也跑不起来。"""

    def test_api_importable(self):
        import api  # noqa: F401

    def test_api_routes_importable(self):
        import api.routes  # noqa: F401
        from api.routes import review  # noqa: F401

    def test_review_importable(self):
        import review  # noqa: F401
        from review import worker, orchestration, prompting  # noqa: F401

    def test_clients_importable(self):
        import clients  # noqa: F401
        from clients import shared  # noqa: F401


class TestPyprojectDeclaration:
    """pyproject.toml packages 键的存在性 + 覆盖面断言。"""

    def test_packages_key_contains_core_packages(self):
        """防回滚: packages = [...] 里必须有 api / review / clients。"""
        try:
            import tomllib  # 3.11+
        except ImportError:
            import tomli as tomllib  # type: ignore

        root = Path(__file__).parent.parent
        with open(root / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)

        packages = data.get("tool", {}).get("setuptools", {}).get("packages", [])
        assert "api" in packages, "api 子包漏声明,pip install 会丢核心路由"
        assert "api.routes" in packages, "api.routes 漏声明"
        assert "review" in packages, "review 子包漏声明"
        assert "clients" in packages, "clients 子包漏声明"

    def test_tools_stays_in_py_modules(self):
        """tools 是顶层 tools.py 单文件,误放 packages 会让 setuptools 报错找不到目录。"""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore

        root = Path(__file__).parent.parent
        with open(root / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)

        setuptools_conf = data.get("tool", {}).get("setuptools", {})
        py_modules = setuptools_conf.get("py-modules", [])
        packages = setuptools_conf.get("packages", [])
        assert "tools" in py_modules, "tools.py 单文件应在 py-modules"
        assert "tools" not in packages, "tools 不是目录,不能进 packages"
