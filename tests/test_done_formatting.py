import sys
import unittest
from pathlib import Path

# Ensure repo root is on sys.path for local imports
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from completion import DONE_PREFIX, format_done_text
from sync_engine import DONE_MARK


class TestDoneFormatting(unittest.TestCase):
    def test_done_prefix_and_gray(self):
        rich_text = [
            {
                "type": "text",
                "text": {"content": "Task"},
                "annotations": {"bold": False},
                "plain_text": "Task",
            }
        ]

        out = format_done_text(rich_text)
        self.assertTrue(out[0]["text"]["content"].startswith(f"{DONE_PREFIX} "))
        self.assertEqual(out[0]["annotations"]["color"], "gray")
        self.assertTrue(out[0]["annotations"]["strikethrough"])
        self.assertEqual(out[-1]["text"]["content"], " ?h")
        self.assertTrue(out[-1]["annotations"]["code"])

    def test_format_done_text_uses_computed_hours_when_provided(self):
        rich_text = [
            {
                "type": "text",
                "text": {"content": "Task"},
                "annotations": {"bold": False},
                "plain_text": "Task",
            }
        ]

        out = format_done_text(rich_text, hours_taken=1.25)
        self.assertEqual(out[-1]["text"]["content"], " 1.2h")
        self.assertTrue(out[-1]["annotations"]["code"])

    def test_format_done_text_rounds_integer_hours_cleanly(self):
        rich_text = [
            {
                "type": "text",
                "text": {"content": "Task"},
                "annotations": {"bold": False},
                "plain_text": "Task",
            }
        ]

        out = format_done_text(rich_text, hours_taken=2.0)
        self.assertEqual(out[-1]["text"]["content"], " 2h")

    def test_done_mark_detection(self):
        title = f"Something {DONE_MARK} finished"
        self.assertIn(DONE_MARK, title)


if __name__ == "__main__":
    unittest.main()
