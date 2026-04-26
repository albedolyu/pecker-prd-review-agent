"""P0-A 防回归 (2026-04-27): evidence_verify 跟 content_loader 同步外挂 canonical wiki.

背景:
2026-04-27 calibration 报告 (docs/calibration_full_chain_2026_04_27.md)
verdict 显示 wiki canonical 接通 PARTIAL — content_loader.load_wiki_pages
已修, worker prompt 真拿到 49 canonical page (`[并行评审] Wiki: 49 页`),
但 evidence_verify 走另一条 wiki path: jsonl 里 `wiki_mode: sparse` +
`authority_distribution: {}` 空 dict, 0 canonical 进 evidence pool.

根因: evidence_verify._build_wiki_index / _is_wiki_sparse 和
funnel_telemetry.get_wiki_telemetry 都用 `glob(workspace/wiki/*.md)`
自己扫, 完全不走 PECKER_EXTERNAL_CANONICAL_WIKI 外挂. workspace 本身
sparse 时即使外挂 49 page 已加载, evidence_verify 仍判 sparse → 触发
宽松模式 → A 类降权保留掩盖真 fail + LLM NLI 永不触发.

修法 (2026-04-27 P0-A):
1. content_loader 加 iter_wiki_files(wiki_dir) 单点 source-of-truth,
   合并语义跟 load_wiki_pages 一致 (外挂在先 / workspace 在后, 同 basename
   workspace 优先).
2. evidence_verify._build_wiki_index 和 _is_wiki_sparse 改走 iter_wiki_files.
3. funnel_telemetry.get_wiki_telemetry 改走 iter_wiki_files.

本测试不 mock 内部 wiki 加载, 用 tmp_path 真模拟"workspace local 3 个 contextual
+ 外挂 5 个 canonical" 场景, 端到端验证 evidence_verify 和 funnel_telemetry
真看见外挂 canonical.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from review.evidence_verify import (
    _build_wiki_index,
    _is_wiki_sparse,
    verify_evidence,
)
from review.funnel_telemetry import get_wiki_telemetry


# ============================================================
# fixture: 模拟 calibration 场景 (workspace local 3 contextual + 外挂 5 canonical)
# ============================================================


@pytest.fixture
def workspace_with_external_canonical(tmp_path, monkeypatch):
    """模拟真实 calibration 场景:
    - 外挂 canonical wiki: 5 个 page (含子目录, 跟风鸟代码库结构一致)
    - workspace local wiki: 3 个 contextual page (业务上下文)
    返回 workspace 路径.
    """
    # 外挂 canonical
    ext = tmp_path / "external_canonical"
    ext.mkdir()
    (ext / "concepts").mkdir()
    (ext / "modules").mkdir()
    # 顶层 index/log 跳过, 不计入
    (ext / "index.md").write_text("idx", encoding="utf-8")
    (ext / "log.md").write_text("log", encoding="utf-8")
    # canonical pages (有 sources>=1 + authority: canonical)
    for i in range(2):
        (ext / "concepts" / f"concept_{i}.md").write_text(
            f"---\nsources: 3\nauthority: canonical\nverified_by: 数据团队\n---\n# concept {i}\n",
            encoding="utf-8",
        )
    for i in range(3):
        (ext / "modules" / f"module_{i}.md").write_text(
            f"---\nsources: 2\nauthority: canonical\nverified_by: 工程团队\n---\n# module {i}\n",
            encoding="utf-8",
        )

    # workspace local
    ws = tmp_path / "workspace"
    wiki = ws / "wiki"
    wiki.mkdir(parents=True)
    for i in range(3):
        (wiki / f"local_业务{i}.md").write_text(
            f"---\nsources: 1\nauthority: contextual\n---\n# local {i}\n",
            encoding="utf-8",
        )

    monkeypatch.setenv("PECKER_EXTERNAL_CANONICAL_WIKI", str(ext))
    return str(ws)


# ============================================================
# 修法验证: _build_wiki_index 真拿到外挂 canonical
# ============================================================


class TestBuildWikiIndexCanonicalSync:
    """_build_wiki_index 应该枚举到外挂 + workspace 全部 page."""

    def test_index_includes_external_canonical(self, workspace_with_external_canonical):
        """_build_wiki_index 真拿到外挂 5 canonical + workspace 3 contextual = 8 entry."""
        ws = workspace_with_external_canonical
        wiki_dir = os.path.join(ws, "wiki")
        index = _build_wiki_index(wiki_dir)

        # 5 外挂 canonical (按 basename 去重) + 3 workspace local = 8
        assert len(index) == 8, (
            f"期望 8 entry (5 ext canonical + 3 ws contextual), 实际 {len(index)}"
        )

        # 抽样验证: 外挂 canonical 真在 index 里 (key 是 basename)
        canonical_keys = [k for k in index if "concept_" in k or "module_" in k]
        assert len(canonical_keys) == 5, (
            f"期望 5 canonical key, 实际 {len(canonical_keys)} — "
            f"说明 _build_wiki_index 没读外挂 canonical wiki"
        )

        # workspace local 也在
        local_keys = [k for k in index if "local_业务" in k]
        assert len(local_keys) == 3

    def test_index_skips_external_meta_files(self, workspace_with_external_canonical):
        """外挂里的 index.md / log.md 跳过, 不进 index."""
        ws = workspace_with_external_canonical
        wiki_dir = os.path.join(ws, "wiki")
        index = _build_wiki_index(wiki_dir)

        for k in index:
            # k 是 basename (含 .md), 元文件不应在
            assert k not in ("index.md", "log.md", "_scratchpad.md", "README.md", "TOC.md"), (
                f"元文件 {k} 不应进 index"
            )


# ============================================================
# 修法验证: _is_wiki_sparse 接通外挂后判 rich
# ============================================================


class TestIsWikiSparseCanonicalSync:
    """workspace 本身只有 < 3 业务 md 但外挂 5 canonical 时, 应判 rich."""

    def test_sparse_workspace_with_canonical_external_is_rich(
        self, tmp_path, monkeypatch,
    ):
        """workspace 0 business md, 外挂 5 canonical → rich (因为外挂被算入)."""
        ext = tmp_path / "ext"
        ext.mkdir()
        for i in range(5):
            (ext / f"page_{i}.md").write_text(
                f"---\nsources: 2\nauthority: canonical\n---\n", encoding="utf-8",
            )

        ws = tmp_path / "workspace"
        wiki = ws / "wiki"
        wiki.mkdir(parents=True)
        # workspace 只有元文件, 0 business md
        (wiki / "log.md").write_text("log", encoding="utf-8")
        (wiki / "index.md").write_text("idx", encoding="utf-8")

        monkeypatch.setenv("PECKER_EXTERNAL_CANONICAL_WIKI", str(ext))
        # P0-A 修法: 接通外挂 → rich
        assert _is_wiki_sparse(str(wiki)) is False

    def test_sparse_when_no_external_and_no_local(self, tmp_path, monkeypatch):
        """无外挂 + workspace 也空 → 仍 sparse (兜底语义不变)."""
        ws = tmp_path / "workspace"
        wiki = ws / "wiki"
        wiki.mkdir(parents=True)
        monkeypatch.setenv("PECKER_EXTERNAL_CANONICAL_WIKI", "")
        assert _is_wiki_sparse(str(wiki)) is True


# ============================================================
# 修法验证: get_wiki_telemetry 的 authority_distribution 含 canonical
# ============================================================


class TestGetWikiTelemetryCanonicalSync:
    """authority_distribution 不再空 dict, 真含 canonical 计数."""

    def test_authority_distribution_includes_canonical(
        self, workspace_with_external_canonical,
    ):
        """workspace local 3 contextual + 外挂 5 canonical → distribution 真有 canonical."""
        ws = workspace_with_external_canonical
        out = get_wiki_telemetry(ws)

        # P0-A 修法核心断言: authority_distribution 不再空 dict
        assert out["authority_distribution"], (
            "authority_distribution 应非空 dict — "
            "P0-A 修法没生效, evidence_verify 没接外挂 canonical"
        )
        # 5 个 canonical 真进了分布
        assert out["authority_distribution"].get("canonical", 0) == 5, (
            f"期望 canonical: 5, 实际 {out['authority_distribution']} — "
            "P0-A 修法没让外挂 canonical 真进 telemetry"
        )
        # 3 workspace local contextual
        assert out["authority_distribution"].get("contextual", 0) == 3
        # mode: rich (因为外挂 5 canonical 算入业务 md, > 3 阈值)
        assert out["mode"] == "rich"

    def test_calibration_scenario_full(self, workspace_with_external_canonical):
        """端到端 calibration 场景: 修前 wiki_mode=sparse + dist={}, 修后 rich + canonical:5."""
        ws = workspace_with_external_canonical
        out = get_wiki_telemetry(ws)

        # 修前 (P0-A 之前):
        #   wiki_mode = sparse
        #   authority_distribution = {} 空 dict
        # 修后 (P0-A 之后):
        #   wiki_mode = rich (workspace local 3 contextual + 外挂 5 canonical = 8 ≥ 3)
        #   authority_distribution = {canonical: 5, contextual: 3}
        assert out["mode"] == "rich"
        assert sum(out["authority_distribution"].values()) == 8
        assert "canonical" in out["authority_distribution"]
