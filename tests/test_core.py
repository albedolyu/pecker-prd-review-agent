"""
啄木鸟 PRD 评审 Agent — 核心函数单元测试
运行: pytest tests/test_core.py
"""

import sys
import os

# 让 Python 找到上级目录中的模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


# ============================================================
# tools._resolve_path
# ============================================================

class TestResolvePath:
    """_resolve_path: 路径解析与越权保护"""

    def test_normal_relative_path(self, tmp_path):
        """正常相对路径解析为绝对路径"""
        from tools import _resolve_path
        result = _resolve_path("raw/foo.md", str(tmp_path))
        assert result == os.path.normpath(os.path.join(str(tmp_path), "raw/foo.md"))

    def test_empty_path_returns_workspace(self, tmp_path):
        """空路径返回工作目录本身"""
        from tools import _resolve_path
        result = _resolve_path("", str(tmp_path))
        assert result == str(tmp_path)

    def test_path_traversal_dotdot_raises(self, tmp_path):
        """../../etc/passwd 形式的路径遍历应抛出 PermissionError"""
        from tools import _resolve_path
        with pytest.raises(PermissionError):
            _resolve_path("../../etc/passwd", str(tmp_path))

    def test_path_traversal_prefix_collision(self, tmp_path):
        """
        前缀碰撞场景：workspace=/work，路径解析到 /workspace/evil 时
        不应被视为合法路径（/workspace 以 /work 开头但不等同于 /work/）
        用 tmp_path 模拟：workspace=<tmp>/work，路径逃逸到 <tmp>/workspace/evil
        """
        from tools import _resolve_path
        workspace = os.path.join(str(tmp_path), "work")
        os.makedirs(workspace, exist_ok=True)
        # 构造一个解析后跑到 workspace 同级目录的路径
        evil_path = os.path.join("..", "workspace", "evil")
        with pytest.raises(PermissionError):
            _resolve_path(evil_path, workspace)

    def test_subdirectory_is_allowed(self, tmp_path):
        """子目录路径合法，不应抛出异常"""
        from tools import _resolve_path
        result = _resolve_path("wiki/page.md", str(tmp_path))
        assert str(tmp_path) in result


# ============================================================
# security.check_file_permission
# ============================================================

class TestCheckFilePermission:
    """check_file_permission: 目录读写权限围栏"""

    def test_raw_read_allowed(self, tmp_path):
        """raw/ 目录：读取允许"""
        from security import check_file_permission
        allowed, reason = check_file_permission("raw/report.md", "read", str(tmp_path))
        assert allowed is True

    def test_raw_write_blocked(self, tmp_path):
        """raw/ 目录：写入被禁"""
        from security import check_file_permission
        allowed, reason = check_file_permission("raw/report.md", "write", str(tmp_path))
        assert allowed is False
        assert "禁止" in reason or "只读" in reason

    def test_wiki_read_allowed(self, tmp_path):
        """wiki/ 目录：读取允许"""
        from security import check_file_permission
        allowed, _ = check_file_permission("wiki/index.md", "read", str(tmp_path))
        assert allowed is True

    def test_wiki_write_allowed(self, tmp_path):
        """wiki/ 目录：写入允许"""
        from security import check_file_permission
        allowed, _ = check_file_permission("wiki/index.md", "write", str(tmp_path))
        assert allowed is True

    def test_output_read_allowed(self, tmp_path):
        """output/ 目录：读取允许"""
        from security import check_file_permission
        allowed, _ = check_file_permission("output/result.md", "read", str(tmp_path))
        assert allowed is True

    def test_output_write_allowed(self, tmp_path):
        """output/ 目录：写入允许"""
        from security import check_file_permission
        allowed, _ = check_file_permission("output/result.md", "write", str(tmp_path))
        assert allowed is True

    def test_unknown_dir_read_allowed(self, tmp_path):
        """未知目录：默认允许读取"""
        from security import check_file_permission
        allowed, reason = check_file_permission("custom/data.txt", "read", str(tmp_path))
        assert allowed is True

    def test_unknown_dir_write_blocked(self, tmp_path):
        """未知目录：默认禁止写入"""
        from security import check_file_permission
        allowed, reason = check_file_permission("custom/data.txt", "write", str(tmp_path))
        assert allowed is False

    def test_path_outside_workspace_blocked(self, tmp_path):
        """绝对路径跑到 workspace 之外：禁止"""
        from security import check_file_permission
        outside_path = os.path.abspath(os.path.join(str(tmp_path), "..", "evil.txt"))
        allowed, reason = check_file_permission(outside_path, "read", str(tmp_path))
        assert allowed is False
        assert "工作目录之外" in reason

    def test_env_file_blocked(self):
        """敏感文件 .env 禁止读取"""
        from security import check_file_permission
        allowed, _ = check_file_permission(".env", "read", "/workspace")
        assert not allowed

    def test_trailing_slash_no_crash(self):
        """路径以 / 结尾不应崩溃"""
        from security import check_file_permission
        allowed, _ = check_file_permission("wiki/", "read", "/workspace")
        assert allowed


