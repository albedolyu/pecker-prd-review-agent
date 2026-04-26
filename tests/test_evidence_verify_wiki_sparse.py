"""2026-04-24 P0 修复:evidence_verify.py 对"无 wiki 上下文 workspace"走宽松模式。

背景:
原逻辑 A 类依据一律检查 wiki 目录,找不到 [[页面]] 引用就硬 retract。模板型 /
新业务 / 跨部门引用 PRD 的 workspace 本来就没 wiki 内容,导致 100% A 类依据
被撤回。侵权软件模板 PRD 跑一次产出从 ~17 条被 evidence verify 裁到 7 条,
其中 5 条因"A 类依据未包含 [[wiki 页面]] 引用"被撤回,构成 pipeline 80% 吞
没率的重要一环。

修复:加 `_is_wiki_sparse()` 判定,workspace wiki 目录业务 md 文件 < 3 时,
A 类依据走宽松模式:不 retract,改 verified_with_caveat,保留 item 继续下游。
B/C 类逻辑不变。

测试矩阵:
- wiki_sparse 判定:无 wiki 目录 / 空 wiki 目录 / 只有元文件(log/index/README)
  / 业务 md 文件 < 3 都应判 sparse
- wiki_rich 判定:≥ 3 个业务 md 文件应判 rich
- A 类在 sparse 模式下不 retract,改 verified_with_caveat
- A 类在 rich 模式下维持原行为(找不到 wiki 页面 → retract)
- B / C 类逻辑不受 wiki_sparse 影响
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from review.evidence_verify import (
    _is_pecker_generated,
    _is_wiki_sparse,
    verify_evidence,
)


@pytest.fixture(autouse=True)
def _disable_external_canonical(monkeypatch):
    # 2026-04-27 P0-A: _is_wiki_sparse / _build_wiki_index 现在走 iter_wiki_files
    # (含外挂 canonical), 但本文件测的是纯 workspace 行为. PM 机器默认外挂路径
    # 存在 → 测试被污染. 显式 env="" disable 外挂.
    monkeypatch.setenv("PECKER_EXTERNAL_CANONICAL_WIKI", "")


# ============================================================
# _is_wiki_sparse 判定
# ============================================================


class TestIsWikiSparse:
    def test_no_wiki_directory_is_sparse(self, tmp_path):
        """wiki 目录不存在 → sparse."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        assert _is_wiki_sparse(str(workspace / "wiki")) is True

    def test_empty_wiki_directory_is_sparse(self, tmp_path):
        """wiki 目录存在但空 → sparse."""
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        assert _is_wiki_sparse(str(wiki)) is True

    def test_only_meta_files_is_sparse(self, tmp_path):
        """只有 log.md / index.md / README.md / TOC.md 等元文件 → sparse."""
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        for fn in ("log.md", "index.md", "README.md", "TOC.md"):
            (wiki / fn).write_text("meta", encoding="utf-8")
        assert _is_wiki_sparse(str(wiki)) is True

    def test_one_business_md_is_sparse(self, tmp_path):
        """< 3 个业务 md → sparse."""
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "log.md").write_text("meta", encoding="utf-8")
        (wiki / "业务页面1.md").write_text("biz", encoding="utf-8")
        assert _is_wiki_sparse(str(wiki)) is True

    def test_three_business_md_is_rich(self, tmp_path):
        """≥ 3 个业务 md → rich."""
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "log.md").write_text("meta", encoding="utf-8")
        for i in range(3):
            (wiki / f"业务页面{i}.md").write_text("biz", encoding="utf-8")
        assert _is_wiki_sparse(str(wiki)) is False


# ============================================================
# verify_evidence 在 sparse/rich 模式下的行为
# ============================================================


@pytest.fixture
def sparse_workspace(tmp_path):
    """模拟模板型 workspace: 没有业务 wiki 内容."""
    ws = tmp_path / "workspace-sparse"
    ws.mkdir()
    (ws / "wiki").mkdir()
    # 只放一个 log.md 元文件
    (ws / "wiki" / "log.md").write_text("meta only", encoding="utf-8")
    (ws / "review-rules").mkdir()
    return ws


