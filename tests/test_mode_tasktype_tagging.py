import unittest
from unittest.mock import patch

import llm_pipeline


class _DummyPredictor:
    def __init__(self, result):
        self._result = result

    def __call__(self, **kwargs):
        return self._result


class _Result:
    def __init__(self, **fields):
        for key, value in fields.items():
            setattr(self, key, value)


class TestModeTaskTypeTagging(unittest.TestCase):
    def test_tag_task_accepts_structured_dict(self):
        options = {"Modes": ["A"], "Task Type": ["B"]}
        result = _Result(tags={"Modes": "A", "Task Type": "B"})

        with patch.object(llm_pipeline.dspy, "Predict", return_value=_DummyPredictor(result)):
            out = llm_pipeline.tag_task("demo", options)

        self.assertEqual(out, {"Modes": "A", "Task Type": "B"})

    def test_tag_task_parses_json_string(self):
        options = {"Modes": ["A"], "Task Type": ["B"]}
        result = _Result(tags='{"Modes":"A","Task Type":"B"}')

        with patch.object(llm_pipeline.dspy, "Predict", return_value=_DummyPredictor(result)):
            out = llm_pipeline.tag_task("demo", options)

        self.assertEqual(out, {"Modes": "A", "Task Type": "B"})

    def test_tag_task_uses_fallback_text_field_when_tags_missing(self):
        options = {"Modes": ["A"], "Task Type": ["B"]}
        result = _Result(answer='{"Modes":"A","Task Type":"B"}')

        with patch.object(llm_pipeline.dspy, "Predict", return_value=_DummyPredictor(result)):
            out = llm_pipeline.tag_task("demo", options)

        self.assertEqual(out, {"Modes": "A", "Task Type": "B"})


if __name__ == "__main__":
    unittest.main()