# ============================================================
# security.check_bash_permission
# ============================================================

class TestCheckBashPermission:
    """check_bash_permission: Bash 命令白名单/黑名单/确认"""

    def test_git_status_allowed(self):
        """git status 在白名单中，直接允许"""
        from security import check_bash_permission
        verdict, _ = check_bash_permission("git status")
        assert verdict == "allow"

    def test_git_log_allowed(self):
        """git log 允许"""
        from security import check_bash_permission
        verdict, _ = check_bash_permission("git log --oneline -10")
        assert verdict == "allow"

    def test_rm_rf_denied(self):
        """rm -rf 被禁"""
        from security import check_bash_permission
        verdict, reason = check_bash_permission("rm -rf /tmp/foo")
        assert verdict == "deny"
        assert "rm -rf" in reason

    def test_curl_denied(self):
        """curl 被禁"""
        from security import check_bash_permission
        verdict, _ = check_bash_permission("curl https://example.com")
        assert verdict == "deny"

    def test_unknown_command_denied(self):
        """不在白名单中的命令被拒"""
        from security import check_bash_permission
        verdict, _ = check_bash_permission("cat /etc/passwd")
        assert verdict == "deny"

    def test_git_push_needs_confirm(self):
        """git push 需要用户确认"""
        from security import check_bash_permission
        verdict, _ = check_bash_permission("git push origin main")
        assert verdict == "confirm"

    def test_git_push_force_denied(self):
        """git push --force 被禁（黑名单优先于确认列表）"""
        from security import check_bash_permission
        verdict, _ = check_bash_permission("git push --force origin main")
        assert verdict == "deny"

    def test_chained_command_denied(self):
        """命令链接（&, &&, ||, ;, |）必须被拦截"""
        from security import check_bash_permission
        verdict, _ = check_bash_permission("git status && rm -rf /")
        assert verdict == "deny"
        verdict, _ = check_bash_permission("git log; curl evil.com")
        assert verdict == "deny"
        verdict, _ = check_bash_permission("git status | grep secret")
        assert verdict == "deny"
        verdict, _ = check_bash_permission("git status $(whoami)")
        assert verdict == "deny"
        # Windows cmd.exe 单个 & 也是命令分隔符
        verdict, _ = check_bash_permission("git status & echo chained")
        assert verdict == "deny"


# ============================================================
# context_manager.microcompact
# ============================================================