@pytest.fixture
def rich_workspace(tmp_path):
    """正常业务 workspace: 有多个业务 wiki 页 (文件名用无关键词避免 _a_class_item
    的 evidence 意外模糊匹配)."""
    ws = tmp_path / "workspace-rich"
    ws.mkdir()
    wiki = ws / "wiki"
    wiki.mkdir()
    # 用完全与 _a_class_item evidence 无重叠的文件名
    for n in ("xxx-alpha.md", "yyy-beta.md", "zzz-gamma.md", "log.md"):
        (wiki / n).write_text("# biz\n内容", encoding="utf-8")
    (ws / "review-rules").mkdir()
    return ws


def _a_class_item():
    """生成一条 A 类依据的 item,依据里不含 [[wiki 页面]] 引用."""
    return {
        "id": "R-001",
        "evidence_type": "A",
        "evidence_content": "PRD 第一行:「# 风鸟新增侵权软件」",  # 不含 [[wiki]]
        "confidence_score": 0.6,
        "issue": "文件标题未替换",
    }


def _b_class_item():
    return {
        "id": "R-002",
        "evidence_type": "B",
        "evidence_content": "规则 V-05 信息自洽性",
        "confidence_score": 0.6,
        "issue": "字段在多处命名不一致",
    }


class TestSparseModeRelaxesA:
    def test_a_class_not_retracted_when_sparse(self, sparse_workspace):
        """核心修复:A 类依据在 sparse workspace 下不被 retract."""
        items = [_a_class_item()]
        result = verify_evidence(items, str(sparse_workspace))
        assert len(result) == 1
        item = result[0]
        assert item["status"] == "VERIFIED", (
            f"sparse 模式下 A 类不应 RETRACTED, 实际 status={item['status']}, "
            f"reason={item.get('verification_reason')}"
        )
        assert item["verification_status"] == "verified_with_caveat"
        assert item["verification_details"]["reason_code"] == "A_wiki_sparse_relaxed"

    def test_a_class_confidence_not_zeroed(self, sparse_workspace):
        """sparse 模式下 confidence 不被砍到 gate 以下 (允许小幅降权)."""
        items = [_a_class_item()]  # 初始 0.6
        result = verify_evidence(items, str(sparse_workspace))
        # 允许略微降权但不能到 0 或 < 0.5 (基本 gate 阈值)
        assert result[0]["confidence_score"] >= 0.5


class TestRichModeSoftDegradesA:
    def test_a_class_not_retracted_when_rich_and_no_wiki_match(self, rich_workspace):
        """2026-04-24 P0 放宽: rich workspace 下 A 类 wiki 未命中也不再 retract,
        改降权保留 (reason_code=A_wiki_page_not_found_weak).

        原行为: retract → 抹杀合理 item. 新行为: confidence × 0.7 保留,PM 复核.
        """
        items = [_a_class_item()]  # 依据里没提到任何 wiki 文件名
        result = verify_evidence(items, str(rich_workspace))
        item = result[0]
        # 关键: 不再 retract
        assert item["status"] == "VERIFIED", (
            f"A 类 wiki 未命中不应 RETRACTED, 应降权保留. "
            f"实际 status={item['status']}, reason={item.get('verification_reason')}"
        )
        assert item["verification_status"] == "verified_with_caveat"
        assert item["verification_details"]["reason_code"] == "A_wiki_page_not_found_weak"
        # confidence 应被降权到 0.7 倍 (0.6 * 0.7 = 0.42)
        assert abs(item["confidence_score"] - 0.42) < 0.01, (
            f"confidence 应降权到 0.42, 实际 {item['confidence_score']}"
        )

    def test_a_class_verified_when_rich_and_wiki_matches(self, rich_workspace):
        """rich workspace + 能匹配到 wiki 页面 → VERIFIED."""
        items = [{
            "id": "R-010",
            "evidence_type": "A",
            # evidence 里提到 wiki 文件名"xxx-alpha"(rich_workspace fixture 有这个文件)
            "evidence_content": "参见 [[xxx-alpha]] 文档",
            "confidence_score": 0.6,
            "issue": "引用现有 wiki",
        }]
        result = verify_evidence(items, str(rich_workspace))
        item = result[0]
        assert item["status"] == "VERIFIED"
        assert item["verification_status"] == "verified"
        assert item["verification_details"]["found"] is True
        # confidence 不变
        assert item["confidence_score"] == 0.6


