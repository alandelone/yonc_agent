import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flow_pipeline import build_timeliner_scope


class TestFlowScopeResolver(unittest.TestCase):
    def test_scope_requires_theme_and_title_match(self):
        state = [
            {
                "id": "a",
                "notion_block_id": "a",
                "title": "Maker Sprint planning",
                "original_notion_title": "Sprint planning",
                "context_heading": "",
                "tags": {"Task Theme with colour": "Maker Sprint|Design"},
            },
            {
                "id": "b",
                "notion_block_id": "b",
                "title": "Random title",
                "original_notion_title": "Random title",
                "context_heading": "",
                "tags": {"Task Theme with colour": "Maker Sprint|Design"},
            },
            {
                "id": "c",
                "notion_block_id": "c",
                "title": "Sprint documentation",
                "original_notion_title": "Sprint documentation",
                "context_heading": "",
                "tags": {"Task Theme with colour": "Other Theme"},
            },
        ]

        entries = [SimpleNamespace(colour_subtheme="Sprint")]
        with patch("flow_pipeline.fetch_and_parse_timeliner", return_value=entries):
            scoped_ids, rank_by_task_id, ordered_keys = build_timeliner_scope(state)

        self.assertEqual(["sprint"], ordered_keys)
        self.assertIn("a", scoped_ids)
        self.assertNotIn("b", scoped_ids)  # Theme match only, title does not match.
        self.assertNotIn("c", scoped_ids)  # Title match only, theme does not match.
        self.assertEqual(0, rank_by_task_id["a"])
        self.assertEqual("sprint", state[0]["timeliner_key"])


if __name__ == "__main__":
    unittest.main()