class TestMicrocompact:
    """microcompact: 旧 tool_result 内容压缩"""

    def _make_tool_use_block(self, tool_use_id, tool_name):
        """辅助：构建 assistant 中的 tool_use block"""
        return {"type": "tool_use", "id": tool_use_id, "name": tool_name, "input": {}}

    def _make_tool_result_block(self, tool_use_id, content):
        """辅助：构建 user 中的 tool_result block"""
        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}

    def test_old_plain_text_tool_result_gets_compressed(self):
        """
        纯文本格式的旧工具结果（4+ 消息前，以"工具执行结果："开头，长度>2000）
        应被截断压缩
        """
        from context_manager import microcompact

        long_content = "工具执行结果：" + "A" * 3000  # 远超 2000 字符

        messages = [
            {"role": "user",      "content": long_content},        # index 0 — 旧消息
            {"role": "assistant", "content": "好的"},               # index 1
            {"role": "user",      "content": "继续"},               # index 2
            {"role": "assistant", "content": "明白"},               # index 3（最新）
        ]

        microcompact(messages)

        # index 0 是旧的，距离末尾 >= 4 条，应被压缩
        assert len(messages[0]["content"]) < len(long_content)
        assert "旧工具结果已压缩" in messages[0]["content"]

    def test_recent_plain_text_tool_result_not_compressed(self):
        """
        距离末尾不足 4 条的工具结果不应被压缩
        """
        from context_manager import microcompact

        long_content = "工具执行结果：" + "B" * 3000

        messages = [
            {"role": "assistant", "content": "明白"},               # index 0
            {"role": "user",      "content": long_content},        # index 1（距离末尾仅 2 步）
            {"role": "assistant", "content": "好的"},               # index 2（最新）
        ]

        microcompact(messages)

        # 最近消息不压缩
        assert messages[1]["content"] == long_content

    def test_short_old_content_not_compressed(self):
        """
        长度不超过 2000 的旧工具结果不压缩
        """
        from context_manager import microcompact

        short_content = "工具执行结果：" + "C" * 100  # 短于 2000

        messages = [
            {"role": "user",      "content": short_content},
            {"role": "assistant", "content": "ok"},
            {"role": "user",      "content": "next"},
            {"role": "assistant", "content": "ok2"},
        ]

        microcompact(messages)

        assert messages[0]["content"] == short_content

    def test_non_tool_result_message_untouched(self):
        """
        不以"工具执行结果："开头的旧消息不处理
        """
        from context_manager import microcompact

        normal_content = "用户的普通消息" + "X" * 3000

        messages = [
            {"role": "user",      "content": normal_content},
            {"role": "assistant", "content": "a"},
            {"role": "user",      "content": "b"},
            {"role": "assistant", "content": "c"},
        ]

        microcompact(messages)

        assert messages[0]["content"] == normal_content


# ============================================================
# context_manager.check_convergence
# ============================================================

class TestCheckConvergence:
    """check_convergence: 检测 agent 打转"""

    def _make_assistant_msg(self, text):
        return {"role": "assistant", "content": text}

    def _make_user_msg(self, text="继续"):
        return {"role": "user", "content": text}

    def test_three_short_consecutive_returns_nudge(self):
        """最近 3 轮 assistant 消息均 < 200 字符 → 返回 nudge"""
        from context_manager import check_convergence

        messages = [
            self._make_user_msg("开始"),
            self._make_assistant_msg("嗯"),          # 短
            self._make_user_msg(),
            self._make_assistant_msg("好"),          # 短
            self._make_user_msg(),
            self._make_assistant_msg("继续"),        # 短
        ]

        result = check_convergence(messages, threshold=3)
        assert result is not None
        assert result["role"] == "user"
        assert "系统提示" in result["content"] or "检测到" in result["content"]

    def test_one_long_message_returns_none(self):
        """只要有一轮 assistant 消息足够长 → 返回 None"""
        from context_manager import check_convergence

        long_text = "这是一段很长的分析内容，足以证明 agent 没有在打转。" * 10  # > 200 字符

        messages = [
            self._make_user_msg("开始"),
            self._make_assistant_msg("嗯"),          # 短
            self._make_user_msg(),
            self._make_assistant_msg(long_text),    # 长 → 打破全短条件
            self._make_user_msg(),
            self._make_assistant_msg("好"),          # 短
        ]

        result = check_convergence(messages, threshold=3)
        assert result is None

    def test_fewer_turns_than_threshold_returns_none(self):
        """历史轮数不足 threshold → 返回 None"""
        from context_manager import check_convergence

        messages = [
            self._make_user_msg("开始"),
            self._make_assistant_msg("嗯"),          # 仅 1 轮
        ]

        result = check_convergence(messages, threshold=3)
        assert result is None

    def test_exactly_threshold_short_messages(self):
        """刚好 threshold 轮都短 → 返回 nudge"""
        from context_manager import check_convergence

        messages = [
            self._make_user_msg("u1"),
            self._make_assistant_msg("a"),
            self._make_user_msg("u2"),
            self._make_assistant_msg("b"),
            self._make_user_msg("u3"),
            self._make_assistant_msg("c"),
        ]

        result = check_convergence(messages, threshold=3)
        assert result is not None


