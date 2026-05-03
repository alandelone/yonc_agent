import os
import json
import pytest
from timeliner_state import (
    load_timeliner_state, save_timeliner_state, get_extension_count, 
    resolve_status_emoji, record_date_change, load_latest_audit_dates,
    TIMELINER_STATE_FILE, TIMELINER_AUDIT_FILE
)

@pytest.fixture(autouse=True)
def clean_test_data():
    """Ensure data files are cleaned up before and after each test."""
    if os.path.exists(TIMELINER_STATE_FILE):
        os.remove(TIMELINER_STATE_FILE)
    if os.path.exists(TIMELINER_AUDIT_FILE):
        os.remove(TIMELINER_AUDIT_FILE)
    yield
    if os.path.exists(TIMELINER_STATE_FILE):
        os.remove(TIMELINER_STATE_FILE)
    if os.path.exists(TIMELINER_AUDIT_FILE):
        os.remove(TIMELINER_AUDIT_FILE)

def test_state_load_save():
    assert load_timeliner_state() == {}
    
    state = {"健身": "2026-03-30", "Study": "2026-04-01"}
    save_timeliner_state(state)
    
    loaded = load_timeliner_state()
    assert loaded == state

def test_audit_logging_and_count():
    assert get_extension_count("健身") == 0
    
    # First change
    count = record_date_change("block1", "健身", "2026-03-30", "2026-04-05")
    assert count == 1
    assert get_extension_count("健身") == 1
    
    # Second change
    count = record_date_change("block1", "健身", "2026-04-05", "2026-04-10")
    assert count == 2
    assert get_extension_count("健身") == 2
    
    # Different subtheme
    assert get_extension_count("Study") == 0

def test_status_emoji():
    assert resolve_status_emoji(0) == "🟢"
    assert resolve_status_emoji(1) == "🔴"
    assert resolve_status_emoji(2) == "🔴"
    assert resolve_status_emoji(3) == "🔥"
    assert resolve_status_emoji(10) == "🔥"

def test_load_latest_audit_dates():
    rows = [
        {
            "scope_key": "Proj::Sub::TaskA",
            "colour_subtheme": "TaskA",
            "field": "settle_date",
            "new_value": "2026-04-10",
        },
        {
            "scope_key": "Proj::Sub::TaskA",
            "colour_subtheme": "TaskA",
            "field": "settle_date",
            "new_value": "2026-04-12",
        },
        {
            "scope_key": "TaskB",
            "colour_subtheme": "TaskB",
            "field": "settle_date",
            "new_value": "2026-05-01",
        },
        {
            "scope_key": "ignore::me",
            "colour_subtheme": "Ignore",
            "field": "percent",
            "new_value": "99",
        },
    ]
    with open(TIMELINER_AUDIT_FILE, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    by_scope, by_subtheme = load_latest_audit_dates()
    assert by_scope["Proj::Sub::TaskA"] == "2026-04-12"
    assert by_scope["TaskB"] == "2026-05-01"
    assert by_subtheme["TaskA"] == "2026-04-12"
    assert by_subtheme["TaskB"] == "2026-05-01"
    assert "Ignore" not in by_subtheme
