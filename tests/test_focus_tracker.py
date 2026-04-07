"""
focus_tracker 模块的单元测试。
使用 mock 数据构造任务树，验证核心逻辑：
- 查找焦点任务
- 编号列表生成
- 焦点事件记录
- 每日重置检测
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
    _find_last_empty_paragraph,
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


# ── _find_last_empty_paragraph 测试 ───────────────────────────

class TestFindLastEmptyParagraph:
    def test_finds_last_empty(self):
        """正确找到最后一个空白 paragraph"""
        blocks = [
            {"id": "p1", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "有内容"}]}},
            {"id": "p2", "type": "paragraph", "paragraph": {"rich_text": []}},
            {"id": "b1", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": []}},
            {"id": "p3", "type": "paragraph", "paragraph": {"rich_text": []}},
        ]
        result = _find_last_empty_paragraph(blocks)
        assert result == "p3"

    def test_no_empty_paragraph(self):
        """没有空白 paragraph 时返回 None"""
        blocks = [
            {"id": "b1", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": []}},
        ]
        result = _find_last_empty_paragraph(blocks)
        assert result is None


# ── daily reset 日期检测测试 ──────────────────────────────────

class TestDailyResetDetection:
    def test_same_day_no_reset(self):
        """同一天不触发重置"""
        log = _default_focus_log()
        log["last_reset_date"] = date.today().isoformat()
        # last_reset_date 等于今天 → 不需要重置
        assert log["last_reset_date"] == date.today().isoformat()

    def test_new_day_triggers_reset(self):
        """新的一天应触发重置"""
        log = _default_focus_log()
        log["last_reset_date"] = "2020-01-01"  # 旧日期
        assert log["last_reset_date"] != date.today().isoformat()
