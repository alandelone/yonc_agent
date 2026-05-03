import unittest
from unittest.mock import patch

from flow_pipeline import _split_scoped_tasks


class TestSplitGeneratedRegistration(unittest.TestCase):
    def test_split_created_subtask_is_registered_as_generated(self):
        state = [
            {
                "id": "parent-1",
                "notion_block_id": "parent-1",
                "title": "Parent Task",
                "original_notion_title": "Parent Task",
                "context_heading": "",
                "parent_id": "page-root",
                "depth": 0,
                "type": "bullet",
                "notion_type": "bulleted_list_item",
                "annotations": {},
                "checked": None,
                "has_tag_style": False,
                "is_generated": False,
                "origin": "human",
                "split_stage": "none",
                "wbs_level": 2,
                "tags": {},
            }
        ]
        structured_cfg = {"themes": {}}
        scoped_ids = {"parent-1"}

        with patch("flow_pipeline.clean_task_title", return_value="Parent Task"), patch(
            "flow_pipeline.build_split_context", return_value={}
        ), patch("flow_pipeline.split_task", return_value=["child task"]), patch(
            "flow_pipeline.push_subtasks_to_notion",
            return_value=[{"id": "child-1", "title": "child task"}],
        ):
            parent_count, subtask_count = _split_scoped_tasks(state, structured_cfg, scoped_ids)

        self.assertEqual(1, parent_count)
        self.assertEqual(1, subtask_count)

        inserted = next((t for t in state if t.get("notion_block_id") == "child-1"), None)
        self.assertIsNotNone(inserted)
        self.assertTrue(inserted.get("is_generated"))
        self.assertEqual("generated", inserted.get("origin"))
        self.assertEqual("to_do", inserted.get("notion_type"))


if __name__ == "__main__":
    unittest.main()
