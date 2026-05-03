import unittest

from task_reader import build_task_tree


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


if __name__ == "__main__":
    unittest.main()
