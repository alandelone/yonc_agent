import os
import json
import pytest
from timeliner_diff import format_date_diff
from timeliner_state import TIMELINER_AUDIT_FILE

@pytest.fixture(autouse=True)
def mock_audit_log():
    if os.path.exists(TIMELINER_AUDIT_FILE):
        os.remove(TIMELINER_AUDIT_FILE)
        
    entries = [
        {
            "timestamp": "2026-04-01T10:00:00Z",
            "block_id": "b1",
            "colour_subtheme": "健身",
            "field": "settle_date",
            "old_value": "2026-03-30",
            "new_value": "2026-04-15",
            "extension_count": 1,
            "status_change": "🟢 \u2192 🔴"
        },
        {
            "timestamp": "2026-04-05T12:00:00Z",
            "block_id": "b1",
            "colour_subtheme": "健身",
            "field": "settle_date",
            "old_value": "2026-04-15",
            "new_value": "2026-05-01",
            "extension_count": 2,
            "status_change": "🔴 \u2192 🔴"
        },
        {
            "timestamp": "2026-04-02T09:00:00Z",
            "block_id": "b2",
            "colour_subtheme": "Study",
            "field": "settle_date",
            "old_value": "2026-04-01",
            "new_value": "2026-04-10",
            "extension_count": 1,
            "status_change": "🟢 \u2192 🔴"
        }
    ]
    with open(TIMELINER_AUDIT_FILE, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
            
    yield
    if os.path.exists(TIMELINER_AUDIT_FILE):
        os.remove(TIMELINER_AUDIT_FILE)

def test_format_multiple_changes():
    output = format_date_diff()
    assert "[2026-04-01] 健身" in output
    assert "- Settle by: 2026-03-30" in output
    assert "+ Settle by: 2026-04-15" in output
    assert "Study" in output

def test_filter_by_subtheme():
    output = format_date_diff("Study")
    assert "Study" in output
    assert "健身" not in output
    
def test_no_history(monkeypatch):
    if os.path.exists(TIMELINER_AUDIT_FILE):
        os.remove(TIMELINER_AUDIT_FILE)
    assert "No date audit history found" in format_date_diff()
