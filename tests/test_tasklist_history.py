import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import state_manager


class TestTasklistHistory(unittest.TestCase):
    def test_save_state_records_tasklist_history_diff(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            state_file = temp_path / "tasklist_state.json"
            history_file = temp_path / "tasklist_history.jsonl"

            with patch.object(state_manager, "STATE_FILE", str(state_file)), patch.object(
                state_manager, "TASKLIST_HISTORY_FILE", str(history_file)
            ):
                state_manager.save_state(
                    [
                        {
                            "id": "task-1",
                            "notion_block_id": "task-1",
                            "title": "First task",
                            "checked": False,
                        }
                    ],
                    str(state_file),
                )
                state_manager.save_state(
                    [
                        {
                            "id": "task-1",
                            "notion_block_id": "task-1",
                            "title": "First task",
                            "checked": True,
                        },
                        {
                            "id": "task-2",
                            "notion_block_id": "task-2",
                            "title": "Second task",
                            "checked": False,
                        },
                    ],
                    str(state_file),
                )

            entries = [
                json.loads(line)
                for line in history_file.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(2, len(entries))
            self.assertEqual("tasklist_state_changed", entries[-1]["event"])
            self.assertEqual({"added": 1, "updated": 1, "deleted": 0, "total_changes": 2}, entries[-1]["summary"])

            changes_by_id = {change["task_id"]: change for change in entries[-1]["changes"]}
            self.assertEqual("added", changes_by_id["task-2"]["type"])
            self.assertEqual("updated", changes_by_id["task-1"]["type"])
            self.assertEqual(False, changes_by_id["task-1"]["fields"]["checked"]["before"])
            self.assertEqual(True, changes_by_id["task-1"]["fields"]["checked"]["after"])

    def test_save_state_does_not_record_current_state_history(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            tasklist_file = temp_path / "tasklist_state.json"
            current_file = temp_path / "current_state.json"
            history_file = temp_path / "tasklist_history.jsonl"

            with patch.object(state_manager, "STATE_FILE", str(tasklist_file)), patch.object(
                state_manager, "TASKLIST_HISTORY_FILE", str(history_file)
            ):
                state_manager.save_state(
                    [{"id": "snapshot-1", "notion_block_id": "snapshot-1"}],
                    str(current_file),
                )

            self.assertFalse(history_file.exists())


if __name__ == "__main__":
    unittest.main()
