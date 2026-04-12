import unittest
from unittest.mock import patch

from llm_pipeline import WBSClassification, priority_pass, wbs_pass


def _config():
    return {
        "Task Theme with colour": [{"text": "Maker Sprint|Design", "color": "blue"}],
        "WBS level": ["1 | Level 1", "2 | Level 2", "3 | Level 3", "4 | Level 4"],
        "Priority": ["CRIT | (P$)", "ALERT | (P0)", "HIGH | (P1)", "NORMAL | (P2)"],
    }


class TestWbsPriorityPasses(unittest.TestCase):
    def test_parent_manual_wbs_propagates_to_child(self):
        state = [
            {
                "id": "p",
                "notion_block_id": "p",
                "title": "Parent",
                "original_notion_title": "Parent",
                "parent_id": "page",
                "depth": 0,
                "tags": {"WBS level": "3 | Level 3"},
                "wbs_level": 3,
            },
            {
                "id": "c",
                "notion_block_id": "c",
                "title": "Child",
                "original_notion_title": "Child",
                "parent_id": "p",
                "depth": 1,
                "tags": {},
                "wbs_level": None,
            },
        ]

        with patch("llm_pipeline.classify_task", return_value=WBSClassification(rationale="x", level=1, task_type="WBS")):
            out = wbs_pass(state, _config(), scoped_ids={"p", "c"})

        self.assertEqual(3, out[0]["wbs_level"])
        self.assertEqual("manual", out[0]["wbs_source"])
        self.assertEqual(4, out[1]["wbs_level"])  # parent-first rule
        self.assertEqual("auto", out[1]["wbs_source"])

    def test_priority_overwrite_main_projects_uses_p0_p1_p2_buckets(self):
        state = []
        scoped = set()
        rank = {}
        for i in range(8):
            tid = f"t{i}"
            state.append(
                {
                    "id": tid,
                    "notion_block_id": tid,
                    "depth": 0,
                    "tags": {},
                    "timeliner_section": "main",
                    "timeliner_priority": i + 1,
                }
            )
            scoped.add(tid)
            rank[tid] = i

        out = priority_pass(state, _config(), scoped_ids=scoped, rank_by_task_id=rank)
        priorities = [t["tags"].get("Priority", "") for t in out]

        # idx 0 -> P0, idx 1-2 -> P1, idx >=3 -> P2
        self.assertEqual("ALERT | (P0)", priorities[0])
        self.assertEqual("HIGH | (P1)", priorities[1])
        self.assertEqual("HIGH | (P1)", priorities[2])
        self.assertEqual("NORMAL | (P2)", priorities[3])
        self.assertEqual("NORMAL | (P2)", priorities[4])
        self.assertEqual("NORMAL | (P2)", priorities[5])
        self.assertEqual("NORMAL | (P2)", priorities[6])
        self.assertEqual("NORMAL | (P2)", priorities[7])


if __name__ == "__main__":
    unittest.main()
