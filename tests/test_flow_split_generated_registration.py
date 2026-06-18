import unittest
from unittest.mock import patch

from flow_pipeline import _split_dedupe_key, _split_scoped_tasks


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

    def test_split_skips_existing_human_styled_child(self):
        state = [
            {
                "id": "parent-1",
                "notion_block_id": "parent-1",
                "title": "Thesis",
                "original_notion_title": "Thesis",
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
            },
            {
                "id": "manual-1",
                "notion_block_id": "manual-1",
                "title": "Thesis 绘制方法论图",
                "original_notion_title": "🔸 **`Thesis`** `💻Focus` ❓ 绘制方法论图 : *为专家委绘制研究流程详图/。*",
                "context_heading": "",
                "parent_id": "parent-1",
                "depth": 1,
                "type": "todo",
                "notion_type": "to_do",
                "annotations": {},
                "checked": False,
                "has_tag_style": False,
                "is_generated": False,
                "origin": "human",
                "split_stage": "none",
                "wbs_level": 4,
                "tags": {},
            },
        ]
        structured_cfg = {
            "themes": {"Thesis": {"color": "default", "sub_themes": []}},
            "modes": [{"mode_name": "Focus"}],
        }
        scoped_ids = {"parent-1"}

        with patch("flow_pipeline.clean_task_title", side_effect=lambda title, _cfg: str(title).replace("Thesis", "").replace("Focus", "")), patch(
            "flow_pipeline.build_split_context", return_value={}
        ), patch("flow_pipeline.split_task", return_value=["绘制方法论图 : 为专家委绘制研究流程详图"]), patch(
            "flow_pipeline.push_subtasks_to_notion",
            return_value=[{"id": "child-1", "title": "绘制方法论图 : 为专家委绘制研究流程详图"}],
        ) as push_mock:
            parent_count, subtask_count = _split_scoped_tasks(state, structured_cfg, scoped_ids)

        self.assertEqual(0, parent_count)
        self.assertEqual(0, subtask_count)
        push_mock.assert_not_called()

    def test_split_dedupe_key_ignores_theme_and_wbs_prefixes(self):
        structured_cfg = {
            "themes": {
                "PhDSettle": {
                    "color": "red",
                    "sub_themes": ["Thesis"],
                }
            },
            "modes": [],
        }

        styled = _split_dedupe_key(
            "🔶 Thesis 🟧 V&V 协议 : 验证结果(准确/可靠/显著)的标准与逻辑测试",
            structured_cfg,
        )
        generated = _split_dedupe_key(
            "V&V 协议 : 确保研究结果(内部效度, 信度, 可信度)的标准与流程。",
            structured_cfg,
        )

        self.assertEqual("v&v 协议", styled)
        self.assertEqual(styled, generated)

    def test_reviewed_generated_non_l4_can_continue_splitting(self):
        state = [
            {
                "id": "generated-l3",
                "notion_block_id": "generated-l3",
                "title": "Thesis Research Gap source mapping",
                "original_notion_title": "Research Gap source mapping",
                "context_heading": "",
                "parent_id": "parent-1",
                "depth": 1,
                "type": "bullet",
                "notion_type": "bulleted_list_item",
                "annotations": {},
                "checked": None,
                "has_tag_style": False,
                "is_generated": True,
                "origin": "generated",
                "generated_selection_processed": True,
                "split_stage": "none",
                "wbs_level": 3,
                "tags": {},
            }
        ]
        structured_cfg = {"themes": {}}
        scoped_ids = {"generated-l3"}

        with patch("flow_pipeline.clean_task_title", return_value="Research Gap source mapping"), patch(
            "flow_pipeline.build_split_context", return_value={}
        ), patch("flow_pipeline.split_task", return_value=["extract paper gap claims"]), patch(
            "flow_pipeline.push_subtasks_to_notion",
            return_value=[{"id": "generated-l4", "title": "extract paper gap claims"}],
        ):
            parent_count, subtask_count = _split_scoped_tasks(state, structured_cfg, scoped_ids)

        self.assertEqual(1, parent_count)
        self.assertEqual(1, subtask_count)
        self.assertEqual("suggested", state[0]["split_stage"])

    def test_unreviewed_generated_non_l4_still_waits_for_review(self):
        state = [
            {
                "id": "generated-l3",
                "notion_block_id": "generated-l3",
                "title": "Thesis Research Gap source mapping",
                "original_notion_title": "Research Gap source mapping",
                "context_heading": "",
                "parent_id": "parent-1",
                "depth": 1,
                "type": "todo",
                "notion_type": "to_do",
                "annotations": {},
                "checked": False,
                "has_tag_style": False,
                "is_generated": True,
                "origin": "generated",
                "generated_selection_processed": False,
                "split_stage": "none",
                "wbs_level": 3,
                "tags": {},
            }
        ]
        structured_cfg = {"themes": {}}
        scoped_ids = {"generated-l3"}

        with patch("flow_pipeline.split_task", return_value=["extract paper gap claims"]) as split_mock:
            parent_count, subtask_count = _split_scoped_tasks(state, structured_cfg, scoped_ids)

        self.assertEqual(0, parent_count)
        self.assertEqual(0, subtask_count)
        split_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