# ============================================================
# parallel_review.merge_and_deduplicate
# ============================================================

class TestMergeAndDeduplicate:
    """merge_and_deduplicate: 合并去重、重编号、排序"""

    def _item(self, id_, location, issue, severity="should"):
        return {
            "id": id_,
            "location": location,
            "issue": issue,
            "suggestion": "修改建议",
            "severity": severity,
            "evidence_type": "B",
            "evidence_content": "RC-001",
            "dimension": "quality",
        }

    def test_dedup_keeps_higher_severity(self):
        """
        两条 location+issue 相似度 > 80% 的条目：
        should 版本和 must 版本共存时，保留 must
        """
        from parallel_review import merge_and_deduplicate

        item_should = self._item("A-001", "第3节 用户登录", "缺少密码长度说明", "should")
        item_must   = self._item("B-001", "第3节 用户登录", "缺少密码长度说明", "must")

        result = merge_and_deduplicate([item_should, item_must])

        # 去重后只剩 1 条
        assert len(result) == 1
        assert result[0]["severity"] == "must"

    def test_renumbering(self):
        """合并后编号应重置为 R-001, R-002, ..."""
        from parallel_review import merge_and_deduplicate

        items = [
            self._item("X-001", "第1节", "问题甲", "should"),
            self._item("X-002", "第2节", "问题乙", "should"),
            self._item("X-003", "第3节", "问题丙", "must"),
        ]

        result = merge_and_deduplicate(items)

        ids = [r["id"] for r in result]
        assert ids[0] == "R-001"
        assert ids[1] == "R-002"
        assert ids[2] == "R-003"

    def test_must_before_should(self):
        """must 严重度的条目排在 should 之前"""
        from parallel_review import merge_and_deduplicate

        items = [
            self._item("S-001", "第1节", "轻微问题", "should"),
            self._item("M-001", "第2节", "严重问题", "must"),
            self._item("S-002", "第3节", "另一轻微", "should"),
        ]

        result = merge_and_deduplicate(items)

        # 第一条应是 must
        assert result[0]["severity"] == "must"
        # 其余都是 should
        for item in result[1:]:
            assert item["severity"] == "should"

    def test_distinct_items_all_kept(self):
        """不相似的条目应全部保留"""
        from parallel_review import merge_and_deduplicate

        items = [
            self._item("A-001", "用户模块", "缺少密码规则", "must"),
            self._item("B-001", "支付流程", "金额精度未定义", "should"),
            self._item("C-001", "推送通知", "触发时机不明", "should"),
        ]

        result = merge_and_deduplicate(items)
        assert len(result) == 3

    def test_empty_input_returns_empty(self):
        """空输入返回空列表"""
        from parallel_review import merge_and_deduplicate
        assert merge_and_deduplicate([]) == []


# ============================================================
# feedback._match_signal_to_item
# ============================================================

class TestMatchSignalToItem:
    """_match_signal_to_item: 信号与改进项的关联评分"""

    def _signal(self, content, file="src/search.py", signal_type="assumption"):
        return {
            "type": signal_type,
            "file": file,
            "line": 10,
            "content": content,
            "signal_type": signal_type,
        }

    def _item(self, location, problem):
        return {
            "id": "R-001",
            "location": location,
            "problem": problem,
            "severity": "should",
            "status": "confirmed",
        }

    def test_matching_keywords_score_high_enough(self):
        """
        文件路径命中 (+2) 加上类型亲和命中 (+1)，总分 >= 2 → 命中。
        信号文件路径含 "payment"，改进项 location 也含 "payment"（路径匹配 +2）；
        改进项 problem 含 "未说明"（assumption 类型亲和词 +1）。
        """
        from feedback import _match_signal_to_item

        signal = self._signal(
            content="TODO: 金额精度规则由开发自行决定",
            file="src/payment/checkout.py",
            signal_type="assumption",
        )
        item = self._item(
            location="payment 支付模块",
            problem="金额计算精度未说明，开发需自行假设",
        )

        matched, _ = _match_signal_to_item(signal, item)
        assert matched is True

    def test_unrelated_signal_does_not_match(self):
        """
        信号内容与改进项完全不相关，不应命中
        """
        from feedback import _match_signal_to_item

        signal = self._signal(
            content="loading spinner added for image gallery",
            file="src/gallery.py",
            signal_type="ui_state_gap",
        )
        item = self._item(
            location="第5节 数据导出",
            problem="导出字段映射缺失，需与后端对齐",
        )

        matched, _ = _match_signal_to_item(signal, item)
        assert matched is False

    def test_file_path_match_contributes(self):
        """
        文件路径中的词出现在改进项 location 中时，加 2 分，可以使评分达标
        """
        from feedback import _match_signal_to_item

        # 改进项 location 含 "payment"，信号文件路径含 "payment"
        signal = self._signal(
            content="FIXME: 金额精度暂定两位小数",
            file="src/payment/order.py",
            signal_type="assumption",
        )
        item = self._item(
            location="payment 支付模块",
            problem="金额精度未说明",
        )

        matched, _ = _match_signal_to_item(signal, item)
        assert matched is True

    def test_empty_item_location_and_problem_returns_false(self):
        """
        改进项 location 和 problem 都为空时，无法评分，应返回 False
        """
        from feedback import _match_signal_to_item

        signal = self._signal("TODO: something")
        item = {"id": "R-001", "location": "", "problem": "", "severity": "should", "status": "confirmed"}

        matched, _ = _match_signal_to_item(signal, item)
        assert matched is False


