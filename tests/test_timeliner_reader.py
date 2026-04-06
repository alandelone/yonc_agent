import pytest
from timeliner_reader import parse_date_to_iso, parse_timeliner_blocks, TIMELINER_PATTERN

def test_date_parsing():
    assert parse_date_to_iso("March 30, 2026") == "2026-03-30"
    assert parse_date_to_iso("Apr 5, 2026") == "2026-04-05"
    assert parse_date_to_iso("Invalid Date") == ""

def test_regex_pattern():
    text1 = "🟢**健身** Takes `🏁dates h` 4.5 ||50% Settle by March 30, 2026, but 🔜 5"
    match1 = TIMELINER_PATTERN.search(text1)
    assert match1 is not None
    data1 = match1.groupdict()
    assert data1["status"] == "🟢"
    assert data1["subtheme"] == "健身"
    assert data1["time_h"] == "4.5"
    assert data1["percent"] == "50"
    assert data1["date"] == "March 30, 2026"
    assert data1["remaining"] == "5"

    text2 = "🔴**Study** Takes 🏁dates h ||100% Settle by April 1, 2026"
    match2 = TIMELINER_PATTERN.search(text2)
    assert match2 is not None
    data2 = match2.groupdict()
    assert data2["status"] == "🔴"
    assert data2["subtheme"] == "Study"
    assert data2["time_h"] is None
    assert data2["percent"] == "100"
    assert data2["date"] == "April 1, 2026"
    assert data2["remaining"] is None

def test_parse_blocks():
    blocks = [
        {
            "type": "heading_2",
            "heading_2": {"rich_text": [{"plain_text": "Main Proj"}]}
        },
        {
            "type": "heading_3",
            "heading_3": {"rich_text": [{"plain_text": "Sub Proj"}]}
        },
        {
            "type": "bulleted_list_item",
            "id": "block1",
            "bulleted_list_item": {"rich_text": [{"plain_text": "🟢**TestTheme** Takes `🏁dates h` 2 ||10% Settle by May 2, 2026, but 🔜 10"}]}
        }
    ]
    
    entries = parse_timeliner_blocks(blocks)
    assert len(entries) == 1
    
    e = entries[0]
    assert e.block_id == "block1"
    assert e.project == "Main Proj"
    assert e.subproject == "Sub Proj"
    assert e.colour_subtheme == "TestTheme"
    assert e.status_emoji == "🟢"
    assert e.time_expected_h == 2.0
    assert e.percent == 10
    assert e.settle_date == "2026-05-02"
    assert e.remaining_work_days == 10
