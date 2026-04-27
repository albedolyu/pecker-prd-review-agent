"""测试 .review_memory 与 wiki/ 路径解耦

背景 (docs/calibration_multi_run_2026_04_28.md R3):
- R2 retry 4 次"对话太长"失败, 用户手动 rm -rf 清缓存才通过
- 清 .review_memory 时连带清掉 workspace/wiki/, R3 evidence verify 全 fallback A_wiki_sparse_relaxed
- 这是 setup fragility — 没工具命令做"只清 mem 不动 wiki", 只能手 rm

本测试守:
1. clear_review_memory 不动 workspace/wiki/
2. clear_review_memory 不动 prd/, review-rules/ 等其他子目录
3. 默认 mem dir 物理上不在 wiki 子树
4. assert_wiki_isolated 防御传入 mem == wiki 的退化场景
"""
import os
import shutil
import tempfile
import pytest

from review_memory import (
    MEMORY_DIR_NAME,
    get_memory_dir,
    clear_review_memory,
    assert_wiki_isolated,
)


@pytest.fixture
def fake_workspace():
    """构造一个真实形状的 workspace: output/.review_memory + wiki + prd"""
    root = tempfile.mkdtemp(prefix="pecker_iso_test_")
    # 模拟真实 layout
    mem_dir = os.path.join(root, "output", ".review_memory")
    sessions_dir = os.path.join(root, "output", ".sessions")
    wiki_dir = os.path.join(root, "wiki")
    prd_dir = os.path.join(root, "prd")
    rules_dir = os.path.join(root, "review-rules")
    for d in [mem_dir, sessions_dir, wiki_dir, prd_dir, rules_dir]:
        os.makedirs(d, exist_ok=True)
    # 各自塞两个文件做哨兵
    with open(os.path.join(mem_dir, "feedback_x.json"), "w", encoding="utf-8") as f:
        f.write('{"type":"feedback","content":"x"}')
    with open(os.path.join(sessions_dir, "rev_001.jsonl"), "w", encoding="utf-8") as f:
        f.write('{}\n')
    with open(os.path.join(wiki_dir, "实体-员工.md"), "w", encoding="utf-8") as f:
        f.write("# 员工\n本页不应被清缓存动到\n")
    with open(os.path.join(wiki_dir, "概念-工时.md"), "w", encoding="utf-8") as f:
        f.write("# 工时\n本页也不应被动\n")
    with open(os.path.join(prd_dir, "prd_v1.md"), "w", encoding="utf-8") as f:
        f.write("# PRD")
    with open(os.path.join(rules_dir, "RULES.md"), "w", encoding="utf-8") as f:
        f.write("# Rules")
    yield root
    shutil.rmtree(root, ignore_errors=True)


# ---------- 1. 默认路径物理隔离 ----------

def test_default_mem_dir_not_inside_wiki(fake_workspace):
    """守: 默认 .review_memory 不在 wiki 子树, 物理上独立"""
    mem_dir = get_memory_dir(fake_workspace)
    wiki_dir = os.path.join(fake_workspace, "wiki")
    mem_abs = os.path.abspath(mem_dir)
    wiki_abs = os.path.abspath(wiki_dir)
    # mem_dir 不能是 wiki 的子目录
    common = os.path.commonpath([mem_abs, wiki_abs])
    assert common != wiki_abs, f"mem_dir {mem_abs} 落在 wiki {wiki_abs} 子树内"
    # mem_dir 也不能等于 wiki
    assert mem_abs != wiki_abs


def test_default_mem_dir_layout(fake_workspace):
    """默认路径形状: workspace/output/.review_memory"""
    mem_dir = get_memory_dir(fake_workspace)
    assert os.path.basename(mem_dir) == MEMORY_DIR_NAME
    assert os.path.basename(os.path.dirname(mem_dir)) == "output"


# ---------- 2. clear_review_memory 不影响 wiki/ ----------

def test_clear_review_memory_preserves_wiki(fake_workspace):
    """清缓存不能动 wiki/ 任何文件"""
    wiki_dir = os.path.join(fake_workspace, "wiki")
    wiki_files_before = sorted(os.listdir(wiki_dir))

    result = clear_review_memory(fake_workspace)

    # wiki 目录还在
    assert os.path.isdir(wiki_dir)
    # wiki 文件全在
    wiki_files_after = sorted(os.listdir(wiki_dir))
    assert wiki_files_before == wiki_files_after
    # 文件内容也没动
    with open(os.path.join(wiki_dir, "实体-员工.md"), "r", encoding="utf-8") as f:
        assert "本页不应被清缓存动到" in f.read()
    # 返回值标注清掉了 mem
    assert result.get("cleared_mem", False) is True


