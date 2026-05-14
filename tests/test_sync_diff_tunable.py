import unittest
from unittest.mock import patch

from sync_engine import compute_diff


class TestSyncDiffTunableLogging(unittest.TestCase):
    def test_human_task_update_does_not_log_tunable_conflict(self):
        current_state = [
            {
                "notion_block_id": "task-human",
                "title": "Draft report",
                "checked": False,
                "is_generated": False,
                "origin": "human",
            }
        ]
        new_notion_state = [
            {
                "notion_block_id": "task-human",
                "title": "Draft report v2",
                "checked": True,
            }
        ]

        with patch("sync_engine.log_conflict") as mock_log:
            diff = compute_diff(current_state, new_notion_state)

        self.assertEqual(1, len(diff["changes"]))
        self.assertFalse(mock_log.called)

    def test_generated_task_update_logs_tunable_conflict(self):
        current_state = [
            {
                "notion_block_id": "task-generated",
                "title": "LLM suggestion",
                "checked": False,
                "is_generated": True,
                "origin": "generated",
            }
        ]
        new_notion_state = [
            {
                "notion_block_id": "task-generated",
                "title": "Human refined suggestion",
                "checked": True,
            }
        ]

        with patch("sync_engine.log_conflict") as mock_log:
            diff = compute_diff(current_state, new_notion_state)

        self.assertEqual(1, len(diff["changes"]))
        self.assertEqual(2, mock_log.call_count)


if __name__ == "__main__":
    unittest.main()
