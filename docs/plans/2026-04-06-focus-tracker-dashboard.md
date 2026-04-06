# Focus Tracker & Task Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a focus-tracking system with "💪🏿💪🏿💪🏿" emoji and a grouped dashboard view of tasks organized by Modes and Task Type from YoncTask_config.

**Architecture:** Two new modules (`focus_tracker.py` for emoji-based focus tracking with timestamps, `dashboard.py` for grouped views), plus CLI commands in `main.py`. Focus state persists in `data/focus_log.json`. The dashboard reads the merged task state and groups tasks using their `tags` dict, matching against config Modes and Task Types.

**Tech Stack:** Python 3.10+, Notion API (existing `notion_client.py`), JSON for persistence, existing `config_reader.py` for Modes/Task Type definitions.

---

## User Review Required

> [!IMPORTANT]
> **`live今目` Page ID**: The plan references a Notion page called `live今目` for task tracking. This page ID is **not** in the current `.env`. 
> - Is this the same page as `DFORGE_LINESV2_PAGE_ID` (the main task tree)?
> - Or a separate page? If separate, please provide the page ID.

> [!IMPORTANT]
> **Dashboard Output Format**: The plan assumes **terminal/CLI output** with ANSI colors for the dashboard. Should it be:
> - (A) Terminal output with colored text (current plan)
> - (B) A separate Notion page that gets updated
> - (C) Something else?

> [!WARNING]
> **Current Tags Gap**: The current task state only has `"Task Theme with colour"` and `"WBS level"` tags populated. **No tasks currently have `"Modes"` or `"Task Type"` tags assigned.** The dashboard will show most tasks under "Unassigned" until the `tag` pipeline is extended to assign Modes/Task Type, or until the user manually tags tasks. The dashboard will still work — it just won't have much to group yet.

---

## Proposed Changes

### Component 1: Focus Tracker Core

#### [NEW] [focus_tracker.py](file:///c:/Users/Alandelone/CodeSpace_Local/yonc_agent/focus_tracker.py)

Core module for 💪🏿💪🏿💪🏿 focus tracking:

- **`FOCUS_EMOJI = "💪🏿💪🏿💪🏿"`** constant
- **`find_focus_task(task_tree)`** — Recursively scan the task tree for the node whose `title` ends with the focus emoji. Returns `(block_id, title, node)` or `None`.
- **`list_focusable_tasks(task_tree)`** — Flatten the tree into a numbered list of leaf-level tasks (non-paragraph, non-heading blocks). Returns `List[dict]` with index, id, title, has_focus flag.
- **`move_focus_emoji(from_block_id, to_block_id)`** — Uses Notion API to:
  1. Read the current block's rich_text, strip the focus emoji from the end
  2. Update the old block (remove emoji)
  3. Read the target block's rich_text, append the focus emoji at the end
  4. Update the new block (add emoji)
- **`reset_focus_daily(task_tree, page_id)`** — Find where 💪🏿💪🏿💪🏿 currently is, remove it, and place it at the last empty row (last block with empty/whitespace-only text) of the page.
- **`record_focus_event(block_id, title, event_type)`** — Append to `data/focus_log.json` with timestamp, block_id, title, event_type ("start"/"end").
- **`track_focus(task_tree)`** — Main tracking function:
  1. Find current focus task
  2. Load last focus record from `data/focus_log.json`
  3. If focus has changed: record `end` for old task, record `start` for new task
  4. If first time: just record `start`
  5. Return current focus info

**Data file: `data/focus_log.json`**
```json
{
  "current_focus": {
    "block_id": "abc-123",
    "title": "Some task",
    "started_at": "2026-04-06T18:00:00+08:00"
  },
  "history": [
    {
      "block_id": "abc-123",
      "title": "Some task",
      "started_at": "2026-04-06T18:00:00+08:00",
      "ended_at": "2026-04-06T19:30:00+08:00"
    }
  ],
  "last_reset_date": "2026-04-06"
}
```

---

### Component 2: Task Dashboard

#### [NEW] [dashboard.py](file:///c:/Users/Alandelone/CodeSpace_Local/yonc_agent/dashboard.py)

Dashboard module that renders grouped task views in the terminal:

