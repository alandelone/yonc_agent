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
            scoped_ids, rank_by_task_id, ordered_keys = build_timeliner_scope(
                state,
                require_cached_state=False,
            )

        self.assertEqual(["sprint"], ordered_keys)
        self.assertIn("a", scoped_ids)
        self.assertNotIn("b", scoped_ids)  # Theme match only, title does not match.
        self.assertNotIn("c", scoped_ids)  # Title match only, theme does not match.
        self.assertEqual(0, rank_by_task_id["a"])
        self.assertEqual("sprint", state[0]["timeliner_key"])

    def test_scope_uses_parsed_timeliner_task_and_theme_tags(self):
        state = [
            {
                "id": "a",
                "notion_block_id": "a",
                "title": "PhDSettle✒ Thesis Apparatus Learning : blablabla",
                "original_notion_title": "🏭 Thesis Apparatus Learning : blablabla",
                "context_heading": "",
                "tags": {"Task Theme with colour": "PhDSettle✒|Thesis"},
            },
            {
                "id": "b",
                "notion_block_id": "b",
                "title": "PhDSettle✒ Thesis Other task",
                "original_notion_title": "Other task",
                "context_heading": "",
                "tags": {"Task Theme with colour": "PhDSettle✒|Thesis"},
            },
        ]

        entries = [
            SimpleNamespace(
                colour_subtheme="Thesis",
                tags={"Task Theme with colour": "PhDSettle✒|Thesis"},
                task_title="Apparatus Learning",
                description="blablabla",
                subproject="",
                project="",
                priority=1,
                scope_section="main",
            )
        ]
        with patch("flow_pipeline.fetch_and_parse_timeliner", return_value=entries):
            scoped_ids, rank_by_task_id, ordered_keys = build_timeliner_scope(
                state,
                require_cached_state=False,
            )

        self.assertEqual(["apparatus learning : blablabla"], ordered_keys)
        self.assertIn("a", scoped_ids)
        self.assertNotIn("b", scoped_ids)
        self.assertEqual(0, rank_by_task_id["a"])
        self.assertEqual("apparatus learning : blablabla", state[0]["timeliner_key"])

    def test_scope_warns_when_timeliner_task_is_absent_in_linev2(self):
        state = [
            {
                "id": "a",
                "notion_block_id": "a",
                "title": "PhDSettle✒ Thesis Other task",
                "original_notion_title": "Other task",
                "context_heading": "",
                "tags": {"Task Theme with colour": "PhDSettle✒|Thesis"},
            },
        ]

        entries = [
            SimpleNamespace(
                colour_subtheme="Thesis",
                tags={"Task Theme with colour": "PhDSettle✒|Thesis"},
                task_title="Apparatus Learning",
                description="blablabla",
                subproject="",
                project="",
                priority=1,
                scope_section="main",
            )
        ]
        with patch("flow_pipeline.fetch_and_parse_timeliner", return_value=entries):
            with self.assertLogs("flow_pipeline", level="WARNING") as logs:
                scoped_ids, _, _ = build_timeliner_scope(
                    state,
                    require_cached_state=False,
                )

        self.assertEqual(set(), scoped_ids)
        self.assertTrue(
            any("Timeliner task absent in LINEV2" in message for message in logs.output)
        )

    def test_scope_allows_title_match_when_description_differs(self):
        state = [
            {
                "id": "a",
                "notion_block_id": "a",
                "title": "Maker Sprint planning : detailed local description",
                "original_notion_title": "Sprint planning : detailed local description",
                "context_heading": "",
                "tags": {"Task Theme with colour": "Maker Sprint|Design"},
            },
        ]

        entries = [
            SimpleNamespace(
                colour_subtheme="Sprint",
                tags={"Task Theme with colour": "Maker Sprint|Design"},
                task_title="Sprint planning",
                description="short timeliner description",
                subproject="",
                project="",
                priority=1,
                scope_section="main",
            )
        ]
        with patch("flow_pipeline.fetch_and_parse_timeliner", return_value=entries):
            scoped_ids, rank_by_task_id, ordered_keys = build_timeliner_scope(
                state,
                require_cached_state=False,
            )

        self.assertEqual(["sprint planning : short timeliner description"], ordered_keys)
        self.assertIn("a", scoped_ids)
        self.assertEqual(0, rank_by_task_id["a"])

    def test_scope_skips_when_timeliner_state_file_missing(self):
        state = [
            {
                "id": "a",
                "notion_block_id": "a",
                "title": "Maker Sprint planning",
                "original_notion_title": "Sprint planning",
                "context_heading": "",
                "tags": {"Task Theme with colour": "Maker Sprint|Design"},
                "timeliner_key": "old",
                "timeliner_rank": 1,
                "timeliner_is_subproject": True,
                "timeliner_priority": 2,
                "timeliner_section": "main",
            },
        ]

        with patch("flow_pipeline.TIMELINER_STATE_FILE", "__missing_timeliner_state__.json"):
            with patch("flow_pipeline.fetch_and_parse_timeliner") as fetch_mock:
                scoped_ids, rank_by_task_id, ordered_keys = build_timeliner_scope(state)

        fetch_mock.assert_not_called()
        self.assertEqual(set(), scoped_ids)
        self.assertEqual({}, rank_by_task_id)
        self.assertEqual([], ordered_keys)
        self.assertIsNone(state[0]["timeliner_key"])
        self.assertIsNone(state[0]["timeliner_rank"])
        self.assertFalse(state[0]["timeliner_is_subproject"])
        self.assertIsNone(state[0]["timeliner_priority"])
        self.assertEqual("", state[0]["timeliner_section"])

    def test_scope_skips_when_timeliner_state_file_is_stale(self):
        state = [
            {
                "id": "a",
                "notion_block_id": "a",
                "title": "Maker Sprint planning",
                "original_notion_title": "Sprint planning",
                "context_heading": "",
                "tags": {"Task Theme with colour": "Maker Sprint|Design"},
                "timeliner_key": "old",
                "timeliner_rank": 1,
                "timeliner_is_subproject": True,
                "timeliner_priority": 2,
                "timeliner_section": "main",
            },
        ]

        with patch("flow_pipeline._has_cached_timeliner_scope", return_value=False):
            with patch("flow_pipeline.fetch_and_parse_timeliner") as fetch_mock:
                scoped_ids, rank_by_task_id, ordered_keys = build_timeliner_scope(state)

        fetch_mock.assert_not_called()
        self.assertEqual(set(), scoped_ids)
        self.assertEqual({}, rank_by_task_id)
        self.assertEqual([], ordered_keys)
        self.assertIsNone(state[0]["timeliner_key"])
        self.assertIsNone(state[0]["timeliner_rank"])
        self.assertFalse(state[0]["timeliner_is_subproject"])
        self.assertIsNone(state[0]["timeliner_priority"])
        self.assertEqual("", state[0]["timeliner_section"])


if __name__ == "__main__":
    unittest.main()
