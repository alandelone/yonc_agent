import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure repo root is on sys.path for local imports
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from llm_pipeline import theme_pass
from sync_engine import push_tags_to_notion


def _raw_config():
    return {
        "Task Theme with colour": [
            {"text": "Maker 3dpF|Rest alarm", "color": "blue"},
        ],
        "Modes": [],
        "WBS level": [],
    }


class TestThemePrefixScoping(unittest.TestCase):
    def test_push_sync_autofills_theme_for_non_theme_parent_container(self):
        state = [
            {
                "id": "parent-3dpf",
                "notion_block_id": "parent-3dpf",
                "title": "Maker 3dpF",
                "original_notion_title": "3dpF",
                "context_heading": "",
                "parent_id": "page-root",
                "depth": 0,
                "type": "bullet",
                "notion_type": "bulleted_list_item",
                "tags": {},
                "wbs_level": None,
            },
            {
                "id": "child-phase1",
                "notion_block_id": "child-phase1",
                "title": "Maker 3dpF Phase1",
                "original_notion_title": "Phase1",
                "context_heading": "",
                "parent_id": "parent-3dpf",
                "depth": 1,
                "type": "bullet",
                "notion_type": "bulleted_list_item",
                "tags": {},
                "wbs_level": None,
            },
        ]

        out = theme_pass(state, _raw_config())
        theme_tag = out[0].get("tags", {}).get("Task Theme with colour", "")
        self.assertTrue(theme_tag.startswith("Maker"), "Parent container should be auto-tagged with Maker in push-sync.")
        self.assertEqual("Maker", out[0].get("theme_display_label"))

    def test_child_hides_redundant_theme_prefix_if_parent_has_same_theme(self):
        state = [
            {
                "id": "parent-3dpf",
                "notion_block_id": "parent-3dpf",
                "type": "bullet",
                "notion_type": "bulleted_list_item",
                "title": "Maker 3dpF",
                "original_notion_title": "3dpF",
                "tags": {"Task Theme with colour": "Maker"},
                "depth": 0,
                "parent_id": "page-root",
                "checked": None,
            },
            {
                "id": "child-phase1",
                "notion_block_id": "child-phase1",
                "type": "bullet",
                "notion_type": "bulleted_list_item",
                "title": "Maker Phase1 setup",
                "original_notion_title": "Phase1 setup",
                "tags": {"Task Theme with colour": "Maker"},
                "depth": 1,
                "parent_id": "parent-3dpf",
                "checked": None,
                "wbs_level": 3,
            },
        ]

        with patch("notion_client.update_block", return_value={}) as mock_update:
            push_tags_to_notion(state, _raw_config())

        payload_by_id = {call.args[0]: call.args[1] for call in mock_update.call_args_list}
        parent_rt = payload_by_id["parent-3dpf"]["bulleted_list_item"]["rich_text"]
        child_rt = payload_by_id["child-phase1"]["bulleted_list_item"]["rich_text"]

        self.assertTrue(parent_rt[0]["annotations"].get("code"), "Parent should still show theme badge.")
        self.assertFalse(any(seg.get("annotations", {}).get("code") for seg in child_rt), "Child should not repeat theme badge.")
        self.assertEqual("Phase1 setup", child_rt[0]["text"]["content"])

    def test_infers_dynamic_display_label_from_prefixed_parent_not_in_config(self):
        config = {
            "Task Theme with colour": [
                {"text": "我流方矩 知识技能學習流程の内化系统|方矩v3 Dev", "color": "blue"},
            ],
            "Modes": [],
            "WBS level": [],
        }
        state = [
            {
                "id": "pref-parent",
                "notion_block_id": "pref-parent",
                "title": "我流方矩 刚体",
                "original_notion_title": "我流方矩 刚体",
                "context_heading": "",
                "parent_id": "theme-root",
                "depth": 1,
                "type": "bullet",
                "notion_type": "bulleted_list_item",
                "tags": {},
                "wbs_level": None,
            },
            {
                "id": "pref-child",
                "notion_block_id": "pref-child",
                "title": "我流方矩 刚体 刚体打造和训练论",
                "original_notion_title": "刚体打造和训练论",
                "context_heading": "",
                "parent_id": "pref-parent",
                "depth": 2,
                "type": "bullet",
                "notion_type": "bulleted_list_item",
                "tags": {},
                "wbs_level": None,
            },
        ]

        out = theme_pass(state, config)
        self.assertEqual("刚体", out[1].get("theme_display_label"))

    def test_dynamic_display_label_does_not_strip_same_word_from_title(self):
        config = {
            "Task Theme with colour": [
                {"text": "我流方矩 知识技能學習流程の内化系统|方矩v3 Dev", "color": "blue"},
            ],
            "Modes": [],
            "WBS level": [],
        }
        state = [
            {
                "id": "leaf",
                "notion_block_id": "leaf",
                "type": "bullet",
                "notion_type": "bulleted_list_item",
                "title": "我流方矩 刚体 刚体打造和训练论",
                "original_notion_title": "刚体打造和训练论",
                "theme_display_label": "刚体",
                "tags": {"Task Theme with colour": "我流方矩 知识技能學習流程の内化系统|方矩v3 Dev"},
                "depth": 0,
                "parent_id": "page-root",
                "checked": None,
            }
        ]

        with patch("notion_client.update_block", return_value={}) as mock_update:
            push_tags_to_notion(state, config)

        rich_text = mock_update.call_args.args[1]["bulleted_list_item"]["rich_text"]
        rendered = "".join(seg["text"]["content"] for seg in rich_text)
        self.assertIn("刚体打造和训练论", rendered)

    def test_full_pipeline_dynamic_prefixed_one_child_group_renders_dynamic_label(self):
        config = {
            "Task Theme with colour": [
                {"text": "Theme Alpha|Beta", "color": "blue"},
            ],
            "Modes": [],
            "WBS level": [],
        }
        state = [
            {"id": "root", "notion_block_id": "root", "title": "Theme", "original_notion_title": "Theme", "parent_id": "page", "depth": 0, "type": "bullet", "notion_type": "bulleted_list_item", "tags": {}, "wbs_level": None},
            {"id": "dyn", "notion_block_id": "dyn", "title": "Theme Dynamic", "original_notion_title": "Theme Dynamic", "parent_id": "root", "depth": 1, "type": "bullet", "notion_type": "bulleted_list_item", "tags": {}, "wbs_level": None},
            {"id": "leaf", "notion_block_id": "leaf", "title": "Theme Dynamic Dynamic theory", "original_notion_title": "Dynamic theory", "parent_id": "dyn", "depth": 2, "type": "bullet", "notion_type": "bulleted_list_item", "tags": {}, "wbs_level": None},
        ]

        from llm_pipeline import theme_pass
        from sync_engine import reparent_theme_containers

        enriched = theme_pass(state, config)

        counter = {"n": 0}
        def _fake_append(parent_id, children, after_id=None, position=None):
            results = []
            for _ in children:
                counter["n"] += 1
                results.append({"id": f"new-{counter['n']}"})
            return {"results": results}

        with patch("notion_client.append_children", side_effect=_fake_append), patch(
            "notion_client.delete_block", return_value={"archived": True}
        ):
            reparented = reparent_theme_containers(enriched, config)

        with patch("notion_client.update_block", return_value={}) as mock_update:
            push_tags_to_notion(reparented, config)

        payloads = {call.args[0]: call.args[1] for call in mock_update.call_args_list}
        rendered = "".join(seg["text"]["content"] for seg in payloads["new-3"]["bulleted_list_item"]["rich_text"])
        self.assertIn("Dynamic Dynamic theory", rendered)


if __name__ == "__main__":
    unittest.main()
