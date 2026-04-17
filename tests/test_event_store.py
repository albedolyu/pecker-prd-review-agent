"""
EventStore 覆盖测试

关键验证: JSONL 追加写入 + replay + last_checkpoint 查找,以及对损坏文件的韧性。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestEventStoreAppend:
    def test_creates_file_and_parent_dirs(self, tmp_path):
        from event_store import EventStore
        store = EventStore(workspace=str(tmp_path), review_id="rev_001")
        store.append("review_started", {"prd": "foo.md"})
        expected = tmp_path / "output" / "sessions" / "rev_001.jsonl"
        assert expected.exists()

    def test_appends_multiple_events(self, tmp_path):
        from event_store import EventStore
        store = EventStore(workspace=str(tmp_path), review_id="rev_002")
        store.append("a", {"x": 1})
        store.append("b", {"y": 2})
        store.append("c", None)
        events = store.replay()
        assert [e["type"] for e in events] == ["a", "b", "c"]
        assert events[0]["x"] == 1
        # ts 字段自动加
        assert all("ts" in e for e in events)

    def test_unicode_content_preserved(self, tmp_path):
        from event_store import EventStore
        store = EventStore(workspace=str(tmp_path), review_id="rev_003")
        store.append("worker_done", {"dim": "数据核对员", "items": ["搜索接口"]})
        events = store.replay()
        assert events[0]["dim"] == "数据核对员"
        assert events[0]["items"] == ["搜索接口"]

    def test_append_none_data_handled(self, tmp_path):
        from event_store import EventStore
        store = EventStore(workspace=str(tmp_path), review_id="rev_004")
        store.append("bare_event", None)
        events = store.replay()
        assert len(events) == 1
        assert events[0]["type"] == "bare_event"


class TestEventStoreReplay:
    def test_missing_file_returns_empty(self, tmp_path):
        from event_store import EventStore
        store = EventStore(workspace=str(tmp_path), review_id="rev_none")
        assert store.replay() == []

    def test_corrupted_file_returns_empty(self, tmp_path):
        from event_store import EventStore
        store = EventStore(workspace=str(tmp_path), review_id="rev_bad")
        # 预先往文件里写损坏内容
        store.path.write_text("not json at all\nalso not json\n", encoding="utf-8")
        # replay 应该不抛,返回 []
        result = store.replay()
        assert result == []

    def test_partial_corrupt_still_returns_empty(self, tmp_path):
        """混合合法+非法行,当前实现遇错整体降级返回 []."""
        from event_store import EventStore
        store = EventStore(workspace=str(tmp_path), review_id="rev_partial")
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text(
            '{"type": "ok", "ts": "t1"}\n'
            'broken line\n'
            '{"type": "also_ok", "ts": "t2"}\n',
            encoding="utf-8",
        )
        result = store.replay()
        # 当前实现用 list comprehension,遇 broken 抛 JSONDecodeError → except → []
        assert result == []

    def test_empty_lines_skipped(self, tmp_path):
        from event_store import EventStore
        store = EventStore(workspace=str(tmp_path), review_id="rev_empty_lines")
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text(
            '{"type": "a", "ts": "t1"}\n\n\n{"type": "b", "ts": "t2"}\n',
            encoding="utf-8",
        )
        result = store.replay()
        assert [e["type"] for e in result] == ["a", "b"]


class TestLastCheckpoint:
    def test_no_events_returns_none(self, tmp_path):
        from event_store import EventStore
        store = EventStore(workspace=str(tmp_path), review_id="rev_x")
        assert store.last_checkpoint() is None

    def test_no_checkpoint_event_returns_none(self, tmp_path):
        from event_store import EventStore
        store = EventStore(workspace=str(tmp_path), review_id="rev_y")
        store.append("review_started", {})
        store.append("worker_done", {})
        assert store.last_checkpoint() is None

    def test_single_checkpoint_returned(self, tmp_path):
        from event_store import EventStore
        store = EventStore(workspace=str(tmp_path), review_id="rev_z")
        store.append("worker_done", {})
        store.append("checkpoint", {"workers_done": 4})
        store.append("review_completed", {})
        cp = store.last_checkpoint()
        assert cp is not None
        assert cp.get("workers_done") == 4

    def test_latest_checkpoint_when_multiple(self, tmp_path):
        from event_store import EventStore
        store = EventStore(workspace=str(tmp_path), review_id="rev_multi")
        store.append("checkpoint", {"round": 1, "items": 3})
        store.append("worker_done", {})
        store.append("checkpoint", {"round": 2, "items": 7})
        store.append("worker_done", {})
        cp = store.last_checkpoint()
        assert cp is not None
        assert cp.get("round") == 2
