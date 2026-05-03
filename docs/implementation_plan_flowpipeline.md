# Fix: Toggle List Fails to Append Suggested Subtasks

## Root Cause Analysis

I traced the full execution path of `run_l2` for the "Thesis Phd Logic" task. There are **two distinct bugs** that compound to prevent subtask appending.

### Bug 1: `_condense_description` blocks `split_task` from returning (IMMEDIATE CAUSE)

The `split_task()` function at [llm_pipeline.py:279](file:///c:/test_codespace/yonc_agent/llm_pipeline.py#L279) calls `_format_title_desc()` for **each** work package, which in turn calls `_condense_description()` — an **additional LLM call per item**. With 5 work packages, that's 5 extra LLM calls (on top of 2 already: classify + decompose = **7 total LLM calls** for a single task split).

The KeyboardInterrupt trace confirms it died here:
```
llm_pipeline.py line 206, in _format_title_desc
llm_pipeline.py line 195, in _condense_description
```

Because `split_task()` never returned, `push_subtasks_to_notion()` was **never reached**. The subtasks were never appended.

### Bug 2: Root reordering destroys overflow quotes (RECURRING CAUSE)

Even if Bug 1 is fixed and subtasks ARE appended, every subsequent `run_l2` will **destroy the quote child** during Physical Root Rank Reordering:

1. `push_root_order_to_notion` clones task trees using `_batch_clone_children`, which builds payloads from `children_map`
2. `children_map` is built **only from the application state** — tasks tracked in `state[]`
3. The overflow quote (`> the`) is a Notion block of type `"quote"`, but [task_reader.py:32](file:///c:/test_codespace/yonc_agent/task_reader.py#L32) only processes: `bulleted_list_item`, `numbered_list_item`, `to_do`, `toggle`, `paragraph`
4. **Quote blocks are silently dropped** — never entering the state tree
5. When the root is cloned → old block deleted → quote child is destroyed with it
6. Next run: `push_tags_to_notion` detects overflow again (since `original_notion_title` in state still has the full text) → recreates toggle + quote → this wipes any existing subtask children by calling `replace_with_toggle_item` with **only** `overflow_children=[quote]`, discarding the subtasks

This creates a destructive cycle: **overflow reconversion kills subtasks on every run**.

### Execution Flow Trace

```
run_l2()
 ├─ _load_merged_state()
 │   ├─ fetch_and_build_task_tree()     ← quote child DROPPED (not in type whitelist)
 │   ├─ flatten_tree()                  ← original_notion_title = FULL title (with "the")
 │   ├─ sync_from_notion()
 │   └─ merge_states()                  ← preserves split_stage from saved state
 │
 ├─ theme_pass / reparent              ← OK
 ├─ build_timeliner_scope              ← scopes task, sets timeliner_rank
 ├─ wbs_pass                           ← sets wbs_level (likely 2)
 ├─ priority_pass                      ← OK
 │
 ├─ push_root_order_to_notion()        ← ⚠️ Bug 2: clones toggle WITHOUT quote child
 │                                        Old toggle (with quote) DELETED
 │                                        New toggle created with full title, NO quote
 │
 ├─ push_tags_to_notion()              ← Detects overflow on full title
 │                                        Converts to toggle + quote("the")
 │                                        ⚠️ If subtasks existed, they're WIPED
 │
 ├─ _split_scoped_tasks()
 │   ├─ split_task(clean_title)        ← LLM: classify(1) + decompose(1) = 2 calls
 │   │   └─ _format_title_desc() × 5  ← ❌ Bug 1: 5 more LLM calls via _condense_description
 │   │       └─ _condense_description  ← KeyboardInterrupt HERE
 │   │
 │   └─ push_subtasks_to_notion()      ← NEVER REACHED
 │
 └─ save_state()                       ← NEVER REACHED (process crashed)
```

## Proposed Changes

---

### Component 1: Fix the immediate blocker (`llm_pipeline.py`)

#### [MODIFY] [llm_pipeline.py](file:///c:/test_codespace/yonc_agent/llm_pipeline.py)

**Skip `_condense_description` for short descriptions.** The LLM-generated descriptions from `DeliverableItem` are already concise (one sentence). Condensing a 5-word description via a full LLM call is wasteful.

```python
# _condense_description (line ~189)
def _condense_description(description: str) -> str:
    if not description.strip():
        return ""
    # Skip condensation for already-short descriptions (< 60 chars)
    if len(description.strip()) < 60:
        return description.strip()
    # ... existing LLM call
```

This alone reduces 5 LLM calls to 0 for the typical split-task flow, cutting the split phase from ~7 calls to ~2.

---

### Component 2: Fix the destructive reconversion cycle (`sync_engine.py`)

#### [MODIFY] [sync_engine.py](file:///c:/test_codespace/yonc_agent/sync_engine.py) — `push_tags_to_notion` overflow section

**When converting to toggle, preserve existing children.** Currently at [line 1042-1060](file:///c:/test_codespace/yonc_agent/sync_engine.py#L1042), overflow conversion creates the toggle with ONLY the quote child. Fix: fetch existing children first and include them alongside the overflow quote.

```python
# Before replace_with_toggle_item, fetch and preserve existing children
from notion_client import get_page_blocks
existing_notion_children = []
try:
    existing_notion_children = get_page_blocks(block_id)
except Exception:
    pass

# Build overflow quote as first child, then append existing children
overflow_children = [{ ... quote block ... }]

# Re-create any non-quote children that already exist
for existing_child in existing_notion_children:
    etype = existing_child.get("type", "")
    if etype == "quote":
        continue  # Skip — we're replacing with our formatted quote
    # Rebuild payload from raw Notion block
    overflow_children.append(_rebuild_notion_block_payload(existing_child))
```

> [!WARNING]
> This adds 1 API call (`get_page_blocks`) per overflow conversion, but this only triggers for tasks whose title exceeds the character limit — a rare event. The alternative (losing subtasks) is unacceptable.

---

### Component 3: Preserve non-task children during root reordering (`sync_engine.py`)

#### [MODIFY] [sync_engine.py](file:///c:/test_codespace/yonc_agent/sync_engine.py) — `_batch_clone_children` in `push_root_order_to_notion`

**Fetch and clone Notion-only children that aren't tracked in state.** When a task `has_children` in Notion but `children_map` has no entries for it, those orphan children (quotes, manual notes) are currently lost.

Add a helper `_fetch_and_clone_orphan_children` that:
1. Calls `get_page_blocks(source_id)` to get actual Notion children
2. Filters out children already present in `children_map` (by ID)
3. Rebuilds the remaining blocks as payloads and appends them under the new parent

This is called at the end of `_batch_clone_children` after processing state-tracked grandchildren.

> [!IMPORTANT]
> This requires a new utility function `_rebuild_notion_block_payload(block)` that converts a raw Notion API block response back into a valid `append_children` payload. This is needed by both Component 2 and Component 3.

---

## Summary of Changes

| File | Change | LLM calls saved | API calls added |
|------|--------|-----------------|-----------------|
| `llm_pipeline.py` | Skip condensation for short descriptions | ~5 per split | 0 |
| `sync_engine.py` | Preserve children during overflow conversion | 0 | 1 per overflow (rare) |
| `sync_engine.py` | Clone orphan children during root reordering | 0 | 1 per moved root with orphans |

## Verification Plan

### Automated Tests
- `cmd /c python -m pytest tests/ -x -q` — ensure no regressions
- Manual run: `cmd /c python main.py flow-l2` — verify:
  1. No KeyboardInterrupt during split phase
  2. Subtasks appear under "Thesis Phd Logic" toggle
  3. Quote `> the` remains at the top of children
  4. Second run does NOT destroy the subtasks
