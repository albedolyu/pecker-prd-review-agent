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


@pytest.mark.asyncio
async def test_save_to_wiki_sanitizes_frontmatter_and_log_metadata(monkeypatch, tmp_path):
    """导出报告的元数据必须使用清洗后的 PRD 名和评审人,避免换行注入。"""
    from api.routes import reports

    ws_dir = tmp_path / "workspace-alpha"
    monkeypatch.setattr(reports, "get_workspace_dir", lambda _workspace: ws_dir, raising=True)
    monkeypatch.setattr(reports, "require_workspace_access", lambda *_args, **_kwargs: None, raising=True)

    req = reports.SaveReviewRequest(
        prd_name="demo\nmalicious: true",
        report_markdown="## 正文\n报告内容",
        items_count=1,
    )

    resp = await reports.save_to_wiki(
        "workspace-alpha",
        req,
        user={"reviewer": "alice\nrole: admin"},
    )

    saved = (ws_dir / "wiki" / resp["filename"]).read_text(encoding="utf-8")
    log_text = (ws_dir / "wiki" / "log.md").read_text(encoding="utf-8")

    metadata_text = saved.split("## 正文", 1)[0] + log_text
    assert "malicious: true" not in metadata_text
    assert "role: admin" not in metadata_text


@pytest.mark.asyncio
async def test_save_to_wiki_redacts_secrets_from_filename_and_metadata(monkeypatch, tmp_path):
    """导出报告的文件名和元数据不能暴露误填进 PRD 名/评审人的 API key。"""
    from api.routes import reports

    fake_key = "sk-01234567890abcdefABCDEFghij"
    ws_dir = tmp_path / "workspace-alpha"
    monkeypatch.setattr(reports, "get_workspace_dir", lambda _workspace: ws_dir, raising=True)
    monkeypatch.setattr(reports, "require_workspace_access", lambda *_args, **_kwargs: None, raising=True)

    req = reports.SaveReviewRequest(
        prd_name=f"demo {fake_key}",
        report_markdown="## 正文\n报告内容",
        items_count=1,
        peck_label=f"高风险 {fake_key}",
    )

    resp = await reports.save_to_wiki(
        "workspace-alpha",
        req,
        user={"reviewer": f"alice {fake_key}"},
    )

    saved = (ws_dir / "wiki" / resp["filename"]).read_text(encoding="utf-8")
    log_text = (ws_dir / "wiki" / "log.md").read_text(encoding="utf-8")
    metadata_text = saved.split("## 正文", 1)[0] + log_text + resp["filename"]

    assert fake_key not in metadata_text
    assert "[REDACTED_SECRET]" in metadata_text


@pytest.mark.asyncio
async def test_save_to_wiki_redacts_secrets_from_report_body(monkeypatch, tmp_path):
    """保存到 wiki 的报告正文也要脱敏,避免 PM 误把 API key 写进报告。"""
    from api.routes import reports

    fake_key = "sk-01234567890abcdefABCDEFghij"
    ws_dir = tmp_path / "workspace-alpha"
    monkeypatch.setattr(reports, "get_workspace_dir", lambda _workspace: ws_dir, raising=True)
    monkeypatch.setattr(reports, "require_workspace_access", lambda *_args, **_kwargs: None, raising=True)

    req = reports.SaveReviewRequest(
        prd_name="demo",
        report_markdown=f"## 正文\n供应商错误: Authorization: Bearer {fake_key}",
        items_count=1,
    )

    resp = await reports.save_to_wiki(
        "workspace-alpha",
        req,
        user={"reviewer": "alice"},
    )

    saved = (ws_dir / "wiki" / resp["filename"]).read_text(encoding="utf-8")

    assert fake_key not in saved
    assert "Authorization: Bearer [REDACTED_SECRET]" in saved


@pytest.mark.asyncio
async def test_save_to_wiki_redacts_secret_from_response_path(monkeypatch, tmp_path):
    """响应 path 也不能暴露 workspace 目录里误带的密钥。"""
    from api.routes import reports

    fake_key = "sk-01234567890abcdefABCDEFghij"
    ws_dir = tmp_path / f"workspace-{fake_key}"
    monkeypatch.setattr(reports, "get_workspace_dir", lambda _workspace: ws_dir, raising=True)
    monkeypatch.setattr(reports, "require_workspace_access", lambda *_args, **_kwargs: None, raising=True)

    req = reports.SaveReviewRequest(
        prd_name="demo",
        report_markdown="## 正文\n报告内容",
        items_count=1,
    )

    resp = await reports.save_to_wiki(
        "workspace-alpha",
        req,
        user={"reviewer": "alice"},
    )

    assert fake_key not in resp["path"]
    assert "[REDACTED_SECRET]" in resp["path"]


