"""
shrike_review Gate 覆盖测试 (Round 6)

shrike 作为 push 前最后一道门禁,安全扫描的 false negative 最危险。
本文件验证 SECURITY_PATTERNS 能识别常见敏感信息 + check_report_completeness
/ check_id_consistency 的边界场景。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# SECURITY_PATTERNS coverage
# ============================================================

class TestSecurityPatterns:
    """验证 shrike 能识别各种敏感信息泄漏"""

    def test_api_key_sk_prefix(self, tmp_path):
        from shrike_review import _scan_file
        f = tmp_path / "leaked.md"
        # pattern 要求 sk- 后紧跟 20+ alphanumerics (不含 -),用裸 alphanumeric
        f.write_text("api_key = sk-01234567890abcdefABCDEFghij", encoding="utf-8")
        hits = _scan_file(str(f))
        assert any("API Key" in name for _, name, _ in hits), \
            "应识别 sk- 前缀的 API Key"

    def test_github_token(self, tmp_path):
        from shrike_review import _scan_file
        f = tmp_path / "ci.yml"
        f.write_text("GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz", encoding="utf-8")
        hits = _scan_file(str(f))
        assert any("GitHub Token" in name for _, name, _ in hits)

    def test_plaintext_password(self, tmp_path):
        from shrike_review import _scan_file
        f = tmp_path / "config.txt"
        f.write_text("password=supersecret123", encoding="utf-8")
        hits = _scan_file(str(f))
        assert any("明文密码" in name for _, name, _ in hits)

    def test_internal_ip_10(self, tmp_path):
        from shrike_review import _scan_file
        f = tmp_path / "doc.md"
        f.write_text("db host: 10.20.30.40 port 5432", encoding="utf-8")
        hits = _scan_file(str(f))
        assert any("内网 IP" in name for _, name, _ in hits)

    def test_internal_ip_192(self, tmp_path):
        from shrike_review import _scan_file
        f = tmp_path / "doc.md"
        f.write_text("router: 192.168.1.1", encoding="utf-8")
        hits = _scan_file(str(f))
        assert any("内网 IP" in name for _, name, _ in hits)

    def test_internal_ip_172_in_range(self, tmp_path):
        """172.16-31 是内网;172.15 和 172.32 不是,测边界。

        注: _scan_file 按行扫描且 re.search 只抓首个 match,所以两个 IP 分两行。
        这一行为本身是 shrike 的一个潜在 false negative (同一行多个敏感信息只报一次),
        已在 round-6 审计笔记里记录待修。
        """
        from shrike_review import _scan_file
        f = tmp_path / "doc.md"
        f.write_text("172.16.0.1\n172.31.255.254\n", encoding="utf-8")
        hits = _scan_file(str(f))
        ip_hits = [h for h in hits if "内网 IP" in h[1]]
        assert len(ip_hits) >= 2

    def test_internal_ip_172_out_of_range_not_hit(self, tmp_path):
        from shrike_review import _scan_file
        f = tmp_path / "doc.md"
        # 172.15 和 172.32 不在 16-31 范围内
        f.write_text("public 172.15.0.1 and 172.32.0.1", encoding="utf-8")
        hits = _scan_file(str(f))
        ip_hits = [h for h in hits if "内网 IP" in h[1]]
        assert len(ip_hits) == 0

    def test_db_connection_with_credentials(self, tmp_path):
        from shrike_review import _scan_file
        f = tmp_path / "env.txt"
        f.write_text("mongodb://admin:p4ss@db.internal/mydb", encoding="utf-8")
        hits = _scan_file(str(f))
        assert any("连接串" in name for _, name, _ in hits)

    def test_clean_file_no_hits(self, tmp_path):
        from shrike_review import _scan_file
        f = tmp_path / "clean.md"
        f.write_text("# 产品需求文档\n\n这里讨论了用户登录流程的设计。", encoding="utf-8")
        hits = _scan_file(str(f))
        assert hits == []

    def test_check_security_multiple_files(self, tmp_path):
        from shrike_review import check_security
        (tmp_path / "clean.md").write_text("# clean", encoding="utf-8")
        (tmp_path / "leak.md").write_text("sk-01234567890abcdefABCDEFghij", encoding="utf-8")
        result = check_security(str(tmp_path))
        assert result["passed"] is False
        assert len(result["details"]) >= 1
        assert any("API Key" in d["type"] for d in result["details"])

    def test_check_security_empty_dir_passes(self, tmp_path):
        from shrike_review import check_security
        empty = tmp_path / "empty"
        empty.mkdir()
        result = check_security(str(empty))
        assert result["passed"] is True
        assert result["details"] == []

    def test_check_security_nonexistent_dir_passes(self, tmp_path):
        """不存在的目录 → 空 scan_dirs → passed=True (0 hits)."""
        from shrike_review import check_security
        result = check_security(str(tmp_path / "does_not_exist"))
        assert result["passed"] is True


# ============================================================
# check_report_completeness
# ============================================================

class TestCheckReportCompleteness:
    def test_missing_output_dir(self, tmp_path):
        from shrike_review import check_report_completeness
        result = check_report_completeness(str(tmp_path / "missing"))
        assert result["passed"] is False
        assert "不存在" in result["details"][0]

    def test_no_report_file(self, tmp_path):
        from shrike_review import check_report_completeness
        result = check_report_completeness(str(tmp_path))
        assert result["passed"] is False
        assert any("找不到" in d for d in result["details"])

    def test_report_with_all_sections(self, tmp_path):
        from shrike_review import check_report_completeness, REQUIRED_SECTIONS
        report = tmp_path / "PRD_改动报告_20260416.md"
        # 写一份包含所有必需章节的报告
        content = "\n\n".join(f"## {s}\n内容..." for s in REQUIRED_SECTIONS)
        report.write_text(content, encoding="utf-8")
        result = check_report_completeness(str(tmp_path))
        assert result["passed"] is True, f"details={result['details']}"

    def test_report_missing_one_section(self, tmp_path):
        from shrike_review import check_report_completeness, REQUIRED_SECTIONS
        report = tmp_path / "PRD_改动报告_20260416.md"
        # 漏掉第一个必需章节
        sections = REQUIRED_SECTIONS[1:]
        content = "\n\n".join(f"## {s}\n内容..." for s in sections)
        report.write_text(content, encoding="utf-8")
        result = check_report_completeness(str(tmp_path))
        assert result["passed"] is False
        assert len(result["details"]) >= 1

    def test_picks_latest_report_by_filename_sort(self, tmp_path):
        """有多份报告时应选日期最新的 (文件名字典序)."""
        from shrike_review import check_report_completeness, REQUIRED_SECTIONS
        older = tmp_path / "PRD_改动报告_20260101.md"
        newer = tmp_path / "PRD_改动报告_20260416.md"
        older.write_text("incomplete", encoding="utf-8")
        newer.write_text(
            "\n\n".join(f"## {s}\n内容..." for s in REQUIRED_SECTIONS),
            encoding="utf-8",
        )
        result = check_report_completeness(str(tmp_path))
        # 用 newer(完整的),所以 passed=True
        assert result["passed"] is True


# ============================================================
# check_id_consistency
# ============================================================

class TestCheckIdConsistency:
    def test_missing_output_dir(self, tmp_path):
        from shrike_review import check_id_consistency
        result = check_id_consistency(str(tmp_path / "missing"))
        assert result["passed"] is False

    def test_consistent_ids(self, tmp_path):
        from shrike_review import check_id_consistency
        (tmp_path / "PRD_改动报告_20260416.md").write_text("R-001 R-002 R-003", encoding="utf-8")
        (tmp_path / "PRD_差异报告_20260416.md").write_text("R-001 R-002 R-003", encoding="utf-8")
        (tmp_path / "PRD_交互记录_20260416.md").write_text("R-001 R-002 R-003", encoding="utf-8")
        result = check_id_consistency(str(tmp_path))
        assert result["passed"] is True

    def test_id_missing_from_diff(self, tmp_path):
        from shrike_review import check_id_consistency
        (tmp_path / "PRD_改动报告_20260416.md").write_text("R-001 R-002 R-003", encoding="utf-8")
        (tmp_path / "PRD_差异报告_20260416.md").write_text("R-001 R-002", encoding="utf-8")
        result = check_id_consistency(str(tmp_path))
        assert result["passed"] is False
        assert any("R-003" in d for d in result["details"])
