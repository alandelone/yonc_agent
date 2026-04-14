import unittest
from unittest.mock import patch

from sync_engine import push_tags_to_notion


def _config():
    return {
        "Task Theme with colour": [{"text": "Maker Sprint|Design", "color": "blue"}],
        "Modes": [],
        "WBS level": ["1️⃣ | Level 1", "2️⃣ | Level 2", "3️⃣ | Level 3", "4️⃣ | Level 4"],
        "Priority": ["🔥 | P1"],
    }


class TestReviewedStageTransitions(unittest.TestCase):
    def test_checked_generated_non_l4_converts_to_bullet(self):
        state = [
            {
                "id": "g1",
                "notion_block_id": "g1",
                "type": "todo",
                "notion_type": "to_do",
                "title": "Maker Sprint task",
                "original_notion_title": "task",
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                    "WBS level": "3️⃣ | Level 3",
                },
                "wbs_level": 3,
                "parent_id": "p1",
                "checked": True,
                "is_generated": True,
                "origin": "generated",
            }
        ]

        with patch("notion_client.replace_with_bullet", return_value={"id": "new-bullet"}) as mock_bullet, \
             patch("notion_client.update_block", return_value={}), \
             patch("notion_client.delete_block", return_value={}):
            push_tags_to_notion(state, _config())

        self.assertTrue(mock_bullet.called)
        self.assertEqual("bullet", state[0]["type"])

    def test_unchecked_generated_todo_is_deleted(self):
        """selection_mode 需要同组至少 1 个 checked generated to_do 才激活。
        添加 checked sibling 满足阈值，验证 unchecked 的被删除。"""
        state = [
            {
                "id": "g2",
                "notion_block_id": "g2",
                "type": "todo",
                "notion_type": "to_do",
                "title": "Maker Sprint task",
                "original_notion_title": "task",
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                    "WBS level": "2️⃣ | Level 2",
                },
                "wbs_level": 2,
                "parent_id": "p1",
                "checked": False,
                "is_generated": True,
                "origin": "generated",
            },
            {
                "id": "g2-sibling",
                "notion_block_id": "g2-sibling",
                "type": "todo",
                "notion_type": "to_do",
                "title": "Maker Sprint sibling",
                "original_notion_title": "sibling",
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                    "WBS level": "2️⃣ | Level 2",
                },
                "wbs_level": 2,
                "parent_id": "p1",
                "checked": True,
                "is_generated": True,
                "origin": "generated",
            },
        ]

        with patch("notion_client.delete_block", return_value={}) as mock_delete, \
             patch("notion_client.update_block", return_value={}), \
             patch("notion_client.replace_with_bullet", return_value={"id": "new-bullet"}):
            push_tags_to_notion(state, _config())

        self.assertTrue(mock_delete.called)
        self.assertTrue(state[0].get("deleted"))

    def test_checked_generated_l4_resets_to_unchecked(self):
        state = [
            {
                "id": "g3",
                "notion_block_id": "g3",
                "type": "todo",
                "notion_type": "to_do",
                "title": "Maker Sprint task",
                "original_notion_title": "task",
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                    "WBS level": "4️⃣ | Level 4",
                },
                "wbs_level": 4,
                "parent_id": "p1",
                "checked": True,
                "is_generated": True,
                "origin": "generated",
            }
        ]

        with patch("notion_client.update_block", return_value={}) as mock_update, patch(
            "notion_client.replace_with_bullet", return_value={"id": "new-bullet"}
        ) as mock_bullet:
            push_tags_to_notion(state, _config())

        self.assertFalse(mock_bullet.called)
        payload = mock_update.call_args.args[1]
        self.assertIn("to_do", payload)
        self.assertFalse(payload["to_do"]["checked"])


if __name__ == "__main__":
    unittest.main()
