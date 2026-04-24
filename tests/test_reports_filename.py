"""P2 #4 (2026-04-24): reports.save_to_wiki 的 prd_name sanitize 回归测试。

背景:
api/routes/reports.py:101 `filename = f"评审记录-{req.prd_name}-..."` 之前没 sanitize
前端传的 prd_name。攻击路径: prd_name = "../../../../evil" → 文件落到 workspace 外面。

修复: 新增 _safe_prd_name helper,参照 _safe_reviewer 的做法过滤路径分隔符/通配符/点。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.routes.reports import _safe_prd_name


class TestSafePrdName:
    def test_strips_path_traversal(self):
        """../../ 模式 → 全部被替换为 _,不留 ..。"""
        result = _safe_prd_name("../../../../evil")
        assert ".." not in result
        assert "/" not in result
        assert "\\" not in result

    def test_strips_absolute_path(self):
        """Windows 绝对路径 C:\\ 也要打掉。"""
        result = _safe_prd_name("C:\\Windows\\evil.md")
        assert "\\" not in result
        assert ":" not in result

    def test_filename_stays_within_wiki_dir(self, tmp_path):
        """核心断言: 拼完 filename 后落点必须还在 wiki_dir 内部,不跑出去。"""
        wiki_dir = tmp_path / "workspace-test" / "wiki"
        wiki_dir.mkdir(parents=True)

        malicious_names = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32",
            "./../../root",
            "/absolute/path/evil",
        ]
        for bad in malicious_names:
            safe = _safe_prd_name(bad)
            filename = f"评审记录-{safe}-alice-20260424.md"
            full_path = (wiki_dir / filename).resolve()
            # resolve() 后的绝对路径必须仍在 wiki_dir 的子路径里
            assert str(full_path).startswith(str(wiki_dir.resolve())), (
                f"路径穿越未拦住: {bad} → {full_path}"
            )

    def test_normal_name_preserved(self):
        """正常 PRD 名基本保留(中文 / 数字 / 短横线)。"""
        result = _safe_prd_name("风鸟-诉前调解-v1")
        # 中文 + 短横线 + 字母数字都应保留
        assert "风鸟" in result
        assert "诉前调解" in result
        assert "v1" in result

    def test_empty_falls_back(self):
        """空值/纯空白 → unknown,不抛异常。"""
        assert _safe_prd_name("") == "unknown"
        assert _safe_prd_name(None) == "unknown"
        assert _safe_prd_name("   ") == "unknown"

    def test_length_capped(self):
        """超长 prd_name 截 50 字符,防撑爆文件名。"""
        long_name = "超长" * 100  # 200 字符
        result = _safe_prd_name(long_name)
        assert len(result) <= 50

    def test_no_leading_trailing_underscore(self):
        """首尾 _ 应去掉(美观)。"""
        result = _safe_prd_name("...abc...")
        assert not result.startswith("_")
        assert not result.endswith("_")
