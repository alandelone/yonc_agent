import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure repo root is on sys.path for local imports
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sync_engine import push_tags_to_notion


def _raw_config():
    return {
        "Task Theme with colour": [
            {"text": "鍛造Lab DZaoSpaceV1|鍛造Maker", "color": "blue"},
        ],
        "Modes": [],
        "WBS level": [],
    }


class TestPushSyncFormattingRules(unittest.TestCase):
    def test_uses_subtheme_from_flattened_ancestor_prefix(self):
        state = [
            {
                "id": "t-1",
                "notion_block_id": "t-1",
                "type": "bullet",
                "notion_type": "bulleted_list_item",
                "title": "鍛造Lab DZaoSpaceV1 phase 1 mini pellet loop",
                "original_notion_title": "phase 1 mini pellet loop",
                "tags": {
                    "Task Theme with colour": "鍛造Lab DZaoSpaceV1|鍛造Maker",
                },
                "depth": 1,
                "parent_id": "p-1",
                "checked": None,
            }
        ]

        with patch("notion_client.update_block", return_value={}) as mock_update:
            push_tags_to_notion(state, _raw_config())

        rich_text = mock_update.call_args.args[1]["bulleted_list_item"]["rich_text"]
        self.assertEqual("DZaoSpaceV1", rich_text[0]["text"]["content"])

    def test_formats_description_as_gray_italic_after_colon(self):
        state = [
            {
                "id": "t-2",
                "notion_block_id": "t-2",
                "type": "bullet",
                "notion_type": "bulleted_list_item",
                "title": "鍛造Maker 3dpF Setup Extruder : existing BOM only",
                "original_notion_title": "Setup Extruder : existing BOM only",
                "tags": {
                    "Task Theme with colour": "鍛造Lab DZaoSpaceV1|鍛造Maker",
                },
                "depth": 1,
                "parent_id": "p-2",
                "checked": None,
            }
        ]

        with patch("notion_client.update_block", return_value={}) as mock_update:
            push_tags_to_notion(state, _raw_config())

        rich_text = mock_update.call_args.args[1]["bulleted_list_item"]["rich_text"]
        desc_segment = [rt for rt in rich_text if "existing BOM only" in rt["text"]["content"]]
        self.assertTrue(desc_segment, "Description segment not found in rich_text.")
        self.assertTrue(desc_segment[0]["annotations"].get("italic"))
        self.assertEqual("gray", desc_segment[0]["annotations"].get("color"))

    def test_compacts_long_title_via_llm_instead_of_toggle_conversion(self):
        """当标题 word count 超过限制时，应通过 LLM 压缩描述部分而非转换为 toggle。"""
        long_desc = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen"
        long_text = f"Setup Extruder : {long_desc}"
        state = [
            {
                "id": "t-3",
                "notion_block_id": "t-3",
                "type": "bullet",
                "notion_type": "bulleted_list_item",
                "title": f"鍛造Maker 3dpF {long_text}",
                "original_notion_title": long_text,
                "tags": {
                    "Task Theme with colour": "鍛造Lab DZaoSpaceV1|鍛造Maker",
                },
                "depth": 1,
                "parent_id": "p-3",
                "checked": None,
            }
        ]

        with patch("notion_client.update_block", return_value={}) as mock_update, \
             patch("llm_pipeline._condense_description", return_value="compacted desc") as mock_condense:
            push_tags_to_notion(state, _raw_config())

        # 应该走 update_block 而不是 replace_with_toggle_item
        self.assertTrue(mock_update.called, "Long title should be updated in-place, not converted to toggle.")
        # LLM 压缩应被调用
        self.assertTrue(mock_condense.called, "LLM _condense_description should be called for overflow title.")


    def test_does_not_render_stale_wbs_emoji_without_wbs_tag(self):
        config = {
            "Task Theme with colour": [{"text": "Thesis", "color": "blue"}],
            "Modes": [],
            "WBS level": ["\U0001f3ed | Thesis"],
        }
        state = [
            {
                "id": "t-4",
                "notion_block_id": "t-4",
                "type": "bullet",
                "notion_type": "bulleted_list_item",
                "title": "\U0001f3ed Thesis Phd RsPlan : Diversed Parallel Assisted Pushing",
                "original_notion_title": "\U0001f3ed Thesis Phd RsPlan : Diversed Parallel Assisted Pushing",
                "tags": {
                    "Task Theme with colour": "Thesis",
                },
                "wbs_level": None,
                "depth": 0,
                "checked": None,
            }
        ]

        with patch("notion_client.update_block", return_value={}) as mock_update:
            push_tags_to_notion(state, config)

        rich_text = mock_update.call_args.args[1]["bulleted_list_item"]["rich_text"]
        rendered = "".join(rt.get("text", {}).get("content", "") for rt in rich_text)
        self.assertNotIn("\U0001f3ed", rendered)

    def test_does_not_mark_parent_complete_when_child_is_unprocessed_selector(self):
        config = {
            "Task Theme with colour": [{"text": "Thesis", "color": "blue"}],
            "Modes": [],
            "WBS level": ["3️⃣ | Level 3", "4️⃣ | Level 4"],
        }
        state = [
            {
                "id": "parent-1",
                "notion_block_id": "parent-1",
                "type": "bullet",
                "notion_type": "bulleted_list_item",
                "title": "Thesis 🔶 Parent Task : description",
                "original_notion_title": "🔶 Parent Task : description",
                "tags": {
                    "Task Theme with colour": "Thesis",
                    "WBS level": "3️⃣ | Level 3",
                },
                "wbs_level": 3,
                "depth": 1,
                "checked": None,
                "origin": "human",
                "split_stage": "suggested",
                "synced_tags": False,
            },
            {
                "id": "child-1",
                "notion_block_id": "child-1",
                "type": "todo",
                "notion_type": "to_do",
                "title": "Thesis 🔶 Parent Task 🤖💬🔜Child Task",
                "original_notion_title": "🤖💬🔜Child Task",
                "tags": {
                    "WBS level": "4️⃣ | Level 4",
                },
                "wbs_level": 4,
                "depth": 2,
                "parent_id": "parent-1",
                "checked": True,
                "is_generated": True,
                "generated_selection_processed": False,
            }
        ]

        with patch("notion_client.update_block", return_value={}) as mock_update:
            push_tags_to_notion(state, config)

        parent_calls = [
            call for call in mock_update.call_args_list 
            if call.args[0] == "parent-1"
        ]
        if parent_calls:
            rich_text = parent_calls[0].args[1]["bulleted_list_item"]["rich_text"]
            rendered = "".join(rt.get("text", {}).get("content", "") for rt in rich_text)
            self.assertNotIn("💯✅", rendered)


if __name__ == "__main__":
    unittest.main()
