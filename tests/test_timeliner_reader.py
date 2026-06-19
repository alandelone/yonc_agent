import pytest
from timeliner_reader import parse_date_to_iso, parse_timeliner_blocks, TIMELINER_PATTERN

def test_date_parsing():
    assert parse_date_to_iso("March 30, 2026") == "2026-03-30"
    assert parse_date_to_iso("Apr 5, 2026") == "2026-04-05"
    assert parse_date_to_iso("Invalid Date") == ""

def test_regex_pattern():
    text1 = "馃煝**鍋ヨ韩** Takes `馃弫dates h` 4.5 ||50% Settle by March 30, 2026, but 馃敎 5"
    match1 = TIMELINER_PATTERN.search(text1)
    assert match1 is not None
    data1 = match1.groupdict()
    assert data1["prefix"] == "馃煝**鍋ヨ韩**"
    assert "4.5" in (data1.get("takes_seg") or "")
    assert data1["percent"] == "50"
    assert data1["date"] == "March 30, 2026"
    assert data1["remaining"] == "5"

    text2 = "馃敶**Study** Takes 馃弫dates h ||100% Settle by April 1, 2026"
    match2 = TIMELINER_PATTERN.search(text2)
    assert match2 is not None
    data2 = match2.groupdict()
    assert data2["prefix"] == "馃敶**Study**"
    assert "馃弫dates h" in (data2.get("takes_seg") or "")
    assert data2["percent"] == "100"
    assert data2["date"] == "April 1, 2026"
    assert data2["remaining"] is None

def test_parse_blocks():
    blocks = [
        {
            "type": "heading_2",
            "heading_2": {"rich_text": [{"plain_text": "Main Projects"}]}
        },
        {
            "type": "heading_3",
            "heading_3": {"rich_text": [{"plain_text": "Sub Projects"}]}
        },
        {
            "type": "bulleted_list_item",
            "id": "block1",
            "bulleted_list_item": {"rich_text": [{"plain_text": "馃煝**TestTheme** Takes `馃弫dates h` 2 ||10% Settle by May 2, 2026, but 馃敎 10"}]}
        }
    ]
    
    entries = parse_timeliner_blocks(blocks)
    assert len(entries) == 1
    
    e = entries[0]
    assert e.block_id == "block1"
    assert e.project == ""
    assert e.subproject == "Sub Projects"
    assert e.colour_subtheme == "TestTheme"
    assert e.status_emoji == "馃煝"
    assert e.time_expected_h == 2.0
    assert e.percent == 10
    assert e.settle_date == "2026-05-02"
    assert e.remaining_work_days == 10
    assert e.in_heading_scope is True


def test_parse_blocks_with_linev2_style_prefix(monkeypatch):
    monkeypatch.setattr(
        "timeliner_reader._structured_config",
        lambda: {
            "themes": {
                "PhDSettle✒": {
                    "name": "PhDSettle✒",
                    "sub_themes": ["Thesis", "SolarMan"],
                    "color": "red",
                }
            },
            "modes": [],
            "priorities": {},
            "task_types": {},
            "wbs_levels": {
                1: {"emoji": "🏭", "label": "(lv1)", "raw": "🏭 | (lv1)"},
                2: {"emoji": "🟧", "label": "(lv2)", "raw": "🟧 | (lv2)"},
            },
        },
    )
    blocks = [
        {
            "type": "heading_1",
            "heading_1": {"rich_text": [{"plain_text": "Main Projects"}]},
        },
        {
            "type": "paragraph",
            "id": "new-format-1",
            "paragraph": {
                "rich_text": [
                    {
                        "plain_text": "🟢Thesis🏭 Apparatus Learning: blablabla Takes 🏁dates h70 ||0% Settle by March 30, 2026, but 🔜 5"
                    }
                ]
            },
        },
    ]

    entries = parse_timeliner_blocks(blocks)
    assert len(entries) == 1

    e = entries[0]
    assert e.status_emoji == "🟢"
    assert e.colour_subtheme == "Thesis"
    assert e.tags["Task Theme with colour"] == "PhDSettle✒|Thesis"
    assert e.tags["WBS level"] == "🏭 | (lv1)"
    assert e.wbs_level == 1
    assert e.task_title == "Apparatus Learning"
    assert e.description == "blablabla"
    assert e.time_expected_h == 70.0
    assert e.percent == 0
    assert e.settle_date == "2026-03-30"


def test_parse_blocks_with_toggle_subproject_container():
    blocks = [
        {
            "type": "heading_2",
            "heading_2": {"rich_text": [{"plain_text": "Main Projects"}]},
            "has_children": False,
        },
        {
            "type": "toggle",
            "id": "toggle-sub",
            "has_children": True,
            "toggle": {"rich_text": [{"plain_text": "Sub Projects A"}]},
            "children_blocks": [
                {
                    "type": "bulleted_list_item",
                    "id": "block2",
                    "bulleted_list_item": {
                        "rich_text": [
                            {
                                "plain_text": "馃煝**ThemeX** Takes `馃弫dates h` 3 ||20% Settle by 2026-05-20, but 馃攷 8"
                            }
                        ]
                    },
                }
            ],
        },
    ]

    entries = parse_timeliner_blocks(blocks)
    assert len(entries) == 1

    e = entries[0]
    assert e.block_id == "block2"
    assert e.project == ""
    assert e.subproject == "Sub Projects A"
    assert e.colour_subtheme == "ThemeX"
    assert e.time_expected_h == 3.0
    assert e.percent == 20
    assert e.settle_date == "2026-05-20"
    assert e.remaining_work_days == 8
    assert e.in_heading_scope is True