# ============================================================
# shrike_review — 五关质量门禁
# ============================================================

from shrike_review import (
    check_report_completeness, check_id_consistency,
    check_wiki_quality, check_security, check_format_compliance,
)

# 改动报告五个必需章节
_ALL_SECTIONS = "## 评审概览\n## 已确认\n## 待确定\n## 已驳回\n## 人工复核提醒\n"


class TestShrikeGate1:
    """Gate 1: check_report_completeness — 改动报告必需章节完整性"""

    def test_complete_report_passes(self, tmp_path):
        """包含全部 5 个必需章节的报告应通过"""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "PRD_改动报告_20260101.md").write_text(
            _ALL_SECTIONS, encoding="utf-8"
        )
        result = check_report_completeness(str(output_dir))
        assert result["passed"] is True
        assert result["details"] == []

    def test_missing_section_fails(self, tmp_path):
        """缺少「人工复核提醒」章节时应不通过，details 中需提及该章节"""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        content = "## 评审概览\n## 已确认\n## 待确定\n## 已驳回\n"  # 故意漏掉人工复核提醒
        (output_dir / "PRD_改动报告_20260101.md").write_text(content, encoding="utf-8")
        result = check_report_completeness(str(output_dir))
        assert result["passed"] is False
        assert any("人工复核提醒" in d for d in result["details"])

    def test_no_report_file_fails(self, tmp_path):
        """空目录中找不到改动报告文件时应不通过"""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        result = check_report_completeness(str(output_dir))
        assert result["passed"] is False


class TestShrikeGate2:
    """Gate 2: check_id_consistency — R-xxx 编号交叉比对"""

    def test_consistent_ids_pass(self, tmp_path):
        """改动报告与差异报告含相同编号集合，应通过"""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "PRD_改动报告_20260101.md").write_text(
            _ALL_SECTIONS + "\nR-001\nR-002\n", encoding="utf-8"
        )
        (output_dir / "PRD_差异报告_20260101.md").write_text(
            "R-001\nR-002\n", encoding="utf-8"
        )
        result = check_id_consistency(str(output_dir))
        assert result["passed"] is True

    def test_inconsistent_ids_fail(self, tmp_path):
        """改动报告有 R-001 R-002，差异报告只有 R-001，应不通过"""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "PRD_改动报告_20260101.md").write_text(
            _ALL_SECTIONS + "\nR-001\nR-002\n", encoding="utf-8"
        )
        (output_dir / "PRD_差异报告_20260101.md").write_text(
            "R-001\n", encoding="utf-8"
        )
        result = check_id_consistency(str(output_dir))
        assert result["passed"] is False
        # details 中应提到 R-002 缺失
        combined = " ".join(result["details"])
        assert "R-002" in combined