@pytest.mark.asyncio
async def test_save_to_wiki_redacts_secret_from_error_detail(monkeypatch, tmp_path):
    """保存失败的 500 detail 也要脱敏,避免底层路径/异常带出密钥。"""
    from fastapi import HTTPException
    from api.routes import reports

    fake_key = "sk-01234567890abcdefABCDEFghij"
    ws_dir = tmp_path / "workspace-alpha"
    monkeypatch.setattr(reports, "get_workspace_dir", lambda _workspace: ws_dir, raising=True)
    monkeypatch.setattr(reports, "require_workspace_access", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        reports.os,
        "replace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(f"disk full {fake_key}")),
        raising=True,
    )

    req = reports.SaveReviewRequest(
        prd_name="demo",
        report_markdown="## 正文\n报告内容",
        items_count=1,
    )

    with pytest.raises(HTTPException) as exc:
        await reports.save_to_wiki(
            "workspace-alpha",
            req,
            user={"reviewer": "alice"},
        )

    assert exc.value.status_code == 500
    assert fake_key not in exc.value.detail
    assert "[REDACTED_SECRET]" in exc.value.detail


@pytest.mark.asyncio
async def test_save_to_wiki_cleans_temp_file_when_replace_fails(monkeypatch, tmp_path):
    """os.replace 澶辫触鏃朵笉搴旀妸 .report_*.tmp 閬楃暀鍦?wiki 鐩綍銆?"""
    from fastapi import HTTPException
    from api.routes import reports

    ws_dir = tmp_path / "workspace-alpha"
    monkeypatch.setattr(reports, "get_workspace_dir", lambda _workspace: ws_dir, raising=True)
    monkeypatch.setattr(reports, "require_workspace_access", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        reports.os,
        "replace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("replace failed")),
        raising=True,
    )

    req = reports.SaveReviewRequest(
        prd_name="demo",
        report_markdown="## 姝ｆ枃\n鎶ュ憡鍐呭",
        items_count=1,
    )

    with pytest.raises(HTTPException):
        await reports.save_to_wiki(
            "workspace-alpha",
            req,
            user={"reviewer": "alice"},
        )

    leftovers = list((ws_dir / "wiki").glob(".report_*.tmp"))
    assert leftovers == []


@pytest.mark.asyncio
async def test_download_report_rejects_non_markdown_files(monkeypatch, tmp_path):
    """报告下载入口只应服务 Markdown 报告,不能顺手暴露 output 下的其他文件。"""
    from fastapi import HTTPException
    from api.routes import reports

    ws_dir = tmp_path / "workspace-alpha"
    output_dir = ws_dir / "output"
    output_dir.mkdir(parents=True)
    (output_dir / "debug.json").write_text('{"secret":"internal"}', encoding="utf-8")
    monkeypatch.setattr(reports, "get_workspace_dir", lambda _workspace: ws_dir, raising=True)
    monkeypatch.setattr(reports, "require_workspace_access", lambda *_args, **_kwargs: None, raising=True)

    with pytest.raises(HTTPException) as exc:
        await reports.download_report(
            "workspace-alpha",
            filename="debug.json",
            user={"reviewer": "alice"},
        )

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_download_report_rejects_markdown_outside_report_prefix(monkeypatch, tmp_path):
    """下载入口应和 list_reports 保持同一白名单,避免暴露 output 下的杂项 Markdown。"""
    from fastapi import HTTPException
    from api.routes import reports

    ws_dir = tmp_path / "workspace-alpha"
    output_dir = ws_dir / "output"
    output_dir.mkdir(parents=True)
    (output_dir / "operator-notes.md").write_text("internal notes", encoding="utf-8")
    monkeypatch.setattr(reports, "get_workspace_dir", lambda _workspace: ws_dir, raising=True)
    monkeypatch.setattr(reports, "require_workspace_access", lambda *_args, **_kwargs: None, raising=True)

    with pytest.raises(HTTPException) as exc:
        await reports.download_report(
            "workspace-alpha",
            filename="operator-notes.md",
            user={"reviewer": "alice"},
        )

    assert exc.value.status_code == 400
