"""
focus_tracker 模块的单元测试。
使用 mock 数据构造任务树，验证核心逻辑：
- 查找焦点任务
- 编号列表生成
- 焦点事件记录
- 每日重置检测
- LIVETODAY 焦点检测（inline + child block）
"""
import json
import os
import tempfile
from datetime import date, datetime
from unittest.mock import patch, MagicMock

import pytest

# 直接导入待测的纯逻辑函数（不触发 Notion API）
from focus_tracker import (
    FOCUS_EMOJI,
    find_focus_task,
    list_focusable_tasks,
    record_focus_event,
    load_focus_log,
    save_focus_log,
    _default_focus_log,
    detect_focus_from_livetoday,
    reset_focus_daily,
)


# ── 测试用的 mock 任务树 ──────────────────────────────────────

def _make_tree():
    """构造一棵简单的任务树用于测试。"""
    return [
        {
            "id": "block-1",
            "title": "Task A",
            "type": "bulleted_list_item",
            "children": [
                {
                    "id": "block-1a",
                    "title": f"子任务 A1 {FOCUS_EMOJI}",
                    "type": "to_do",
                    "children": []
                },
                {
                    "id": "block-1b",
                    "title": "子任务 A2",
                    "type": "to_do",
                    "children": []
                }
            ]
        },
        {
            "id": "block-2",
            "title": "Task B",
            "type": "bulleted_list_item",
            "children": []
        },
        {
            "id": "block-p",
            "title": "Some heading",
            "type": "paragraph",
            "children": []
        },
    ]


def _make_tree_no_focus():
    """构造一棵没有焦点 emoji 的任务树。"""
    return [
        {
            "id": "block-x",
            "title": "Clean task",
            "type": "bulleted_list_item",
            "children": []
        }
    ]


# ── find_focus_task 测试 ──────────────────────────────────────

class TestFindFocusTask:
    def test_find_focus_in_tree(self):
        """树中有 💪🏿💪🏿💪🏿 的节点应被正确找到"""
        tree = _make_tree()
        result = find_focus_task(tree)
        assert result is not None
        assert result["block_id"] == "block-1a"
        assert FOCUS_EMOJI in result["title"]

    def test_find_focus_not_present(self):
        """树中没有 💪🏿💪🏿💪🏿 时返回 None"""
        tree = _make_tree_no_focus()
        result = find_focus_task(tree)
        assert result is None

    def test_find_focus_empty_tree(self):
        """空树返回 None"""
        result = find_focus_task([])
        assert result is None


# ── list_focusable_tasks 测试 ─────────────────────────────────

class TestListFocusableTasks:
    def test_correct_numbering_and_focus_flag(self):
        """编号列表正确，has_focus 标记准确"""
        tree = _make_tree()
        tasks = list_focusable_tasks(tree)

        # paragraph 类型应被排除，所以总共 4 个（Task A, 子任务A1, 子任务A2, Task B）
        assert len(tasks) == 4

        # 编号从 1 开始，连续递增
        for i, t in enumerate(tasks):
            assert t["index"] == i + 1

        # 只有 block-1a 应该有 focus
        focus_tasks = [t for t in tasks if t["has_focus"]]
        assert len(focus_tasks) == 1
        assert focus_tasks[0]["block_id"] == "block-1a"

        # focus 的 title 应该已经去掉了 emoji
        assert FOCUS_EMOJI not in focus_tasks[0]["title"]

    def test_empty_title_excluded(self):
        """空标题的节点不进入列表"""
        tree = [{"id": "e", "title": "", "type": "bulleted_list_item", "children": []}]
        tasks = list_focusable_tasks(tree)
        assert len(tasks) == 0


# ── record_focus_event 测试 ───────────────────────────────────

class TestRecordFocusEvent:
    def test_start_event(self):
        """start 事件正确写入 current_focus"""
        log = _default_focus_log()
        log = record_focus_event(log, "block-1", "Task A", "start")

        assert log["current_focus"] is not None
        assert log["current_focus"]["block_id"] == "block-1"
        assert log["current_focus"]["title"] == "Task A"
        assert "started_at" in log["current_focus"]

    def test_end_event_moves_to_history(self):
        """end 事件将 current_focus 移入 history"""
        log = _default_focus_log()
        log = record_focus_event(log, "block-1", "Task A", "start")
        log = record_focus_event(log, "block-1", "Task A", "end")

        assert log["current_focus"] is None
        assert len(log["history"]) == 1
        assert log["history"][0]["block_id"] == "block-1"
        assert "ended_at" in log["history"][0]

    def test_end_without_current_focus(self):
        """没有 current_focus 时 end 事件不会崩溃"""
        log = _default_focus_log()
        log = record_focus_event(log, "block-1", "Task A", "end")
        assert log["current_focus"] is None
        assert len(log["history"]) == 0

    def test_focus_switch_records_both(self):
        """焦点切换时记录 end + start"""
        log = _default_focus_log()
        log = record_focus_event(log, "block-1", "Task A", "start")
        log = record_focus_event(log, "block-1", "Task A", "end")
        log = record_focus_event(log, "block-2", "Task B", "start")

        assert log["current_focus"]["block_id"] == "block-2"
        assert len(log["history"]) == 1
        assert log["history"][0]["block_id"] == "block-1"


# ── load/save focus_log 测试 ──────────────────────────────────