class TestShrikeGate3:
    """Gate 3: check_wiki_quality — frontmatter / 命名前缀 / 双向链接"""

    def test_compliant_page_passes(self, tmp_path):
        """含 frontmatter、合规前缀、双向链接的页面应通过"""
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        content = "---\ntitle: 测试\n---\n\n正文内容 [[其他页面]]\n"
        (wiki_dir / "概念-搜索意图.md").write_text(content, encoding="utf-8")
        result = check_wiki_quality(str(wiki_dir))
        assert result["passed"] is True
        assert result["details"] == []

    def test_missing_frontmatter_fails(self, tmp_path):
        """没有 --- frontmatter 的页面应不通过"""
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        content = "# 标题\n\n正文 [[链接]]\n"  # 无 frontmatter
        (wiki_dir / "概念-测试页.md").write_text(content, encoding="utf-8")
        result = check_wiki_quality(str(wiki_dir))
        assert result["passed"] is False
        # details 中应有该文件的问题记录
        assert any(d["file"] == "概念-测试页.md" for d in result["details"])

    def test_no_wiki_dir_passes(self, tmp_path):
        """wiki_path=None 时视为可选目录，应直接通过"""
        result = check_wiki_quality(None)
        assert result["passed"] is True
        assert result["details"] == []


class TestShrikeGate4:
    """Gate 4: check_security — 敏感信息扫描"""

    def test_clean_files_pass(self, tmp_path):
        """无敏感信息的文件应通过"""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "PRD_改动报告_20260101.md").write_text(
            "这是一份干净的报告，没有敏感信息。\n", encoding="utf-8"
        )
        result = check_security(str(output_dir))
        assert result["passed"] is True
        assert result["details"] == []

    def test_api_key_detected(self, tmp_path):
        """包含 sk- 开头 API Key 的文件应被检测出来"""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "PRD_改动报告_20260101.md").write_text(
            "调用密钥：sk-abc123def456ghi789jkl012\n", encoding="utf-8"
        )
        result = check_security(str(output_dir))
        assert result["passed"] is False
        assert len(result["details"]) >= 1

    def test_internal_ip_detected(self, tmp_path):
        """包含内网 IP 192.168.x.x 的文件应被检测出来"""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "PRD_改动报告_20260101.md").write_text(
            "数据库地址：192.168.1.100\n", encoding="utf-8"
        )
        result = check_security(str(output_dir))
        assert result["passed"] is False
        assert len(result["details"]) >= 1


class TestShrikeGate5:
    """Gate 5: check_format_compliance — 改进项必填字段完整度"""

    def _make_report(self, output_dir, item_content):
        """辅助：写一份含指定条目内容的改动报告"""
        body = _ALL_SECTIONS + item_content
        (output_dir / "PRD_改动报告_20260101.md").write_text(body, encoding="utf-8")

    def test_complete_items_pass(self, tmp_path):
        """R-001 包含全部 5 个必填字段时，通过率应为 1.0"""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        item = (
            "\n#### R-001 登录流程缺少说明\n"
            "**位置**：第3节\n"
            "**问题**：缺少密码长度约束\n"
            "**建议**：补充密码规则\n"
            "**严重度**：must\n"
            "**依据**：RC-001\n"
        )
        self._make_report(output_dir, item)
        result = check_format_compliance(str(output_dir))
        assert result["passed"] is True
        assert result["rate"] == 1.0

    def test_missing_fields_fail(self, tmp_path):
        """R-001 缺少「严重度」和「依据」字段时，通过率应 < 1.0"""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        item = (
            "\n#### R-001 登录流程缺少说明\n"
            "**位置**：第3节\n"
            "**问题**：缺少密码长度约束\n"
            "**建议**：补充密码规则\n"
            # 故意省略严重度和依据
        )
        self._make_report(output_dir, item)
        result = check_format_compliance(str(output_dir))
        assert result["rate"] < 1.0
        # details 应包含 R-001 的缺失字段信息
        assert any(d["id"] == "R-001" for d in result["details"])


# ============================================================
# api_adapter.TokenTracker
# ============================================================

