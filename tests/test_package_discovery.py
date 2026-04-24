"""P1 #3 (2026-04-24): pyproject.toml 子包声明的双层回归。

第一层(快,总是跑): 源码树内断言 packages/py-modules 键存在 + 可 import。
防止有人回滚改动或 typo。

第二层(慢,独立 pip install 真测): `pip install . --no-deps --target tmp` 后
用独立 python 子进程 + cwd 离开源码树 + PYTHONPATH 只含 tmp 目录, 断言关键
模块仍能 import。这才是 reviewer 2026-04-24 追问的"真实安装后 import"场景 —
源码树内 import 不能暴露 pyproject 漏项 (因为 cwd + sys.path 把源码树也纳入)。

背景:
第一版 fix 只加了 packages=[api, api.routes, review, clients] 就以为完事,
reviewer 复查跑了 pip install + 离源码树 import 后发现: agent_config 内部
from config 依然失败, review.orchestration 内部 from io_utils 失败,
api.routes.metrics 内部 from stability_metrics 失败. 暴露出三类漏:
(1) config 是子包但 packages 没列
(2) io_utils 是顶层单文件但 py-modules 没列
(3) stability_metrics 在 scripts/ 但 scripts package 没列 + 代码用 sys.path 黑魔法

第二版 (本次提交) 全列 47 个顶层 py-modules + packages 加 config/scripts +
metrics.py 改走标准 import 路径, 配合本文件第二层兜底.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


PROJECT_ROOT = Path(__file__).parent.parent


class TestPackagesAreImportable:
    """第一层 — 每个 packages 里声明的子包必须能 import。
    源码树内验证, 快 (<0.1s), 每次 pytest 都跑。"""

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

    def test_config_importable(self):
        """config/ 是子包, agent_config 内部依赖它 — 没声明就炸。"""
        import config  # noqa: F401
        from config import MODEL_TIERS  # noqa: F401

    def test_scripts_importable(self):
        """scripts/ 是子包, api.routes.metrics 依赖 stability_metrics — 没声明就炸。"""
        import scripts  # noqa: F401
        from scripts.stability_metrics import compute_metrics  # noqa: F401


class TestPyprojectDeclaration:
    """第一层 — pyproject.toml 键的存在性 + 覆盖面断言。防手滑回滚。"""

    def _load_pyproject(self) -> dict:
        try:
            import tomllib  # 3.11+
        except ImportError:
            import tomli as tomllib  # type: ignore
        with open(PROJECT_ROOT / "pyproject.toml", "rb") as f:
            return tomllib.load(f)

    def test_packages_key_contains_core_packages(self):
        """防回滚: packages 里必须有全部已知的子包。"""
        packages = self._load_pyproject()["tool"]["setuptools"]["packages"]
        for required in ["api", "api.routes", "review", "clients", "config", "scripts"]:
            assert required in packages, f"{required} 漏声明, pip install 会 404"

    def test_py_modules_covers_critical_shared(self):
        """防回滚: 被跨包引用的关键顶层 .py 必须在 py-modules 里。

        下面这些是 api/review/clients 实际 import 的, 漏一个 fresh install 就崩。
        """
        py_modules = self._load_pyproject()["tool"]["setuptools"]["py-modules"]
        for required in [
            "logger",       # api/stream.py + review/worker.py import
            "io_utils",     # review/orchestration.py + review/prompting.py import
            "agent_config", # run_session + api 主链路
            "models",       # api.routes.review import
            "tools",        # run_session 主链路
        ]:
            assert required in py_modules, f"{required} 漏声明 py-modules"

    def test_tools_stays_in_py_modules_not_packages(self):
        """tools 是 tools.py 单文件, 误放 packages 会让 setuptools 报错找不到目录。"""
        data = self._load_pyproject()
        py_modules = data["tool"]["setuptools"]["py-modules"]
        packages = data["tool"]["setuptools"]["packages"]
        assert "tools" in py_modules
        assert "tools" not in packages


# ========================================================================
# 第二层 — 真 pip install + 独立 python 子进程 import
# ========================================================================

_INSTALL_TARGET_MODULES = [
    # 纯标准库依赖,不需要装 fastapi/anthropic 等外部包,--no-deps 也能 import 成功
    "io_utils",                          # 顶层 py-modules
    "agent_config",                      # 内部 from config import * — 验证 config 子包
    "config",                            # 子包本身
    "config.base",                       # 子包内模块
    "scripts.stability_metrics",         # scripts 子包 + 内部纯标准库
]


def _pip_available() -> bool:
    """CI 和本地 pytest 都能跑 pip, 但保守做个探测。"""
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True, check=True, timeout=10,
        )
        return True
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


@pytest.mark.skipif(not _pip_available(), reason="pip 不可用")
class TestInstalledArtifactImports:
    """第二层 — 真装到临时目录 + 离开源码树 + 独立 python 子进程 import。

    只有这层能抓到 pyproject.toml 漏声明 — 源码树内 import 会被 cwd / sys.path
    污染, 假象看起来都 OK。reviewer 2026-04-24 就是靠这类测试抓到第一版 fix 没修透。

    单测成本 ~30-60s (pip install 加子进程 import), 整个测试类合并成一个 test
    避免重复装包; 本地第一次跑会稍慢, 之后 pip cache 会加速。
    """

    def test_install_and_import_from_outside_source_tree(self, tmp_path):
        install_target = tmp_path / "site"
        install_target.mkdir()

        # Step 1: pip install . --no-deps --target <tmp/site>
        # --no-deps 避免装 fastapi/pydantic 等外部依赖(本测试只验证本项目文件声明)
        result = subprocess.run(
            [
                sys.executable, "-m", "pip", "install", ".",
                "--no-deps",
                "--target", str(install_target),
                "--quiet",
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True, text=True,
            timeout=180,
        )
        assert result.returncode == 0, (
            f"pip install 失败:\nstdout={result.stdout}\nstderr={result.stderr}"
        )

        # Step 2: 在完全独立的 sandbox 目录下跑子进程, cwd 离开源码树
        # PYTHONPATH 只指向 install_target, 完全不继承父进程的源码树 sys.path
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        test_script = "; ".join(
            f"import {mod}" for mod in _INSTALL_TARGET_MODULES
        ) + "; print('OK')"

        clean_env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(install_target),
            # 保留系统基础, 清掉可能污染 sys.path 的变量
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),  # Windows 需要
            "TEMP": os.environ.get("TEMP", ""),
            "PECKER_JWT_SECRET": "unit-test-jwt-secret-at-least-32-chars",
            "PECKER_SIGNATURE_SECRET": "unit-test-signature-secret-32-chars",
        }
        result = subprocess.run(
            [sys.executable, "-c", test_script],
            cwd=str(sandbox),
            env=clean_env,
            capture_output=True, text=True,
            timeout=30,
        )

        assert result.returncode == 0, (
            f"安装后独立进程 import 失败 — 说明 pyproject.toml 漏装某个模块\n"
            f"执行: {test_script}\n"
            f"cwd: {sandbox}\n"
            f"PYTHONPATH: {install_target}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        assert "OK" in result.stdout, f"子进程未正常结束, stdout={result.stdout}"
