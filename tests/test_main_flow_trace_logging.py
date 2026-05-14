import unittest
import types
import sys
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def _install_stub_modules() -> dict:
    stubbed_names = [
        "flow_pipeline",
        "config",
        "config_reader",
        "state_manager",
        "sync_engine",
        "task_reader",
        "dashboard",
    ]
    previous_modules = {name: sys.modules.get(name) for name in stubbed_names}

    flow_mod = types.ModuleType("flow_pipeline")
    flow_mod.run_flow = lambda: None
    flow_mod.run_l1 = lambda: None
    flow_mod.run_l2 = lambda: None
    flow_mod.run_l3 = lambda: None
    sys.modules["flow_pipeline"] = flow_mod

    config_mod = types.ModuleType("config")
    config_mod.POLL_INTERVAL_SECONDS = 5
    sys.modules["config"] = config_mod

    config_reader_mod = types.ModuleType("config_reader")
    config_reader_mod.load_config = lambda: {}
    config_reader_mod.structure_yonctask_config = lambda cfg: cfg
    sys.modules["config_reader"] = config_reader_mod

    state_manager_mod = types.ModuleType("state_manager")
    state_manager_mod.STATE_FILE = "data/current_state.json"
    state_manager_mod.flatten_tree = lambda tree: tree
    state_manager_mod.load_state = lambda _: []
    state_manager_mod.merge_states = lambda a, b: a or b
    state_manager_mod.save_state = lambda state, path: None
    sys.modules["state_manager"] = state_manager_mod

    sync_mod = types.ModuleType("sync_engine")
    sync_mod.sync_from_notion = lambda flat: flat
    sys.modules["sync_engine"] = sync_mod

    task_reader_mod = types.ModuleType("task_reader")
    task_reader_mod.fetch_and_build_task_tree = lambda: []
    sys.modules["task_reader"] = task_reader_mod

    dashboard_mod = types.ModuleType("dashboard")
    dashboard_mod.group_tasks_by_mode = lambda *_args, **_kwargs: {}
    sys.modules["dashboard"] = dashboard_mod

    return previous_modules


def _restore_modules(previous_modules: dict) -> None:
    for name, module in previous_modules.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


_PREVIOUS_MODULES = _install_stub_modules()
import main
_restore_modules(_PREVIOUS_MODULES)


class TestMainFlowTraceLogging(unittest.TestCase):
    def test_is_flow_trace_command(self):
        self.assertTrue(main._is_flow_trace_command("flow"))
        self.assertTrue(main._is_flow_trace_command("split"))
        self.assertFalse(main._is_flow_trace_command("sync"))
        self.assertFalse(main._is_flow_trace_command(None))

    def test_capture_flow_trace_writes_print_output(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            try:
                with patch("main._logs_root_dir", return_value=temp_path):
                    main.configure_cli_logging("INFO", "flow")
                    with main.capture_flow_trace("flow", ["python", "main.py", "flow"]) as run_log:
                        print("trace-line-1")
                        print("trace-line-2")
                        logging.getLogger("trace-test").info("trace-log-line")

                    self.assertTrue(run_log.exists())
                    run_content = run_log.read_text(encoding="utf-8")
                    self.assertIn("command: flow", run_content)
                    self.assertIn("trace-line-1", run_content)
                    self.assertIn("trace-line-2", run_content)
                    self.assertIn("trace-log-line", run_content)

                    latest_log = temp_path / "flow_runs" / "flow_latest.log"
                    self.assertTrue(latest_log.exists())
                    latest_content = latest_log.read_text(encoding="utf-8")
                    self.assertIn("trace-line-2", latest_content)
            finally:
                root_logger = logging.getLogger()
                for handler in list(root_logger.handlers):
                    root_logger.removeHandler(handler)
                    handler.close()


if __name__ == "__main__":
    unittest.main()
