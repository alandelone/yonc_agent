import unittest

from state_evaluator import BlockState, evaluate_block_state


class TestStateEvaluatorGeneratedSplit(unittest.TestCase):
    def test_reviewed_generated_non_l4_without_children_is_expanding(self):
        task = {
            "id": "generated-l3",
            "notion_block_id": "generated-l3",
            "original_notion_title": "Research Gap source mapping",
            "type": "bullet",
            "notion_type": "bulleted_list_item",
            "is_generated": True,
            "generated_selection_processed": True,
            "split_stage": "none",
            "wbs_level": 3,
            "timeliner_rank": 1,
            "tags": {
                "Task Theme with colour": "Thesis|Research",
                "Priority": "P1",
            },
        }

        self.assertEqual(BlockState.EXPANDING, evaluate_block_state(task, {}))

    def test_unreviewed_generated_non_l4_without_children_is_not_expanding(self):
        task = {
            "id": "generated-l3",
            "notion_block_id": "generated-l3",
            "original_notion_title": "Research Gap source mapping",
            "type": "todo",
            "notion_type": "to_do",
            "checked": False,
            "is_generated": True,
            "generated_selection_processed": False,
            "split_stage": "none",
            "wbs_level": 3,
            "timeliner_rank": 1,
            "tags": {
                "Task Theme with colour": "Thesis|Research",
                "Priority": "P1",
            },
        }

        self.assertNotEqual(BlockState.EXPANDING, evaluate_block_state(task, {}))

    def test_quote_content_block_is_skipped(self):
        task = {
            "id": "quote-1",
            "notion_block_id": "quote-1",
            "original_notion_title": "Format Cute Manual",
            "type": "quote",
            "notion_type": "quote",
            "is_content_block": True,
            "tags": {},
        }

        self.assertEqual(BlockState.SKIP, evaluate_block_state(task, {}))


if __name__ == "__main__":
    unittest.main()
