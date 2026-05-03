import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure repo root is on sys.path for local imports
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sync_engine import reparent_theme_containers


def _fake_append_factory():
    counter = {"n": 0}

    def _fake_append(parent_id, children, after_id=None, position=None):
        # 批量 append：每个 child 对应一个唯一 ID
        results = []
        for _ in children:
            counter["n"] += 1
            results.append({"id": f"new-{counter['n']}"})
        return {"results": results}

    return _fake_append


class TestReparentSubthemeContainers(unittest.TestCase):
    def test_reparents_prefixed_subtheme_container_under_lab(self):
        config = {
            "Task Theme with colour": [
                {"text": "鍛造Lab 倉库管理sys|日志管理&Building Plan sys|DZaoSpaceV1|鍛造Maker", "color": "blue"},
            ],
            "Modes": [],
            "WBS level": [],
        }

        state = [
            {"id": "lab", "notion_block_id": "lab", "original_notion_title": "鍛造Lab", "title": "鍛造Lab", "parent_id": "page", "depth": 0, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "maker", "notion_block_id": "maker", "original_notion_title": "鍛造Lab 鍛造Maker", "title": "鍛造Lab 鍛造Maker", "parent_id": "lab", "depth": 1, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "rest", "notion_block_id": "rest", "original_notion_title": "Rest alarm", "title": "Rest alarm", "parent_id": "maker", "depth": 2, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "f3d", "notion_block_id": "f3d", "original_notion_title": "3dpF", "title": "3dpF", "parent_id": "maker", "depth": 2, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "phase1", "notion_block_id": "phase1", "original_notion_title": "Phase1", "title": "Phase1", "parent_id": "f3d", "depth": 3, "type": "bullet", "notion_type": "bulleted_list_item"},
        ]

        with patch("notion_client.append_children", side_effect=_fake_append_factory()), patch(
            "notion_client.delete_block", return_value={"archived": True}
        ):
            out = reparent_theme_containers(state, config)

        root_titles = [t.get("original_notion_title") for t in out if t.get("parent_id") == "page"]
        self.assertEqual(["Rest alarm", "3dpF"], root_titles)
        self.assertFalse(any("鍛造Maker" in str(t) for t in root_titles))

    def test_reparents_gangti_and_life_to_leaf_tasks(self):
        config = {
            "Task Theme with colour": [
                {"text": "我流方矩 知识技能學習流程の内化系统|方矩v3 Dev|刚体|Life", "color": "blue"},
            ],
            "Modes": [],
            "WBS level": [],
        }

        state = [
            {"id": "root", "notion_block_id": "root", "original_notion_title": "我流方矩", "title": "我流方矩", "parent_id": "page", "depth": 0, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "k1", "notion_block_id": "k1", "original_notion_title": "知识技能學習流程の内化系统", "title": "知识技能學習流程の内化系统", "parent_id": "root", "depth": 1, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "k2", "notion_block_id": "k2", "original_notion_title": "方矩v3 Dev", "title": "方矩v3 Dev", "parent_id": "root", "depth": 1, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "gangti", "notion_block_id": "gangti", "original_notion_title": "我流方矩 刚体", "title": "我流方矩 刚体", "parent_id": "root", "depth": 1, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "gangti-child", "notion_block_id": "gangti-child", "original_notion_title": "刚体打造和训练论", "title": "刚体打造和训练论", "parent_id": "gangti", "depth": 2, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "life", "notion_block_id": "life", "original_notion_title": "我流方矩 Life", "title": "我流方矩 Life", "parent_id": "root", "depth": 1, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "life-child", "notion_block_id": "life-child", "original_notion_title": "食物系统", "title": "食物系统", "parent_id": "life", "depth": 2, "type": "bullet", "notion_type": "bulleted_list_item"},
        ]

        with patch("notion_client.append_children", side_effect=_fake_append_factory()), patch(
            "notion_client.delete_block", return_value={"archived": True}
        ):
            out = reparent_theme_containers(state, config)

        root_titles = [t.get("original_notion_title") for t in out if t.get("parent_id") == "page"]
        self.assertEqual(
            ["知识技能學習流程の内化系统", "方矩v3 Dev", "刚体打造和训练论", "食物系统"],
            root_titles,
        )
        self.assertFalse(any(t in ["刚体", "Life", "我流方矩 刚体", "我流方矩 Life"] for t in root_titles))

    def test_reparents_dynamic_prefixed_one_child_group_even_if_not_in_config(self):
        config = {
            "Task Theme with colour": [
                {"text": "我流方矩 知识技能學習流程の内化系统|方矩v3 Dev", "color": "blue"},
            ],
            "Modes": [],
            "WBS level": [],
        }

        state = [
            {"id": "root", "notion_block_id": "root", "original_notion_title": "我流方矩", "title": "我流方矩", "parent_id": "page", "depth": 0, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "gangti", "notion_block_id": "gangti", "original_notion_title": "我流方矩 刚体", "title": "我流方矩 刚体", "parent_id": "root", "depth": 1, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "gangti-child", "notion_block_id": "gangti-child", "original_notion_title": "刚体打造和训练论", "title": "刚体打造和训练论", "parent_id": "gangti", "depth": 2, "type": "bullet", "notion_type": "bulleted_list_item"},
        ]

        with patch("notion_client.append_children", side_effect=_fake_append_factory()), patch(
            "notion_client.delete_block", return_value={"archived": True}
        ):
            out = reparent_theme_containers(state, config)

        root_titles = [t.get("original_notion_title") for t in out if t.get("parent_id") == "page"]
        self.assertEqual(["刚体打造和训练论"], root_titles)

    def test_theme_display_label_propagated_to_reparented_children(self):
        """展平后子节点应继承容器匹配到的子主题名作为 theme_display_label"""
        config = {
            "Task Theme with colour": [
                {"text": "鍛造Lab 倉库管理sys|日志管理&Building Plan sys|DZaoSpaceV1|鍛造Maker", "color": "blue"},
            ],
            "Modes": [],
            "WBS level": [],
        }

        state = [
            {"id": "lab", "notion_block_id": "lab", "original_notion_title": "鍛造Lab", "title": "鍛造Lab", "parent_id": "page", "depth": 0, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "maker", "notion_block_id": "maker", "original_notion_title": "鍛造Maker", "title": "鍛造Lab 鍛造Maker", "parent_id": "lab", "depth": 1, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "rest", "notion_block_id": "rest", "original_notion_title": "Rest alarm", "title": "Rest alarm", "parent_id": "maker", "depth": 2, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "f3d", "notion_block_id": "f3d", "original_notion_title": "3dpF", "title": "3dpF", "parent_id": "maker", "depth": 2, "type": "bullet", "notion_type": "bulleted_list_item"},
        ]

        with patch("notion_client.append_children", side_effect=_fake_append_factory()), patch(
            "notion_client.delete_block", return_value={"archived": True}
        ):
            out = reparent_theme_containers(state, config)

        # 从 鍛造Maker 下提升的子节点应获得 theme_display_label = "鍛造Maker"
        rest_task = next((t for t in out if t.get("original_notion_title") == "Rest alarm"), None)
        f3d_task = next((t for t in out if t.get("original_notion_title") == "3dpF"), None)
        self.assertIsNotNone(rest_task)
        self.assertIsNotNone(f3d_task)
        self.assertEqual("鍛造Maker", rest_task.get("theme_display_label"))
        self.assertEqual("鍛造Maker", f3d_task.get("theme_display_label"))

    def test_theme_display_label_for_gangti_and_life(self):
        """我流方矩 刚体 -> 子节点的 label 应为 '刚体'; 我流方矩 Life -> 子节点的 label 应为 'Life'"""
        config = {
            "Task Theme with colour": [
                {"text": "我流方矩 知识技能學習流程の内化系统|方矩v3 Dev|刚体|Life", "color": "blue"},
            ],
            "Modes": [],
            "WBS level": [],
        }

        state = [
            {"id": "root", "notion_block_id": "root", "original_notion_title": "我流方矩", "title": "我流方矩", "parent_id": "page", "depth": 0, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "k1", "notion_block_id": "k1", "original_notion_title": "知识技能學習流程の内化系统", "title": "知识技能學習流程の内化系统", "parent_id": "root", "depth": 1, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "gangti", "notion_block_id": "gangti", "original_notion_title": "刚体", "title": "我流方矩 刚体", "parent_id": "root", "depth": 1, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "gangti-child", "notion_block_id": "gangti-child", "original_notion_title": "刚体打造和训练论", "title": "刚体打造和训练论", "parent_id": "gangti", "depth": 2, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "life", "notion_block_id": "life", "original_notion_title": "Life", "title": "我流方矩 Life", "parent_id": "root", "depth": 1, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "life-child", "notion_block_id": "life-child", "original_notion_title": "食物系统", "title": "食物系统", "parent_id": "life", "depth": 2, "type": "bullet", "notion_type": "bulleted_list_item"},
        ]

        with patch("notion_client.append_children", side_effect=_fake_append_factory()), patch(
            "notion_client.delete_block", return_value={"archived": True}
        ):
            out = reparent_theme_containers(state, config)

        gangti_child = next((t for t in out if t.get("original_notion_title") == "刚体打造和训练论"), None)
        life_child = next((t for t in out if t.get("original_notion_title") == "食物系统"), None)
        k1_task = next((t for t in out if t.get("original_notion_title") == "知识技能學習流程の内化系统"), None)

        self.assertIsNotNone(gangti_child)
        self.assertIsNotNone(life_child)
        self.assertIsNotNone(k1_task)
        self.assertEqual("刚体", gangti_child.get("theme_display_label"))
        self.assertEqual("Life", life_child.get("theme_display_label"))
        # k1 直接从 我流方矩 下提升，label 应为 "我流方矩"
        self.assertEqual("我流方矩", k1_task.get("theme_display_label"))

    def test_dry_run_does_not_call_api(self):
        """dry_run=True 时不应调用 append_children 或 delete_block"""
        config = {
            "Task Theme with colour": [
                {"text": "我流方矩 刚体|Life", "color": "blue"},
            ],
            "Modes": [],
            "WBS level": [],
        }

        state = [
            {"id": "root", "notion_block_id": "root", "original_notion_title": "我流方矩", "title": "我流方矩", "parent_id": "page", "depth": 0, "type": "bullet", "notion_type": "bulleted_list_item"},
            {"id": "k1", "notion_block_id": "k1", "original_notion_title": "task1", "title": "task1", "parent_id": "root", "depth": 1, "type": "bullet", "notion_type": "bulleted_list_item"},
        ]

        with patch("notion_client.append_children") as mock_append, patch(
            "notion_client.delete_block"
        ) as mock_delete:
            out = reparent_theme_containers(state, config, dry_run=True)

        mock_append.assert_not_called()
        mock_delete.assert_not_called()
        # state 应该仍然被正确变换（容器被移除）
        root_titles = [t.get("original_notion_title") for t in out if t.get("parent_id") == "page"]
        self.assertEqual(["task1"], root_titles)


class TestNormalizeUuid(unittest.TestCase):
    def test_converts_32char_hex_to_uuid(self):
        from sync_engine import _normalize_uuid
        raw = "318e1eb5ce57808ea334c9365174d477"
        expected = "318e1eb5-ce57-808e-a334-c9365174d477"
        self.assertEqual(expected, _normalize_uuid(raw))

    def test_preserves_already_hyphenated_uuid(self):
        from sync_engine import _normalize_uuid
        already = "33ae1eb5-ce57-802a-a2e1-d6fd6b3fb970"
        self.assertEqual(already, _normalize_uuid(already))

    def test_handles_empty_string(self):
        from sync_engine import _normalize_uuid
        self.assertEqual("", _normalize_uuid(""))


if __name__ == "__main__":
    unittest.main()