def test_parse_blocks_with_main_and_sub_sections():
    blocks = [
        {
            "type": "heading_1",
            "heading_1": {"rich_text": [{"plain_text": "Main Projects"}]},
        },
        {
            "type": "heading_2",
            "heading_2": {"rich_text": [{"plain_text": "Fitness Main"}]},
        },
        {
            "type": "heading_1",
            "heading_1": {"rich_text": [{"plain_text": "Sub Projects"}]},
        },
        {
            "type": "heading_2",
            "heading_2": {"rich_text": [{"plain_text": "Morning Run"}]},
        },
        {
            "type": "bulleted_list_item",
            "id": "block-sub-1",
            "bulleted_list_item": {
                "rich_text": [
                    {
                        "plain_text": "馃煝**Cardio** Takes 馃弫dates h 1.5 ||30% Settle by 2026-05-03, but 馃敎 3"
                    }
                ]
            },
        },
    ]

    entries = parse_timeliner_blocks(blocks)
    assert len(entries) == 1

    e = entries[0]
    assert e.block_id == "block-sub-1"
    assert e.project == "Fitness Main"
    assert e.subproject == "Morning Run"
    assert e.colour_subtheme == "Cardio"
    assert e.time_expected_h == 1.5
    assert e.percent == 30
    assert e.settle_date == "2026-05-03"
    assert e.remaining_work_days == 3
    assert e.in_heading_scope is True


def test_parse_blocks_strips_corrupted_main_projects_prefix():
    blocks = [
        {
            "type": "heading_1",
            "heading_1": {"rich_text": [{"plain_text": "Main Projects"}]},
        },
        {
            "type": "bulleted_list_item",
            "id": "block-clean-1",
            "bulleted_list_item": {
                "rich_text": [
                    {
                        "plain_text": "馃煝**`科研人`** ain Projects RstV4 Takes `馃弫dates h`  || 0% Settle by April 18, 2026, but 馃敎 day"
                    }
                ]
            },
        }
    ]

    entries = parse_timeliner_blocks(blocks)
    assert len(entries) == 1
    assert entries[0].colour_subtheme == "RstV4"
    assert entries[0].in_heading_scope is True


def test_parse_blocks_infers_project_and_subproject_from_sections():
    blocks = [
        {
            "type": "heading_2",
            "heading_2": {"rich_text": [{"plain_text": "Main Projects"}]},
        },
        {
            "type": "paragraph",
            "id": "m1",
            "paragraph": {
                "rich_text": [
                    {
                        "plain_text": "🟢科研人 RstV4 Takes 🏁dates h || 0% Settle by 2026-04-18, but 🔜 day"
                    }
                ]
            },
        },
        {
            "type": "heading_2",
            "heading_2": {"rich_text": [{"plain_text": "Sub Projects"}]},
        },
        {
            "type": "paragraph",
            "id": "s1",
            "paragraph": {
                "rich_text": [
                    {
                        "plain_text": "🟢鍛造Maker 3dpF Takes 🏁dates h || % Settle by 2026-12-31, but 🔜"
                    }
                ]
            },
        },
    ]

    entries = parse_timeliner_blocks(blocks)
    assert len(entries) == 2

    main_entry = next(e for e in entries if e.block_id == "m1")
    assert main_entry.project == "科研人"
    assert main_entry.subproject == ""
    assert main_entry.colour_subtheme == "RstV4"
    assert main_entry.percent == 0
    assert main_entry.in_heading_scope is True

    sub_entry = next(e for e in entries if e.block_id == "s1")
    assert sub_entry.project == ""
    assert sub_entry.subproject == "鍛造Maker"
    assert sub_entry.colour_subtheme == "3dpF"
    assert sub_entry.percent == 0
    assert sub_entry.in_heading_scope is True


def test_parse_blocks_marks_outside_vs_heading_scope():
    blocks = [
        {
            "type": "paragraph",
            "id": "outside-1",
            "paragraph": {
                "rich_text": [
                    {
                        "plain_text": "🟢OutsideTask Takes 🏁dates h || 0% Settle by 2026-04-20, but 🔜 day"
                    }
                ]
            },
        },
        {
            "type": "heading_2",
            "heading_2": {"rich_text": [{"plain_text": "Main Projects"}]},
        },
        {
            "type": "paragraph",
            "id": "inside-1",
            "paragraph": {
                "rich_text": [
                    {
                        "plain_text": "🟢InsideTask Takes 🏁dates h || 0% Settle by 2026-04-21, but 🔜 day"
                    }
                ]
            },
        },
    ]

    entries = parse_timeliner_blocks(blocks)
    assert len(entries) == 1

    inside = next(e for e in entries if e.block_id == "inside-1")
    assert inside.in_heading_scope is True
