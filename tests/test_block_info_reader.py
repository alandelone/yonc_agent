import unittest

from block_info_reader import build_block_info_for_state


class TestBlockInfoReader(unittest.TestCase):
    def test_extracts_parent_child_and_description(self):
        tasks = [
            {
                "id": "root",
                "notion_block_id": "root",
                "title": "Theme Root",
                "original_notion_title": "Theme Root",
                "parent_id": "page",
                "type": "bullet",
                "notion_type": "bulleted_list_item",
            },
            {
                "id": "p1",
                "notion_block_id": "p1",
                "title": "Design Architecture : draft version",
                "original_notion_title": "Design Architecture : draft version",
                "parent_id": "root",
                "type": "bullet",
                "notion_type": "bulleted_list_item",
            },
            {
                "id": "c1",
                "notion_block_id": "c1",
                "title": "Sketch component boundaries",
                "original_notion_title": "Sketch component boundaries",
                "parent_id": "p1",
                "type": "to_do",
                "notion_type": "to_do",
                "checked": False,
            },
        ]

        info = build_block_info_for_state(tasks, tasks[1], max_chars=2000)
        self.assertEqual("Design Architecture", info["title"])
        self.assertEqual("draft version", info["description"])
        self.assertEqual("Theme Root", info["parent_blocks"][0]["title"])
        self.assertEqual("Sketch component boundaries", info["child_blocks"][0]["title"])
        self.assertFalse(info["compacted"])

    def test_compacts_when_payload_is_too_large(self):
        long_desc = "word " * 3000
        tasks = [
            {
                "id": "p1",
                "notion_block_id": "p1",
                "title": f"Big Task : {long_desc}",
                "original_notion_title": f"Big Task : {long_desc}",
                "parent_id": "page",
                "type": "bullet",
                "notion_type": "bulleted_list_item",
            }
        ]
        info = build_block_info_for_state(tasks, tasks[0], max_chars=300)
        self.assertTrue(info["compacted"])
        self.assertTrue(any("summary" in src for src in info["sources"]))


if __name__ == "__main__":
    unittest.main()
