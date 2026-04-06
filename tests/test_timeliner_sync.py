import pytest
from timeliner_sync import calculate_progress_by_subtheme, get_percentage, build_timeliner_rich_text
from timeliner_reader import TimelineEntry
from completion import DONE_PREFIX

def test_calculate_progress():
    tasks = [
        {"type": "to_do", "tags": {"Task Theme with colour": "我流方矩 健身"}, "checked": True},
        {"type": "to_do", "tags": {"Task Theme with colour": "我流方矩 健身"}, "checked": False},
        {"type": "bullet", "tags": {"Task Theme with colour": "Study"}, "title": f"{DONE_PREFIX} Read book"},
        {"type": "heading_2", "tags": {"Task Theme with colour": "Hide"}}
    ]
    
    stats = calculate_progress_by_subtheme(tasks)
    assert stats["我流方矩 健身"] == (1, 2)
    assert stats["Study"] == (1, 1)
    assert "Hide" not in stats
    
    # Check percentage
    assert get_percentage("健身", stats) == 50
    assert get_percentage("Study", stats) == 100
    assert get_percentage("Unknown", stats) == 0

def test_build_rich_text():
    entry = TimelineEntry(
        block_id="b1", project="Proj", subproject="Sub", colour_subtheme="健身",
        status_emoji="🟢", settle_date="2026-03-30", time_expected_h=4.5,
        percent=50, remaining_work_days=5, raw_text=""
    )
    
    # update to 100%, 🔴 status
    rt = build_timeliner_rich_text(entry, 100, "🔴")
    
    assert rt[0]["text"]["content"] == "🔴 "
    assert rt[0]["annotations"]["strikethrough"] is True
    
    texts = "".join([x["text"]["content"] for x in rt])
    assert "🔴 **健身** Takes 🏁dates h4.5 ||100% 💯 Settle by 2026-03-30, but 🔜 5" in texts
