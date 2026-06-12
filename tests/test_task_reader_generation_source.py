import unittest

from task_reader import build_task_tree
from state_manager import flatten_tree


class TestTaskReaderGenerationSource(unittest.TestCase):
    def test_notion_created_by_metadata_does_not_set_generated(self):
        blocks = [
            {
                "id": "block-1",
                "type": "to_do",
                "to_do": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {"content": "LLM-looking task"},
                            "plain_text": "LLM-looking task",
                        }
                    ],
                    "checked": False,
                },
                "created_by": {"id": "integration-user-id"},
                "last_edited_by": {"id": "integration-user-id"},
            }
        ]

        tree = build_task_tree(blocks, parent_id="page-root")
        self.assertEqual(1, len(tree))
        self.assertFalse(tree[0].get("is_generated"))
        self.assertEqual("human", tree[0].get("origin"))

    def test_quote_blocks_and_text_links_are_captured(self):
        blocks = [
            {
                "id": "quote-1",
                "type": "quote",
                "quote": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": "Format Cute Manual",
                                "link": {"url": "https://example.com/manual"},
                            },
                            "plain_text": "Format Cute Manual",
                        }
                    ],
                    "color": "default",
                },
            }
        ]

        tree = build_task_tree(blocks, parent_id="page-root")
        self.assertEqual(1, len(tree))
        self.assertEqual("quote", tree[0]["type"])
        self.assertEqual("Format Cute Manual", tree[0]["title"])
        self.assertEqual(
            [{"text": "Format Cute Manual", "url": "https://example.com/manual"}],
            tree[0]["links"],
        )

        flat = flatten_tree(tree)
        self.assertTrue(flat[0]["is_content_block"])


if __name__ == "__main__":
    unittest.main()
