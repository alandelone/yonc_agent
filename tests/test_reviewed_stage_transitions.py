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
                "generated_selection_processed": False,
            }
        ]

        with patch("notion_client.replace_with_bullet", return_value={"id": "new-bullet"}) as mock_bullet, \
             patch("notion_client.update_block", return_value={}), \
             patch("notion_client.delete_block", return_value={}):
            push_tags_to_notion(state, _config())

        self.assertTrue(mock_bullet.called)
        self.assertEqual("bullet", state[0]["type"])

    def test_manual_unchecked_non_l4_todo_converts_to_bullet(self):
        state = [
            {
                "id": "manual-l2",
                "notion_block_id": "manual-l2",
                "type": "todo",
                "notion_type": "to_do",
                "title": "Maker Sprint manually keyed module",
                "original_notion_title": "manually keyed module",
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                    "WBS level": "2锔忊儯 | Level 2",
                },
                "wbs_level": 2,
                "parent_id": "p1",
                "checked": False,
                "is_generated": False,
                "origin": "human",
                "generated_selection_processed": False,
            }
        ]

        with patch("notion_client.replace_with_bullet", return_value={"id": "new-bullet"}) as mock_bullet, \
             patch("notion_client.update_block", return_value={}), \
             patch("notion_client.delete_block", return_value={}):
            push_tags_to_notion(state, _config())

        self.assertTrue(mock_bullet.called)
        self.assertEqual("bullet", state[0]["type"])
        self.assertEqual("bulleted_list_item", state[0]["notion_type"])
        self.assertIsNone(state[0]["checked"])

    def test_manual_non_l4_todo_conversion_preserves_children(self):
        state = [
            {
                "id": "manual-l2",
                "notion_block_id": "manual-l2",
                "type": "todo",
                "notion_type": "to_do",
                "title": "Maker Sprint manually keyed module",
                "original_notion_title": "manually keyed module",
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                    "WBS level": "2 | Level 2",
                },
                "wbs_level": 2,
                "parent_id": "p1",
                "checked": False,
                "is_generated": False,
                "origin": "human",
                "generated_selection_processed": False,
            },
            {
                "id": "child-quote",
                "notion_block_id": "child-quote",
                "type": "quote",
                "notion_type": "quote",
                "title": "manual note",
                "original_notion_title": "manual note",
                "parent_id": "manual-l2",
                "checked": None,
                "annotations": {"color": "default"},
                "tags": {},
            },
        ]

        with patch("notion_client.replace_with_bullet", return_value={"id": "new-bullet"}) as mock_bullet, \
             patch("notion_client.update_block", return_value={}), \
             patch("notion_client.delete_block", return_value={}):
            push_tags_to_notion(state, _config())

        self.assertTrue(mock_bullet.called)
        self.assertEqual("new-bullet", state[1]["parent_id"])
        kwargs = mock_bullet.call_args.kwargs
        self.assertEqual("manual note", kwargs["children"][0]["quote"]["rich_text"][0]["text"]["content"])

    def test_rendered_title_restores_matching_rich_text_link(self):
        state = [
            {
                "id": "linked-l2",
                "notion_block_id": "linked-l2",
                "type": "bullet",
                "notion_type": "bulleted_list_item",
                "title": "Maker Sprint report flow : data to report direct",
                "original_notion_title": "report flow : data to report direct",
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                    "WBS level": "2 | Level 2",
                },
                "wbs_level": 2,
                "parent_id": "p1",
                "checked": None,
                "is_generated": False,
                "origin": "human",
                "generated_selection_processed": False,
                "links": [{"text": "data to report direct", "url": "https://example.com/report"}],
            }
        ]

        with patch("notion_client.update_block", return_value={}) as mock_update, \
             patch("notion_client.replace_with_bullet", return_value={"id": "new-bullet"}), \
             patch("notion_client.delete_block", return_value={}):
            push_tags_to_notion(state, _config())

        rich_text = mock_update.call_args.args[1]["bulleted_list_item"]["rich_text"]
        linked = [rt for rt in rich_text if rt.get("text", {}).get("link")]
        self.assertEqual("https://example.com/report", linked[0]["text"]["link"]["url"])

    def test_quote_content_block_is_not_formatted(self):
        state = [
            {
                "id": "quote-1",
                "notion_block_id": "quote-1",
                "type": "quote",
                "notion_type": "quote",
                "title": "Format Cute Manual",
                "original_notion_title": "Format Cute Manual",
                "parent_id": "p1",
                "is_content_block": True,
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                    "WBS level": "2 | Level 2",
                },
            }
        ]

        with patch("notion_client.update_block", return_value={}) as mock_update, \
             patch("notion_client.replace_with_bullet", return_value={"id": "new-bullet"}), \
             patch("notion_client.delete_block", return_value={}):
            push_tags_to_notion(state, _config())

        mock_update.assert_not_called()

    def test_manual_checked_non_l4_todo_converts_to_bullet(self):
        state = [
            {
                "id": "manual-checked-l3",
                "notion_block_id": "manual-checked-l3",
                "type": "todo",
                "notion_type": "to_do",
                "title": "Maker Sprint manually checked package",
                "original_notion_title": "manually checked package",
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                    "WBS level": "3锔忊儯 | Level 3",
                },
                "wbs_level": 3,
                "parent_id": "p1",
                "checked": True,
                "is_generated": False,
                "origin": "human",
                "generated_selection_processed": False,
            }
        ]

        with patch("notion_client.replace_with_bullet", return_value={"id": "new-bullet"}) as mock_bullet, \
             patch("notion_client.update_block", return_value={}), \
             patch("notion_client.delete_block", return_value={}):
            push_tags_to_notion(state, _config())

        self.assertTrue(mock_bullet.called)
        self.assertEqual("bullet", state[0]["type"])
        self.assertEqual("bulleted_list_item", state[0]["notion_type"])
        self.assertIsNone(state[0]["checked"])

    def test_processed_generated_non_l4_checked_converts_without_done_style(self):
        state = [
            {
                "id": "generated-processed-l3",
                "notion_block_id": "generated-processed-l3",
                "type": "todo",
                "notion_type": "to_do",
                "title": "Maker Sprint reviewed package",
                "original_notion_title": "reviewed package",
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                    "WBS level": "3 | Level 3",
                },
                "wbs_level": 3,
                "parent_id": "p1",
                "checked": True,
                "is_generated": True,
                "origin": "generated",
                "generated_selection_processed": True,
            }
        ]

        with patch("notion_client.replace_with_bullet", return_value={"id": "new-bullet"}) as mock_bullet, \
             patch("notion_client.update_block", return_value={}), \
             patch("notion_client.delete_block", return_value={}):
            push_tags_to_notion(state, _config())

        self.assertTrue(mock_bullet.called)
        self.assertIsNone(state[0]["checked"])
        self.assertEqual("bullet", state[0]["type"])
        rich_text = mock_bullet.call_args.args[2]
        self.assertFalse(any(rt.get("annotations", {}).get("strikethrough") for rt in rich_text))
        self.assertNotEqual("gray", mock_bullet.call_args.kwargs.get("color"))

    def test_unreviewed_unchecked_generated_non_l4_todo_waits_for_selection(self):
        state = [
            {
                "id": "generated-l2",
                "notion_block_id": "generated-l2",
                "type": "todo",
                "notion_type": "to_do",
                "title": "Maker Sprint generated module",
                "original_notion_title": "generated module",
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                    "WBS level": "2锔忊儯 | Level 2",
                },
                "wbs_level": 2,
                "parent_id": "p1",
                "checked": False,
                "is_generated": True,
                "origin": "generated",
                "generated_selection_processed": False,
            }
        ]

        with patch("notion_client.replace_with_bullet", return_value={"id": "new-bullet"}) as mock_bullet, \
             patch("notion_client.update_block", return_value={}) as mock_update, \
             patch("notion_client.delete_block", return_value={}) as mock_delete:
            push_tags_to_notion(state, _config())

        self.assertFalse(mock_bullet.called)
        self.assertFalse(mock_update.called)
        self.assertFalse(mock_delete.called)
        self.assertEqual("todo", state[0]["type"])

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
                "generated_selection_processed": False,
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
                "generated_selection_processed": False,
            },
        ]

        with patch("notion_client.delete_block", return_value={}) as mock_delete, \
             patch("notion_client.update_block", return_value={}), \
             patch("notion_client.replace_with_bullet", return_value={"id": "new-bullet"}):
            push_tags_to_notion(state, _config())

        self.assertTrue(mock_delete.called)
        self.assertTrue(state[0].get("deleted"))

    def test_edited_checked_generated_selector_still_deletes_unchecked_sibling(self):
        state = [
            {
                "id": "g2-unchecked",
                "notion_block_id": "g2-unchecked",
                "type": "todo",
                "notion_type": "to_do",
                "title": "Maker Sprint unchecked option",
                "original_notion_title": "unchecked option",
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                    "WBS level": "3锔忊儯 | Level 3",
                },
                "wbs_level": 3,
                "parent_id": "p1",
                "checked": False,
                "is_generated": True,
                "origin": "generated",
                "generated_selection_processed": False,
            },
            {
                "id": "g2-edited",
                "notion_block_id": "g2-edited",
                "type": "todo",
                "notion_type": "to_do",
                "title": "Maker Sprint edited selected option",
                "original_notion_title": "edited selected option after manual text change",
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                    "WBS level": "3锔忊儯 | Level 3",
                },
                "wbs_level": 3,
                "parent_id": "p1",
                "checked": True,
                "is_generated": True,
                "origin": "generated",
                "generated_selection_processed": False,
            },
        ]

        with patch("notion_client.delete_block", return_value={}) as mock_delete, \
             patch("notion_client.update_block", return_value={}), \
             patch("notion_client.replace_with_bullet", return_value={"id": "new-bullet"}) as mock_bullet:
            push_tags_to_notion(state, _config())

        self.assertTrue(mock_delete.called)
        self.assertTrue(mock_bullet.called)
        self.assertTrue(state[0].get("deleted"))
        self.assertEqual("bullet", state[1]["type"])

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
                "generated_selection_processed": False,
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
        self.assertTrue(state[0].get("generated_selection_processed"))

    def test_processed_generated_l4_is_not_deleted_even_when_sibling_is_checked(self):
        state = [
            {
                "id": "g4",
                "notion_block_id": "g4",
                "type": "todo",
                "notion_type": "to_do",
                "title": "Maker Sprint task",
                "original_notion_title": "task",
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                    "WBS level": "4锔忊儯 | Level 4",
                },
                "wbs_level": 4,
                "parent_id": "p1",
                "checked": False,
                "is_generated": True,
                "origin": "generated",
                "generated_selection_processed": True,
            },
            {
                "id": "g4-sibling",
                "notion_block_id": "g4-sibling",
                "type": "todo",
                "notion_type": "to_do",
                "title": "Maker Sprint sibling",
                "original_notion_title": "sibling",
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                    "WBS level": "4锔忊儯 | Level 4",
                },
                "wbs_level": 4,
                "parent_id": "p1",
                "checked": True,
                "is_generated": True,
                "origin": "generated",
                "generated_selection_processed": False,
            },
        ]

        with patch("notion_client.delete_block", return_value={}) as mock_delete, \
             patch("notion_client.update_block", return_value={}), \
             patch("notion_client.replace_with_bullet", return_value={"id": "new-bullet"}):
            push_tags_to_notion(state, _config())

        self.assertFalse(state[0].get("deleted", False))
        self.assertTrue(state[0].get("generated_selection_processed"))
        self.assertFalse(mock_delete.called)

    def test_processed_generated_l4_rehydrates_wbs_level_tag(self):
        state = [
            {
                "id": "g5",
                "notion_block_id": "g5",
                "type": "todo",
                "notion_type": "to_do",
                "title": "Maker Sprint task",
                "original_notion_title": "task",
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                },
                "wbs_level": 4,
                "parent_id": "p1",
                "checked": False,
                "is_generated": True,
                "origin": "generated",
                "generated_selection_processed": True,
            }
        ]

        with patch("notion_client.delete_block", return_value={}), \
             patch("notion_client.update_block", return_value={}) as mock_update, \
             patch("notion_client.replace_with_bullet", return_value={"id": "new-bullet"}):
            push_tags_to_notion(state, _config())

        self.assertIn("WBS level", state[0].get("tags", {}))
        self.assertIn("Level 4", state[0]["tags"]["WBS level"])
        self.assertTrue(mock_update.called)
        payload = mock_update.call_args.args[1]
        self.assertIn("to_do", payload)

    def test_freshly_selected_generated_l4_rehydrates_wbs_before_mode_render(self):
        config = {
            "Task Theme with colour": [{"text": "Maker Sprint|Design", "color": "blue"}],
            "Modes": ["Lv3  Focus  Focused execution mode"],
            "Task Type": ["🔍 | Testing"],
            "WBS level": ["1️⃣ | Level 1", "2️⃣ | Level 2", "3️⃣ | Level 3", "4️⃣ | Level 4"],
            "Priority": [],
        }
        state = [
            {
                "id": "g-selected",
                "notion_block_id": "g-selected",
                "type": "todo",
                "notion_type": "to_do",
                "title": "Maker Sprint selected task",
                "original_notion_title": "selected task",
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                    "Modes": "Focus",
                    "Task Type": "🔍 | Testing",
                },
                "wbs_level": 4,
                "parent_id": "p1",
                "checked": True,
                "is_generated": True,
                "origin": "generated",
                "generated_selection_processed": False,
                "timeliner_rank": 1,
            }
        ]

        with patch("notion_client.delete_block", return_value={}), \
             patch("notion_client.update_block", return_value={}) as mock_update, \
             patch("notion_client.replace_with_bullet", return_value={"id": "new-bullet"}):
            push_tags_to_notion(state, config)

        self.assertIn("WBS level", state[0].get("tags", {}))
        self.assertIn("Level 4", state[0]["tags"]["WBS level"])
        self.assertTrue(state[0].get("generated_selection_processed"))
        payload = mock_update.call_args.args[1]
        rendered = "".join(seg.get("text", {}).get("content", "") for seg in payload["to_do"]["rich_text"])
        self.assertTrue(rendered.startswith("4️⃣ "))
        self.assertIn("Focus", rendered)
        self.assertIn("🔍", rendered)

    def test_scoped_processed_generated_l4_renders_modes_and_task_type(self):
        config = {
            "Task Theme with colour": [{"text": "Maker Sprint|Design", "color": "blue"}],
            "Modes": ["Lv3  Focus  Focused execution mode"],
            "Task Type": ["🔍 | Testing"],
            "WBS level": ["1️⃣ | Level 1", "2️⃣ | Level 2", "3️⃣ | Level 3", "4️⃣ | Level 4"],
            "Priority": ["🔥 | P1"],
        }
        state = [
            {
                "id": "g6",
                "notion_block_id": "g6",
                "type": "todo",
                "notion_type": "to_do",
                "title": "Maker Sprint task",
                "original_notion_title": "task",
                "tags": {
                    "Task Theme with colour": "Maker Sprint|Design",
                    "WBS level": "4️⃣ | Level 4",
                    "Modes": "Focus",
                    "Task Type": "🔍 | Testing",
                },
                "wbs_level": 4,
                "parent_id": "p1",
                "checked": False,
                "is_generated": True,
                "origin": "generated",
                "generated_selection_processed": True,
                "timeliner_rank": 1,
            }
        ]

        with patch("notion_client.delete_block", return_value={}), \
             patch("notion_client.update_block", return_value={}) as mock_update, \
             patch("notion_client.replace_with_bullet", return_value={"id": "new-bullet"}):
            push_tags_to_notion(state, config)

        self.assertTrue(mock_update.called)
        payload = mock_update.call_args.args[1]
        rich_text = payload["to_do"]["rich_text"]
        rendered = "".join(seg.get("text", {}).get("content", "") for seg in rich_text)
        self.assertIn("Focus", rendered)
        self.assertIn("🔍", rendered)


if __name__ == "__main__":
    unittest.main()