class TestBClassUnaffected:
    def test_b_class_logic_same_in_sparse(self, sparse_workspace):
        """B 类依据不受 wiki_sparse 影响,逻辑保持原有."""
        items = [_b_class_item()]
        result = verify_evidence(items, str(sparse_workspace))
        # B 类: review-rules 找不到 → retract (和原行为一致)
        item = result[0]
        assert item["status"] == "RETRACTED"
        assert item["verification_details"]["reason_code"] == "B_missing_rule"


class TestPeckerGeneratedDetection:
    """2026-04-24 新增:wiki 自回归偏见修复 — 识别 pecker 自生成文件并从
    权威源中剔除,防止循环引用(用 pecker 上次输出当权威验证 pecker 本次输出)。"""

    def test_pecker_generated_with_sources_zero(self, tmp_path):
        """frontmatter 里 sources: 0 的 wiki 文件被判为 pecker 自生成."""
        f = tmp_path / "概念-侵权软件.md"
        f.write_text(
            "---\n"
            "source: prd/某.md\n"
            "tags: [domain/x, status/已验证]\n"
            "sources: 0\n"
            "---\n\n"
            "# 概念\n内容...",
            encoding="utf-8",
        )
        assert _is_pecker_generated(str(f)) is True

    def test_pm_curated_without_sources_zero(self, tmp_path):
        """没有 sources: 0 字段(PM 手工维护) → 非 pecker 生成."""
        f = tmp_path / "pm维护页.md"
        f.write_text(
            "---\n"
            "author: albedolyu\n"
            "tags: [domain/x]\n"
            "---\n\n"
            "# PM 写的业务 wiki\n",
            encoding="utf-8",
        )
        assert _is_pecker_generated(str(f)) is False

    def test_pm_curated_with_sources_positive(self, tmp_path):
        """sources > 0 (PM 引用了外部来源) → 非 pecker 生成."""
        f = tmp_path / "有来源.md"
        f.write_text(
            "---\n"
            "sources: 3\n"
            "---\n\n"
            "content",
            encoding="utf-8",
        )
        assert _is_pecker_generated(str(f)) is False

    def test_missing_file_safe(self, tmp_path):
        """文件不存在不应抛异常."""
        assert _is_pecker_generated(str(tmp_path / "不存在.md")) is False

    def test_wiki_sparse_ignores_pecker_generated(self, tmp_path):
        """核心修复:wiki 有 5 个 pecker 自生成 md 仍被判 sparse(真实业务 md = 0)."""
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        # 5 个自生成文件(sources: 0)
        for i in range(5):
            (wiki / f"pecker-生成-{i}.md").write_text(
                "---\nsources: 0\n---\n内容", encoding="utf-8"
            )
        # sources: 0 的 wiki 不算业务上下文
        assert _is_wiki_sparse(str(wiki)) is True

    def test_wiki_rich_needs_pm_curated(self, tmp_path):
        """混合场景: 3 个 PM 维护 + 多个 pecker 生成 → rich(以 PM 维护计数)."""
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        # 3 个 PM 手工维护(无 sources: 0)
        for i in range(3):
            (wiki / f"pm-{i}.md").write_text("---\nauthor: pm\n---\n内容", encoding="utf-8")
        # 另加 2 个 pecker 生成(不应计入 rich)
        for i in range(2):
            (wiki / f"pecker-{i}.md").write_text("---\nsources: 0\n---\n内容", encoding="utf-8")
        assert _is_wiki_sparse(str(wiki)) is False


class TestMixedItems:
    def test_mixed_a_b_c_items_in_sparse(self, sparse_workspace):
        """混合 A/B/C items,只 A 走宽松,B/C 逻辑不变."""
        items = [
            _a_class_item(),  # A 类,sparse 模式 verified_with_caveat
            _b_class_item(),  # B 类,没规则文件 retracted
            {
                "id": "R-003",
                "evidence_type": "C",
                "evidence_content": "未经验证的推测",  # 无"待确定"
                "confidence_score": 0.5,
                "issue": "推测问题",
            },
        ]
        result = verify_evidence(items, str(sparse_workspace))
        assert len(result) == 3
        # A: verified_with_caveat
        assert result[0]["verification_status"] == "verified_with_caveat"
        assert result[0]["verification_details"]["reason_code"] == "A_wiki_sparse_relaxed"
        # B: retracted (不受 sparse 影响)
        assert result[1]["status"] == "RETRACTED"
        # C: verified_with_caveat + 自动补标
        assert result[2]["verification_status"] == "verified_with_caveat"
        assert "待确定" in result[2]["evidence_content"]
