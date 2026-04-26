"""测试 scripts/fengniao_wiki_frontmatter_batch.py.

覆盖矩阵 (用 tmp_path 创 fixture wiki, 不依赖真实 51 文件):
1. 文件已有完整 frontmatter (4 字段全有) → 0 fields_added (idempotent)
2. 文件无 frontmatter → 4 fields_added
3. 文件 frontmatter 有 authority: trusted → 不动 authority (尊重现有)
4. 正文含 2 个 riskbird-mobile-vue3 引用 → sources_count=2
5. 正文 0 引用 → sources_count 至少给 1 (fallback)
6. dry-run 不写文件 (mtime 不变)
7. --apply --yes 真写文件 + 追加 log.md
8. frontmatter YAML 异常 → warn + 跳过, 不阻断
"""
from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import fengniao_wiki_frontmatter_batch as fwfb


# ============================================================
# fixture 工具
# ============================================================

def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def _make_wiki(tmp_path, files: dict) -> str:
    """files: {rel_path: content_str}, 返回 wiki_root 绝对路径."""
    wiki_root = str(tmp_path / "wiki")
    os.makedirs(wiki_root, exist_ok=True)
    for rel, content in files.items():
        _write(os.path.join(wiki_root, rel), content)
    return wiki_root


# ============================================================
# 1. 已有完整 frontmatter → 0 fields_added (idempotent)
# ============================================================

def test_full_frontmatter_no_op(tmp_path):
    wiki_root = _make_wiki(tmp_path, {
        "modules/foo.md": (
            "---\n"
            "title: Foo\n"
            "verified_by: 源码同步\n"
            "sources: 5\n"
            "last_verified: '2026-04-26'\n"
            "authority: canonical\n"
            "---\n"
            "\nbody text\n"
        )
    })
    paths = fwfb._walk_wiki(wiki_root)
    assert len(paths) == 1
    r = fwfb._scan_one_file(paths[0])
    assert r["error"] is None
    assert r["fields_added"] == {}, f"已有 4 字段不该补任何, got {r['fields_added']}"
    assert r["frontmatter_existed"] is True


# ============================================================
# 2. 无 frontmatter → 4 fields_added
# ============================================================

def test_no_frontmatter_adds_four(tmp_path):
    wiki_root = _make_wiki(tmp_path, {
        "modules/bar.md": "# 标题\n\n纯正文 引用一次 riskbird-mobile-vue3.\n"
    })
    paths = fwfb._walk_wiki(wiki_root)
    r = fwfb._scan_one_file(paths[0])
    assert r["error"] is None
    assert set(r["fields_added"].keys()) == {
        "verified_by", "sources", "last_verified", "authority"
    }
    assert r["fields_added"]["authority"] == "canonical"
    assert r["fields_added"]["verified_by"] == "源码同步"
    assert r["fields_added"]["last_verified"] == "2026-04-26"
    assert r["frontmatter_existed"] is False


# ============================================================
# 3. authority: trusted 已存在 → 不动 authority (尊重现有)
# ============================================================

def test_existing_trusted_authority_preserved(tmp_path):
    wiki_root = _make_wiki(tmp_path, {
        "modules/baz.md": (
            "---\n"
            "title: Baz\n"
            "authority: trusted\n"
            "sources: 3\n"
            "---\n"
            "\nbody RiskBirdApi\n"
        )
    })
    paths = fwfb._walk_wiki(wiki_root)
    r = fwfb._scan_one_file(paths[0])
    assert r["error"] is None
    # 尊重 authority: trusted, 不该补
    assert "authority" not in r["fields_added"]
    # sources 已存在也不补
    assert "sources" not in r["fields_added"]
    # verified_by/last_verified 缺, 应补
    assert "verified_by" in r["fields_added"]
    assert "last_verified" in r["fields_added"]


# ============================================================
# 4. 正文 2 个 riskbird-mobile-vue3 引用 → sources_count=2
# ============================================================

def test_sources_count_from_body(tmp_path):
    body = (
        "# 模块\n\n"
        "前端在 riskbird-mobile-vue3/pages/index.vue 实现, "
        "另外 riskbird-mobile-vue3/utils 有工具.\n"
    )
    wiki_root = _make_wiki(tmp_path, {"modules/qux.md": body})
    paths = fwfb._walk_wiki(wiki_root)
    r = fwfb._scan_one_file(paths[0])
    assert r["error"] is None
    assert r["fields_added"].get("sources") == 2, (
        f"期望 sources=2, got {r['fields_added'].get('sources')}"
    )