- **`group_tasks_by_mode(flat_state, structured_cfg)`** — Groups tasks by their `tags.Modes` value. Maps each mode name from config to a list of matching tasks. Tasks without mode tags go to "Unassigned".
- **`group_tasks_by_task_type(flat_state, structured_cfg)`** — Groups tasks by their `tags["Task Type"]` value. Tasks without type tags go to "Unassigned".
- **`get_theme_subheading(task)`** — Extract the theme/sub-theme tag from a task for use as sub-heading.
- **`render_dashboard(flat_state, structured_cfg)`** — Main render function:
  1. Print `### By Modes` (blue background heading)
  2. For each mode group: print mode name as bold sub-heading, then each task indented with theme sub-grouping
  3. Print `### By Task Type` (blue background heading)
  4. For each type group: same pattern
  5. Uses ANSI escape codes for blue background on headings, bold on sub-headings

Terminal output example:
```
╔══════════════════════════════════════╗
║           📋 By Modes               ║
╠══════════════════════════════════════╣

  ▸ 💻Focus (3 tasks)
    ├─ PhDSettle✒
    │  • Sustainable Rural Electrification Scheme Discussion
    │  • Cloud-Adaptive AI Forecast Algorithm
    ├─ 鍛造Lab
    │  • 3dp Tuning Up
    
  ▸ Handy🤘🏻 (2 tasks)
    ├─ 小事业们
    │  • 素食堂运营

╔══════════════════════════════════════╗
║         📋 By Task Type             ║
╠══════════════════════════════════════╣

  ▸ 🔍 测试 (1 task)
    ├─ PhDSettle✒
    │  • Stress Testing setup
```

---

### Component 3: CLI Integration

#### [MODIFY] [main.py](file:///c:/Users/Alandelone/CodeSpace_Local/yonc_agent/main.py)

Add 3 new CLI subcommands:

1. **`dashboard`** — Runs `cmd_dashboard()`: fetches task tree, loads config, renders grouped dashboard
2. **`focus`** — Runs `cmd_focus()`: 
   - No args → lists numbered tasks with 💪🏿💪🏿💪🏿 position indicator + usage guide
   - With `--move <N>` → moves focus to task number N
3. **`track`** — Runs `cmd_track()`: finds current focus, records timestamp in focus_log.json

#### [MODIFY] [config.py](file:///c:/Users/Alandelone/CodeSpace_Local/yonc_agent/config.py)

Add `LIVE_PAGE_ID` env variable for the `live今目` page (pending user answer on whether this is the same as DFORGE_LINESV2_PAGE_ID).

---

### Component 4: Tests

#### [NEW] [test_focus_tracker.py](file:///c:/Users/Alandelone/CodeSpace_Local/yonc_agent/tests/test_focus_tracker.py)

- `test_find_focus_in_tree` — mock tree with emoji in one node
- `test_find_focus_not_present` — tree without emoji returns None
- `test_list_focusable_tasks` — correct numbering and has_focus flag
- `test_record_focus_event` — writes correctly to focus_log.json
- `test_track_focus_first_call` — creates initial start record
- `test_track_focus_switch` — records end for old + start for new

#### [NEW] [test_dashboard.py](file:///c:/Users/Alandelone/CodeSpace_Local/yonc_agent/tests/test_dashboard.py)

- `test_group_by_mode_with_tags` — tasks with mode tags grouped correctly
- `test_group_by_mode_unassigned` — tasks without mode go to Unassigned
- `test_group_by_task_type` — tasks with type tags grouped correctly
- `test_render_dashboard_output` — capture stdout, verify headings present

---

## Open Questions

> [!IMPORTANT]
> 1. **`live今目` 页面** — 这是一个单独的 Notion 页面还是就是现有的 `DFORGE_LINESV2_PAGE_ID`？如果是独立页面，请提供 page ID。
> 2. **"最后一个空行"** — "put it back to original place (last empty row)" 是指页面最底部的空白 paragraph block 吗？还是最后一个没有内容的 bulleted_list_item？
> 3. **每日重置触发方式** — 应该是自动检测日期变化时重置，还是手动运行一个 `reset` 命令？
> 4. **Dashboard 输出** — 终端输出 OK 吗？还是需要写到一个 Notion 页面上？

## Verification Plan

### Automated Tests

```bash
# 运行所有新增测试
pytest tests/test_focus_tracker.py tests/test_dashboard.py -v

# 运行完整测试套件确保无回归
pytest tests/ -v
```

### Manual Verification

1. `python main.py dashboard` — 查看分组输出是否正确
2. `python main.py focus` — 查看编号任务列表
3. `python main.py focus --move 3` — 在 Notion 中验证 💪🏿💪🏿💪🏿 是否移动
4. `python main.py track` — 检查 `data/focus_log.json` 是否记录了 timestamp