class TestTokenTracker:
    """TokenTracker: 累积 token 用量统计"""

    def test_empty_tracker(self):
        """新建 tracker 初始状态为零"""
        from api_adapter import TokenTracker
        tracker = TokenTracker()
        assert tracker.calls == 0
        assert tracker.input_tokens == 0
        assert tracker.output_tokens == 0

    def test_record_accumulates(self):
        """连续 record 3 次，总量正确累加"""
        from api_adapter import TokenTracker
        tracker = TokenTracker()
        tracker.record("claude-sonnet-4-6", 100, 50)
        tracker.record("claude-sonnet-4-6", 200, 80)
        tracker.record("claude-sonnet-4-6", 300, 120)
        assert tracker.calls == 3
        assert tracker.input_tokens == 600
        assert tracker.output_tokens == 250

    def test_by_model_tracking(self):
        """不同模型分别统计，per-model stats 正确"""
        from api_adapter import TokenTracker
        tracker = TokenTracker()
        tracker.record("claude-sonnet-4-6", 100, 40)
        tracker.record("claude-haiku-4-5", 50, 20)
        tracker.record("claude-sonnet-4-6", 200, 60)
        # sonnet: 2 次，input=300, output=100
        assert tracker.by_model["claude-sonnet-4-6"]["calls"] == 2
        assert tracker.by_model["claude-sonnet-4-6"]["input"] == 300
        assert tracker.by_model["claude-sonnet-4-6"]["output"] == 100
        # haiku: 1 次，input=50, output=20
        assert tracker.by_model["claude-haiku-4-5"]["calls"] == 1
        assert tracker.by_model["claude-haiku-4-5"]["input"] == 50
        assert tracker.by_model["claude-haiku-4-5"]["output"] == 20

    def test_summary_format(self):
        """summary() 返回字符串，包含调用次数和 token 信息"""
        from api_adapter import TokenTracker
        tracker = TokenTracker()
        tracker.record("claude-sonnet-4-6", 1000, 500)
        summary = tracker.summary()
        assert isinstance(summary, str)
        assert "1" in summary          # 调用次数
        assert "1,000" in summary      # input token（格式化带逗号）
        assert "500" in summary        # output token
        assert "1,500" in summary      # total


# ============================================================
# goshawk_advisor.apply_advisor_result
# ============================================================

def _make_review_item(id_, severity="should"):
    """辅助：构造最小改进项 dict"""
    return {
        "id": id_,
        "location": f"第N节 {id_}",
        "issue": f"问题描述 {id_}",
        "suggestion": "建议修改",
        "severity": severity,
        "evidence_type": "B",
        "evidence_content": "RC-001",
        "dimension": "quality",
    }


def _make_advisor_result(false_positives=None, additional_findings=None, conflict_resolutions=None):
    """辅助：构造苍鹰结果 dict"""
    return {
        "flagged_as_false_positive": false_positives or [],
        "additional_findings": additional_findings or [],
        "conflict_resolutions": conflict_resolutions or [],
        "confidence": 0.9,
    }