def test_sources_count_mixed_repos(tmp_path):
    # 1 次 riskbird-mobile-vue3 + 2 次 RiskBirdApi → 3
    body = "# T\n\n riskbird-mobile-vue3 + RiskBirdApi 还有 RiskBirdApi/x.\n"
    wiki_root = _make_wiki(tmp_path, {"modules/m.md": body})
    paths = fwfb._walk_wiki(wiki_root)
    r = fwfb._scan_one_file(paths[0])
    assert r["fields_added"].get("sources") == 3


# ============================================================
# 5. 正文 0 引用 → sources fallback 为 1
# ============================================================

def test_sources_fallback_one(tmp_path):
    wiki_root = _make_wiki(tmp_path, {
        "modules/empty.md": "# 标题\n\n这里完全没引用源码仓库关键词.\n"
    })
    paths = fwfb._walk_wiki(wiki_root)
    r = fwfb._scan_one_file(paths[0])
    assert r["error"] is None
    assert r["fields_added"].get("sources") == 1, "0 引用应 fallback 给 1"


# ============================================================
# 6. dry-run 不写文件 (mtime 不变)
# ============================================================

def test_dry_run_does_not_modify(tmp_path):
    wiki_root = _make_wiki(tmp_path, {
        "modules/x.md": "# 标题\n\n riskbird-mobile-vue3 一处.\n"
    })
    target = os.path.join(wiki_root, "modules", "x.md")
    mtime_before = os.path.getmtime(target)
    size_before = os.path.getsize(target)

    # 强制等一拍, 让 mtime 比较有意义
    time.sleep(0.05)

    rc = fwfb.run(wiki_root=wiki_root, apply=False, yes=False, out_path=None)
    assert rc == 0

    mtime_after = os.path.getmtime(target)
    size_after = os.path.getsize(target)
    assert mtime_after == mtime_before, "dry-run 不该改 mtime"
    assert size_after == size_before, "dry-run 不该改 size"
    # log.md 也不该被创建
    assert not os.path.isfile(os.path.join(wiki_root, "log.md"))


# ============================================================
# 7. --apply --yes 真写文件 + 追加 log.md
# ============================================================

def test_apply_yes_writes_files_and_log(tmp_path):
    wiki_root = _make_wiki(tmp_path, {
        "modules/a.md": "# A\n\n riskbird-mobile-vue3 hit.\n",
        "modules/b.md": (
            "---\n"
            "title: B\n"
            "verified_by: 源码同步\n"
            "sources: 2\n"
            "last_verified: '2026-04-26'\n"
            "authority: canonical\n"
            "---\n"
            "\nbody.\n"
        ),
    })
    rc = fwfb.run(wiki_root=wiki_root, apply=True, yes=True, out_path=None)
    assert rc == 0

    # a.md 应被改 (4 字段补全)
    with open(os.path.join(wiki_root, "modules", "a.md"), "r", encoding="utf-8") as f:
        a_content = f.read()
    assert a_content.startswith("---\n")
    assert "verified_by:" in a_content
    assert "authority: canonical" in a_content
    assert "last_verified:" in a_content
    assert "sources: 1" in a_content  # 1 hit
    assert "# A" in a_content, "正文不能丢"
    assert "riskbird-mobile-vue3 hit" in a_content

    # b.md 已完整 → 不该被改 (内容上 idempotent, 不强求 mtime)
    with open(os.path.join(wiki_root, "modules", "b.md"), "r", encoding="utf-8") as f:
        b_content = f.read()
    assert "title: B" in b_content
    assert "authority: canonical" in b_content

    # log.md 应被追加
    log_path = os.path.join(wiki_root, "log.md")
    assert os.path.isfile(log_path)
    with open(log_path, "r", encoding="utf-8") as f:
        log = f.read()
    assert "2026-04-26" in log
    assert "batch frontmatter update" in log
    assert "fengniao_wiki_frontmatter_batch.py" in log


