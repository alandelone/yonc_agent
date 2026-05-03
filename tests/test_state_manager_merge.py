import sys
import unittest
from pathlib import Path

# Ensure repo root is on sys.path for local imports
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from state_manager import merge_states


class TestMergeStates(unittest.TestCase):
    def test_preserves_synced_tags_for_existing_block(self):
        notion_tree = [
            {
                "id": "task-1",
                "title": "Task One",
                "type": "bulleted_list_item",
                "depth": 0,
                "parent_id": "page-root",
                "annotations": {},
                "checked": None,
                "children": [],
            }
        ]
        local_state = [
            {
                "id": "task-1",
                "notion_block_id": "task-1",
                "title": "Task One",
                "original_notion_title": "Task One",
                "context_heading": "",
                "parent_id": "page-root",
                "depth": 0,
                "wbs_level": 2,
                "type": "bullet",
                "notion_type": "bulleted_list_item",
                "annotations": {},
                "checked": None,
                "has_tag_style": False,
                "created_by_id": "",
                "last_edited_by_id": "",
                "is_generated": False,
                "origin": "human",
                "tags": {"Task Theme with colour": "Maker Main"},
                "status": "todo",
                "metrics": {
                    "estimated_time_h": 1.5,
                    "actual_time_taken_h": 0.5,
                    "interruption_count": 1,
                },
                "synced_tags": True,
            }
        ]

        merged = merge_states(notion_tree, local_state)
        self.assertEqual(1, len(merged))
        self.assertTrue(merged[0].get("synced_tags"))

    def test_new_block_defaults_to_unsynced(self):
        notion_tree = [
            {
                "id": "task-new",
                "title": "Task New",
                "type": "bulleted_list_item",
                "depth": 0,
                "parent_id": "page-root",
                "annotations": {},
                "checked": None,
                "children": [],
            }
        ]

        merged = merge_states(notion_tree, [])
        self.assertEqual(1, len(merged))
        self.assertFalse(merged[0].get("synced_tags", False))

    def test_preserves_local_generated_flags(self):
        notion_tree = [
            {
                "id": "task-generated",
                "title": "Task Generated",
                "type": "to_do",
                "depth": 1,
                "parent_id": "task-parent",
                "annotations": {},
                "checked": False,
                "children": [],
            }
        ]
        local_state = [
            {
                "id": "task-generated",
                "notion_block_id": "task-generated",
                "title": "Task Parent Task Generated",
                "original_notion_title": "Task Generated",
                "context_heading": "",
                "parent_id": "task-parent",
                "depth": 1,
                "wbs_level": None,
                "type": "todo",
                "notion_type": "to_do",
                "annotations": {},
                "checked": False,
                "has_tag_style": False,
                "created_by_id": "",
                "last_edited_by_id": "",
                "is_generated": True,
                "origin": "generated",
                "tags": {},
                "status": "todo",
                "metrics": {
                    "estimated_time_h": None,
                    "actual_time_taken_h": None,
                    "interruption_count": 0,
                },
            }
        ]

        merged = merge_states(notion_tree, local_state)
        self.assertEqual(1, len(merged))
        self.assertTrue(merged[0].get("is_generated"))
        self.assertEqual("generated", merged[0].get("origin"))


if __name__ == "__main__":
    unittest.main()