class TestApplyAdvisorResult:
    """apply_advisor_result: 苍鹰结果合并逻辑"""

    def test_false_positive_removed(self):
        """苍鹰将 R-001 标记为误报且建议「移除」，R-001 不出现在活跃列表"""
        from goshawk_advisor import apply_advisor_result
        items = [_make_review_item("R-001"), _make_review_item("R-002")]
        advisor = _make_advisor_result(
            false_positives=[{
                "item_id": "R-001",
                "reason": "PRD 第2节已有说明",
                "recommendation": "移除",
            }]
        )
        result = apply_advisor_result(items, advisor)
        ids = [r["id"] for r in result]
        assert "R-001" not in ids
        assert "R-002" in ids

    def test_false_positive_downgraded(self):
        """苍鹰标记误报但建议降级（非移除），R-001 severity 变为 should"""
        from goshawk_advisor import apply_advisor_result
        items = [_make_review_item("R-001", severity="must"), _make_review_item("R-002")]
        advisor = _make_advisor_result(
            false_positives=[{
                "item_id": "R-001",
                "reason": "过度解读",
                "recommendation": "降级为 should",
            }]
        )
        result = apply_advisor_result(items, advisor)
        r001 = next(r for r in result if r["id"] == "R-001")
        assert r001["severity"] == "should"

    def test_additional_findings_added(self):
        """苍鹰补充 2 条漏报，追加为 R-003 R-004，source 为苍鹰补充"""
        from goshawk_advisor import apply_advisor_result
        items = [_make_review_item("R-001"), _make_review_item("R-002")]
        advisor = _make_advisor_result(
            additional_findings=[
                {"location": "第5节", "issue": "漏报甲", "severity": "should", "evidence": "依据A"},
                {"location": "第6节", "issue": "漏报乙", "severity": "must",   "evidence": "依据B"},
            ]
        )
        result = apply_advisor_result(items, advisor)
        ids = [r["id"] for r in result]
        assert "R-003" in ids
        assert "R-004" in ids
        new_item = next(r for r in result if r["id"] == "R-003")
        assert new_item["source"] == "苍鹰补充"

    def test_additional_findings_capped_at_2(self):
        """苍鹰补充 5 条漏报，实际只追加前 2 条"""
        from goshawk_advisor import apply_advisor_result
        items = [_make_review_item("R-001"), _make_review_item("R-002")]
        advisor = _make_advisor_result(
            additional_findings=[
                {"location": f"第{i}节", "issue": f"漏报{i}", "severity": "should", "evidence": "依据"}
                for i in range(1, 6)  # 5 条
            ]
        )
        result = apply_advisor_result(items, advisor)
        # 原 2 条 + 最多 2 条新增 = 4 条
        assert len(result) == 4
        ids = [r["id"] for r in result]
        assert "R-003" in ids
        assert "R-004" in ids
        assert "R-005" not in ids
        assert "R-006" not in ids
        assert "R-007" not in ids

    def test_conflict_resolution_merges(self):
        """R-001 R-002 冲突: R-002 保留为 could 级 facet,链 facet_of=R-001 (2026-04-24 facet 保留)"""
        from goshawk_advisor import apply_advisor_result
        items = [_make_review_item("R-001"), _make_review_item("R-002")]
        advisor = _make_advisor_result(
            conflict_resolutions=[{
                "items": ["R-001", "R-002"],
                "resolution": "保留 R-001，R-002 同源",
                "reason": "两条描述同一问题",
            }]
        )
        result = apply_advisor_result(items, advisor)
        ids = [r["id"] for r in result]
        # 老语义已废弃: 不再从活跃列表移除被合并的
        assert "R-001" in ids
        assert "R-002" in ids   # 保留为 facet,不过滤
        r002 = next(r for r in result if r["id"] == "R-002")
        assert r002["severity"] == "could"          # 降到 facet 级
        assert r002["facet_of"] == "R-001"           # 链回 primary
        assert r002["status"] == "MERGED_BY_ADVISOR"  # 审计痕迹保留
        assert r002["provenance"] == "facet_of_advisor"
        assert "R-001" in r002["advisor_note"]

    def test_conflict_resolution_multi_facet(self):
        """3 条冲突: R-001 primary, R-002 R-003 都成 could facet (避免 1 个宏观问题吞 N 个章节)"""
        from goshawk_advisor import apply_advisor_result
        items = [
            _make_review_item("R-001", severity="must"),
            _make_review_item("R-002", severity="must"),
            _make_review_item("R-003", severity="should"),
        ]
        advisor = _make_advisor_result(
            conflict_resolutions=[{
                "items": ["R-001", "R-002", "R-003"],
                "resolution": "保留 R-001，R-002/R-003 同源 facet",
                "reason": "三条描述跨章节同一类问题",
            }]
        )
        result = apply_advisor_result(items, advisor)
        ids = [r["id"] for r in result]
        assert ids == ["R-001", "R-002", "R-003"]    # 三条都保留
        r001 = next(r for r in result if r["id"] == "R-001")
        assert r001["severity"] == "must"             # primary 不动
        assert "facet_of" not in r001                  # primary 不带 facet_of
        for fid in ("R-002", "R-003"):
            f = next(r for r in result if r["id"] == fid)
            assert f["severity"] == "could"
            assert f["facet_of"] == "R-001"

    def test_empty_advisor_no_changes(self):
        """空苍鹰结果，改进项数量和内容不变"""
        from goshawk_advisor import apply_advisor_result
        items = [_make_review_item("R-001"), _make_review_item("R-002")]
        advisor = _make_advisor_result()
        result = apply_advisor_result(items, advisor)
        assert len(result) == 2
        assert result[0]["id"] == "R-001"
        assert result[1]["id"] == "R-002"