def test_apply_without_yes_aborts(tmp_path):
    wiki_root = _make_wiki(tmp_path, {
        "modules/c.md": "# C\n\nbody.\n"
    })
    rc = fwfb.run(wiki_root=wiki_root, apply=True, yes=False, out_path=None)
    assert rc == 1, "--apply 不带 --yes 应返非 0"
    # 文件不该被改 — 仍是无 frontmatter
    with open(os.path.join(wiki_root, "modules", "c.md"), "r", encoding="utf-8") as f:
        c_content = f.read()
    assert not c_content.startswith("---"), "未 confirm 不该写 frontmatter"


# ============================================================
# 8. frontmatter YAML 异常 → warn + 跳过, 不阻断
# ============================================================

def test_yaml_error_skipped_and_does_not_block(tmp_path, capsys):
    wiki_root = _make_wiki(tmp_path, {
        # 故意构造非法 yaml: 缩进矛盾 + 重复 key
        "modules/broken.md": (
            "---\n"
            "title: Broken\n"
            "  bad_indent: x\n"
            "[ unclosed list\n"
            "---\n"
            "body.\n"
        ),
        "modules/ok.md": "# OK\n\nbody.\n",
    })
    rc = fwfb.run(wiki_root=wiki_root, apply=False, yes=False, out_path=None)
    assert rc == 0, "解析失败不该阻断整个流程"

    paths = fwfb._walk_wiki(wiki_root)
    broken = [p for p in paths if "broken.md" in p][0]
    ok = [p for p in paths if "ok.md" in p][0]

    r_broken = fwfb._scan_one_file(broken)
    assert r_broken["error"] is not None
    assert "yaml parse failed" in r_broken["error"] or "parse" in r_broken["error"]

    r_ok = fwfb._scan_one_file(ok)
    assert r_ok["error"] is None
    assert len(r_ok["fields_added"]) == 4

    # warn 应有打到 stderr
    captured = capsys.readouterr()
    assert "broken.md" in captured.err or "broken" in captured.err


# ============================================================
# 额外: _format_report_md 报告生成
# ============================================================

def test_format_report_includes_all_buckets(tmp_path):
    wiki_root = _make_wiki(tmp_path, {
        "modules/full.md": (
            "---\nverified_by: x\nsources: 1\nlast_verified: '2026-04-26'\n"
            "authority: canonical\n---\nbody.\n"
        ),
        "modules/empty.md": "# X\n\nbody.\n",
        "modules/partial.md": (
            "---\nsources: 3\n---\nbody RiskBirdApi.\n"
        ),
    })
    paths = fwfb._walk_wiki(wiki_root)
    results = []
    for p in paths:
        r = fwfb._scan_one_file(p)
        r["rel_path"] = os.path.relpath(p, wiki_root).replace("\\", "/")
        results.append(r)
    counts = fwfb._classify(results)
    report = fwfb._format_report_md(results, wiki_root, counts)

    # 三种类别都应出现
    assert counts["full_add_4"] == 1
    assert counts["partial"] == 1
    assert counts["no_op"] == 1
    assert "Dry Run 报告" in report
    assert "modules/full.md" in report
    assert "modules/empty.md" in report
    assert "modules/partial.md" in report


# ============================================================
# 额外: 不存在的 wiki-root 优雅退出
# ============================================================

def test_missing_wiki_root_returns_error(tmp_path):
    rc = fwfb.run(
        wiki_root=str(tmp_path / "does_not_exist"),
        apply=False, yes=False, out_path=None,
    )
    assert rc == 1


# ============================================================
# 额外: 递归子目录 (api/architecture/modules 等)
# ============================================================

def test_recursive_walk(tmp_path):
    wiki_root = _make_wiki(tmp_path, {
        "api/x.md": "# x\n\n riskbird-mobile-vue3.\n",
        "architecture/y.md": "# y\n\n RiskBirdApi.\n",
        "modules/z.md": "# z\n\nplain.\n",
        "concepts/w.md": "# w\n\nplain.\n",
    })
    paths = fwfb._walk_wiki(wiki_root)
    assert len(paths) == 4
    rels = sorted(os.path.relpath(p, wiki_root).replace("\\", "/") for p in paths)
    assert rels == ["api/x.md", "architecture/y.md", "concepts/w.md", "modules/z.md"]