class TestFocusLogPersistence:
    def test_save_and_load(self, tmp_path):
        """保存后加载应返回相同数据"""
        test_file = str(tmp_path / "focus_log.json")
        log = _default_focus_log()
        log = record_focus_event(log, "b1", "T1", "start")

        with patch("focus_tracker.FOCUS_LOG_FILE", test_file):
            save_focus_log(log)
            loaded = load_focus_log()
            assert loaded["current_focus"]["block_id"] == "b1"

    def test_load_missing_file(self, tmp_path):
        """文件不存在时返回默认结构"""
        test_file = str(tmp_path / "nonexistent.json")
        with patch("focus_tracker.FOCUS_LOG_FILE", test_file):
            log = load_focus_log()
            assert log["current_focus"] is None
            assert log["history"] == []

    def test_load_corrupted_file(self, tmp_path):
        """损坏的 JSON 文件返回默认结构"""
        test_file = str(tmp_path / "bad.json")
        with open(test_file, "w") as f:
            f.write("{broken json")
        with patch("focus_tracker.FOCUS_LOG_FILE", test_file):
            log = load_focus_log()
            assert log["current_focus"] is None


# ── detect_focus_from_livetoday 测试 ──────────────────────────

class TestDetectFocusFromLivetoday:
    """测试从 LIVETODAY 页面检测焦点位置"""

    def _make_notion_block(self, block_type, text):
        """构造一个简单的 Notion block mock"""
        return {
            "type": block_type,
            block_type: {
                "rich_text": [{"plain_text": text}]
            }
        }

    def test_pattern_a_inline_emoji(self):
        """Pattern A: emoji 在任务标题末尾"""
        blocks = [
            self._make_notion_block("heading_2", "By Modes"),
            self._make_notion_block("numbered_list_item", "[1] Task Alpha"),
            self._make_notion_block("numbered_list_item", f"[2] Task Beta {FOCUS_EMOJI}"),
            self._make_notion_block("numbered_list_item", "[3] Task Gamma"),
        ]
        task_index_map = {1: "bid-a", 2: "bid-b", 3: "bid-c"}

        with patch("focus_tracker.get_page_blocks", return_value=blocks):
            result = detect_focus_from_livetoday("page-id", task_index_map)

        assert result is not None
        assert result["block_id"] == "bid-b"
        assert result["title"] == "Task Beta"
        assert result["index"] == 2

    def test_pattern_b_child_block_emoji(self):
        """Pattern B: emoji 作为独立 block 在任务下方"""
        blocks = [
            self._make_notion_block("numbered_list_item", "[1] Task Alpha"),
            self._make_notion_block("numbered_list_item", "[2] Task Beta"),
            self._make_notion_block("paragraph", FOCUS_EMOJI),
            self._make_notion_block("numbered_list_item", "[3] Task Gamma"),
        ]
        task_index_map = {1: "bid-a", 2: "bid-b", 3: "bid-c"}

        with patch("focus_tracker.get_page_blocks", return_value=blocks):
            result = detect_focus_from_livetoday("page-id", task_index_map)

        assert result is not None
        assert result["block_id"] == "bid-b"
        assert result["title"] == "Task Beta"
        assert result["index"] == 2

    def test_no_emoji_found(self):
        """没有 emoji 时返回 None"""
        blocks = [
            self._make_notion_block("numbered_list_item", "[1] Task Alpha"),
            self._make_notion_block("numbered_list_item", "[2] Task Beta"),
        ]
        task_index_map = {1: "bid-a", 2: "bid-b"}

        with patch("focus_tracker.get_page_blocks", return_value=blocks):
            result = detect_focus_from_livetoday("page-id", task_index_map)

        assert result is None

    def test_empty_page(self):
        """空页面返回 None"""
        with patch("focus_tracker.get_page_blocks", return_value=[]):
            result = detect_focus_from_livetoday("page-id", {})

        assert result is None

    def test_emoji_on_first_task(self):
        """emoji 在第一个任务上（Pattern A）"""
        blocks = [
            self._make_notion_block("numbered_list_item", f"[1] First Task {FOCUS_EMOJI}"),
            self._make_notion_block("numbered_list_item", "[2] Second Task"),
        ]
        task_index_map = {1: "bid-first", 2: "bid-second"}

        with patch("focus_tracker.get_page_blocks", return_value=blocks):
            result = detect_focus_from_livetoday("page-id", task_index_map)

        assert result is not None
        assert result["block_id"] == "bid-first"
        assert result["index"] == 1


# ── reset_focus_daily 测试 ────────────────────────────────────

class TestResetFocusDaily:
    def test_same_day_no_reset(self):
        """同一天不触发重置"""
        log = _default_focus_log()
        log["last_reset_date"] = date.today().isoformat()
        log = record_focus_event(log, "b1", "T1", "start")

        updated_log, did_reset = reset_focus_daily(log)
        assert did_reset is False
        assert updated_log["current_focus"] is not None

    def test_new_day_triggers_reset(self):
        """新的一天应触发重置，结束当前焦点"""
        log = _default_focus_log()
        log["last_reset_date"] = "2020-01-01"
        log = record_focus_event(log, "b1", "T1", "start")

        updated_log, did_reset = reset_focus_daily(log)
        assert did_reset is True
        assert updated_log["current_focus"] is None
        assert len(updated_log["history"]) == 1
        assert updated_log["history"][0]["block_id"] == "b1"
        assert updated_log["last_reset_date"] == date.today().isoformat()

    def test_reset_without_current_focus(self):
        """没有当前焦点时重置不会崩溃"""
        log = _default_focus_log()
        log["last_reset_date"] = "2020-01-01"

        updated_log, did_reset = reset_focus_daily(log)
        assert did_reset is True
        assert updated_log["current_focus"] is None
        assert len(updated_log["history"]) == 0