def test_clear_review_memory_preserves_prd_and_rules(fake_workspace):
    """清缓存不能动 prd/ review-rules/"""
    clear_review_memory(fake_workspace)
    assert os.path.isfile(os.path.join(fake_workspace, "prd", "prd_v1.md"))
    assert os.path.isfile(os.path.join(fake_workspace, "review-rules", "RULES.md"))


def test_clear_review_memory_actually_clears_mem(fake_workspace):
    """清缓存确实把 .review_memory 清空"""
    mem_dir = os.path.join(fake_workspace, "output", ".review_memory")
    assert os.listdir(mem_dir)  # 哨兵确认有文件
    clear_review_memory(fake_workspace)
    # mem dir 还在 (重建空目录) 但内容空
    assert os.path.isdir(mem_dir)
    assert os.listdir(mem_dir) == []


def test_clear_review_memory_with_sessions(fake_workspace):
    """also_sessions=True 时同时清 .sessions 但仍然不动 wiki"""
    sessions_dir = os.path.join(fake_workspace, "output", ".sessions")
    wiki_dir = os.path.join(fake_workspace, "wiki")
    wiki_files_before = sorted(os.listdir(wiki_dir))

    result = clear_review_memory(fake_workspace, also_sessions=True)

    # sessions 清空
    assert os.path.isdir(sessions_dir)
    assert os.listdir(sessions_dir) == []
    # wiki 还在
    assert sorted(os.listdir(wiki_dir)) == wiki_files_before
    assert result.get("cleared_sessions", False) is True


def test_clear_review_memory_idempotent(fake_workspace):
    """缓存不存在时清缓存不应抛错(idempotent)"""
    # 先彻底删 mem 目录
    mem_dir = os.path.join(fake_workspace, "output", ".review_memory")
    shutil.rmtree(mem_dir, ignore_errors=True)
    # 再清一次,应该平静通过
    result = clear_review_memory(fake_workspace)
    assert result.get("cleared_mem") is True  # 仍报告已清(空 → 空)


# ---------- 3. assert_wiki_isolated 防御 ----------

def test_assert_wiki_isolated_passes_default(fake_workspace):
    """默认 layout 下 assert_wiki_isolated 通过"""
    wiki_dir = os.path.join(fake_workspace, "wiki")
    # 不抛错即通过
    assert_wiki_isolated(fake_workspace, wiki_dir)


def test_assert_wiki_isolated_blocks_wiki_inside_output(fake_workspace):
    """如果有人手贱把 wiki 放到 output/ 下(跟 mem 同父),也通过 (它们是兄弟不是父子)"""
    wiki_inside = os.path.join(fake_workspace, "output", "wiki")
    os.makedirs(wiki_inside, exist_ok=True)
    # mem 是 output/.review_memory, wiki 是 output/wiki, 两个兄弟,不重叠 → 通过
    assert_wiki_isolated(fake_workspace, wiki_inside)


def test_assert_wiki_isolated_blocks_wiki_under_mem(fake_workspace):
    """致命退化场景: 有人把 wiki 配到 .review_memory 子目录里, 必须抛错"""
    bad_wiki = os.path.join(fake_workspace, "output", ".review_memory", "wiki")
    os.makedirs(bad_wiki, exist_ok=True)
    with pytest.raises(ValueError, match="wiki"):
        assert_wiki_isolated(fake_workspace, bad_wiki)


def test_assert_wiki_isolated_blocks_wiki_equals_mem(fake_workspace):
    """致命退化场景: wiki_path == mem_dir, 必须抛错"""
    mem_dir = get_memory_dir(fake_workspace)
    with pytest.raises(ValueError):
        assert_wiki_isolated(fake_workspace, mem_dir)


# ---------- 4. clear_review_memory 内含 assert ----------

def test_clear_review_memory_refuses_when_wiki_under_mem():
    """退化配置: wiki_path 在 mem 子树, clear 必须拒绝执行不动任何东西"""
    root = tempfile.mkdtemp(prefix="pecker_iso_bad_")
    try:
        mem_dir = os.path.join(root, "output", ".review_memory")
        bad_wiki = os.path.join(mem_dir, "wiki")
        os.makedirs(bad_wiki, exist_ok=True)
        sentinel = os.path.join(bad_wiki, "shouldnt_die.md")
        with open(sentinel, "w", encoding="utf-8") as f:
            f.write("alive")
        # 若 clear 收到 wiki 配置错位的 workspace, 必须 raise 不要默默删 wiki
        with pytest.raises(ValueError):
            clear_review_memory(root, wiki_path=bad_wiki)
        # 哨兵还在
        assert os.path.isfile(sentinel)
    finally:
        shutil.rmtree(root, ignore_errors=True)
