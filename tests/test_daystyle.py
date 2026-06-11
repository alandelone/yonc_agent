import os
import json
import pytest
from unittest.mock import patch, MagicMock, mock_open
from config_reader import parse_daystyles, parse_daystyle_dicts
from daystyle_manager import write_today_daystyle, edit_daystyle, CONFIG_FILE, TODAY_STATUS_FILE

def test_parse_daystyles():
    mock_blocks = [
        {
            "type": "toggle",
            "id": "toggle-1",
            "toggle": {
                "rich_text": [
                    {"plain_text": "Uni Research", "annotations": {"bold": True}},
                    {"plain_text": " : Description of research day", "annotations": {"bold": False}}
                ]
            },
            "children_blocks": [
                {
                    "type": "heading_4",
                    "heading_4": {"rich_text": [{"plain_text": "Trajectory:"}]}
                },
                {
                    "type": "bulleted_list_item",
                    "id": "bullet-1",
                    "bulleted_list_item": {"rich_text": [{"plain_text": "Home"}]}
                },
                {
                    "type": "heading_4",
                    "heading_4": {"rich_text": [{"plain_text": "Expected State Timeline"}]}
                },
                {
                    "type": "paragraph",
                    "id": "p-1",
                    "paragraph": {"rich_text": [{"plain_text": 'time: "07:00" || activity: WakeUp || location: Home || energy: 3'}]}
                }
            ]
        }
    ]
    res = parse_daystyles(mock_blocks)
    assert len(res) == 1
    assert res[0]["dayStyle"] == "Uni Research"
    assert res[0]["description"] == "Description of research day"
    assert res[0]["block_id"] == "toggle-1"
    assert len(res[0]["trajectory"]) == 1
    assert res[0]["trajectory"][0]["location"] == "Home"
    assert res[0]["trajectory"][0]["block_id"] == "bullet-1"
    assert len(res[0]["expectedStateTimeline"]) == 1
    assert res[0]["expectedStateTimeline"][0]["time"] == "07:00"
    assert res[0]["expectedStateTimeline"][0]["activity"] == "WakeUp"
    assert res[0]["expectedStateTimeline"][0]["location"] == "Home"
    assert res[0]["expectedStateTimeline"][0]["energy"] == 3
    assert res[0]["expectedStateTimeline"][0]["block_id"] == "p-1"

def test_parse_daystyle_dicts():
    mock_blocks = [
        {
            "type": "toggle",
            "toggle": {"rich_text": [{"plain_text": "Location_Dict"}]},
            "children_blocks": [
                {
                    "type": "toggle",
                    "id": "subtoggle-1",
                    "toggle": {"rich_text": [{"plain_text": "Home"}]},
                    "children_blocks": [
                        {
                            "type": "bulleted_list_item",
                            "bulleted_list_item": {"rich_text": [{"plain_text": "Miri House"}]}
                        }
                    ]
                }
            ]
        }
    ]
    res = parse_daystyle_dicts(mock_blocks)
    assert "Location_Dict" in res
    assert "Home" in res["Location_Dict"]
    assert res["Location_Dict"]["Home"]["sub_items"] == ["Miri House"]
    assert res["Location_Dict"]["Home"]["block_id"] == "subtoggle-1"

@patch("daystyle_manager._atomic_write_json")
def test_write_today_daystyle(mock_atomic_write, tmp_path):
    mock_config = {
        "daystyles": [
            {
                "dayStyle": "Uni Research",
                "description": "Normal working day",
                "trajectory": [{"location": "Home", "block_id": "b-1"}],
                "expectedStateTimeline": [
                    {
                        "time": "07:00",
                        "activity": "WakeUp",
                        "location": "Home",
                        "energy": 3,
                        "tasktype": [],
                        "block_id": "p-1",
                        "raw": "..."
                    }
                ]
            }
        ]
    }
    
    with patch("builtins.open", mock_open(read_data=json.dumps(mock_config))):
        with patch("os.path.exists", return_value=True):
            write_today_daystyle("Uni Research")
            
    assert mock_atomic_write.called
    written_data = mock_atomic_write.call_args[0][1]
    assert "day_mode" in written_data
    dm = written_data["day_mode"]
    assert dm["dayStyle"] == "Uni Research"
    assert dm["trajectory"] == ["Home"]
    assert len(dm["expectedStateTimeline"]) == 1
    assert "block_id" not in dm["expectedStateTimeline"][0]
    assert "raw" not in dm["expectedStateTimeline"][0]

@patch("daystyle_manager.update_block")
@patch("daystyle_manager._log_change")
@patch("daystyle_manager.read_daystyles")
def test_edit_daystyle(mock_read, mock_log, mock_update):
    mock_config = {
        "daystyles": [
            {
                "dayStyle": "Uni Research",
                "description": "Old description",
                "block_id": "parent-1",
                "trajectory": [{"location": "Home", "block_id": "b-1"}],
                "expectedStateTimeline": [{"time": "07:00", "block_id": "p-1", "raw": "..."}]
            }
        ]
    }
    
    with patch("builtins.open", mock_open(read_data=json.dumps(mock_config))):
        with patch("os.path.exists", return_value=True):
            edit_daystyle("Uni Research", "description", "New description", action="update")
            
    assert mock_update.called
    assert mock_log.called
    assert mock_read.called
