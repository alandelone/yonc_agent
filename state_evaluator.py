"""
状态机评估引擎：基于 Block Pattern 的响应式处理器。

替代原有的 flow-l1/l2/l3 分级管线，改为对每个 Block 独立评估其生命周期状态，
然后仅触发缺失的转换动作（Theme、WBS、Scope、Priority、Split、Mode 等）。
"""

import copy
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from block_info_reader import build_state_indexes
from config_reader import clean_task_title, load_config, structure_yonctask_config
from state_manager import STATE_FILE, flatten_tree, merge_states, save_state
from sync_engine import (
    push_root_order_to_notion,
    push_subtasks_to_notion,
    push_tags_to_notion,
    reparent_theme_containers,
    sync_from_notion,
)
from task_reader import fetch_and_build_task_tree

LOGGER = logging.getLogger(__name__)

# 阶段排序 emoji 集合（0️⃣ ~ 9️⃣）
PHASE_EMOJIS = [
    "0\uFE0F\u20E3",  # 0️⃣
    "1\uFE0F\u20E3",  # 1️⃣
    "2\uFE0F\u20E3",  # 2️⃣
    "3\uFE0F\u20E3",  # 3️⃣
    "4\uFE0F\u20E3",  # 4️⃣
    "5\uFE0F\u20E3",  # 5️⃣
    "6\uFE0F\u20E3",  # 6️⃣
    "7\uFE0F\u20E3",  # 7️⃣
    "8\uFE0F\u20E3",  # 8️⃣
    "9\uFE0F\u20E3",  # 9️⃣
]

# 防止无限生成的已拆解标志
_ALREADY_SPLIT_STAGES = {"suggested", "processed"}


# ─── 工具函数 ────────────────────────────────────────────


def _task_id(task: Dict[str, Any]) -> str:
    return str(task.get("notion_block_id") or task.get("id") or "")


def _task_title(task: Dict[str, Any]) -> str:
    return str(task.get("original_notion_title") or task.get("title") or "").strip()


def _log(stage: str, message: str) -> None:
    LOGGER.info("[%s] %s", stage, message)


def _extract_wbs_level(task: Dict[str, Any]) -> Optional[int]:
    level = task.get("wbs_level")
    if isinstance(level, str) and level.isdigit():
        level = int(level)
    return level if isinstance(level, int) else None


def detect_phase_emoji(title: str) -> Optional[int]:
    """从任务标题中检测阶段 emoji（0️⃣~9️⃣），返回对应数字或 None。"""
    for idx, emoji in enumerate(PHASE_EMOJIS):
        if emoji in title:
            return idx
    return None


# ─── 状态判定 ────────────────────────────────────────────


class BlockState:
    """Block 生命周期状态常量。"""

    RAW = "RAW"
    STRUCTURED = "STRUCTURED"
    SCOPED = "SCOPED"
    SEQUENCED = "SEQUENCED"
    EXPANDING = "EXPANDING"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    PHASING_WAIT = "PHASING_WAIT"
    ACTIONABLE_PENDING = "ACTIONABLE_PENDING"
    READY = "READY"
    COMPLETED = "COMPLETED"
    SKIP = "SKIP"  # 不需要处理的结构容器（如 paragraph/heading 主题块）


def evaluate_block_state(
    task: Dict[str, Any],
    children_by_parent: Dict[str, List[Dict[str, Any]]],
) -> str:
    """基于当前 Block 的属性模式，判定其所处的生命周期状态。"""

    tid = _task_id(task)
    tags = task.get("tags") or {}
    wbs_level = _extract_wbs_level(task)
    is_generated = bool(task.get("is_generated"))
    generated_selection_processed = bool(task.get("generated_selection_processed", False))
    checked = task.get("checked")
    split_stage = str(task.get("split_stage", "none")).lower()
    notion_type = task.get("notion_type") or task.get("type") or ""
    depth = task.get("depth", 0)
    try:
        depth = int(depth)
    except (TypeError, ValueError):
        depth = 0

    if task.get("is_content_block") or notion_type == "quote":
        return BlockState.SKIP

    # ── COMPLETED：已勾选的非选择模式任务
    if notion_type in ("to_do", "todo") and checked is True and not (
        is_generated and not generated_selection_processed
    ):
        return BlockState.COMPLETED

    # ── SKIP：主题容器块（paragraph/heading 且作为父节点）
    if notion_type in ("paragraph", "heading_1", "heading_2", "heading_3"):
        return BlockState.SKIP

    # ── RAW：缺少 Theme 标签
    theme_tag = str(tags.get("Task Theme with colour", "")).strip()
    if not theme_tag:
        return BlockState.RAW

    # ── STRUCTURED：有 Theme 但缺少 WBS
    if wbs_level is None:
        return BlockState.STRUCTURED

    # ── SCOPED：有 WBS 但缺少 Timeliner Scope
    timeliner_rank = task.get("timeliner_rank")
    if timeliner_rank is None:
        return BlockState.SCOPED

    # ── SEQUENCED：有 Scope 但缺少 Priority
    priority_tag = str(tags.get("Priority", "")).strip()
    if not priority_tag:
        return BlockState.SEQUENCED

    # ── EXPANDING：WBS < 4 且没有子节点且从未拆解过
    children = children_by_parent.get(tid, [])
    if isinstance(wbs_level, int) and wbs_level < 4:
        has_no_children = len(children) == 0
        never_split = split_stage not in _ALREADY_SPLIT_STAGES
        not_generated = not is_generated  # 不拆解 LLM 生成的任务

        if has_no_children and never_split and (not is_generated or generated_selection_processed):
            return BlockState.EXPANDING

    # ── HUMAN_REVIEW：有 LLM 生成的子任务但尚未被人类审阅
    if split_stage == "suggested":
        generated_children = [
            c for c in children if bool(c.get("is_generated"))
        ]
        unreviewed = [
            c for c in generated_children
            if not bool(c.get("generated_selection_processed", False))
        ]
        if unreviewed:
            return BlockState.HUMAN_REVIEW

    # ── PHASING_WAIT：Depth=1 的大模块缺少阶段 emoji
    if depth == 1 and isinstance(wbs_level, int) and wbs_level in (2, 3):
        title = _task_title(task)
        phase = detect_phase_emoji(title)
        if phase is None:
            return BlockState.PHASING_WAIT

    # ── ACTIONABLE_PENDING：WBS=4 叶子节点缺少 Mode/TaskType
    if isinstance(wbs_level, int) and wbs_level == 4:
        # 对于 LLM 生成的任务，必须先被人类确认后才进入此状态
        if is_generated and not generated_selection_processed:
            return BlockState.HUMAN_REVIEW

        mode_tag = str(tags.get("Modes", "")).strip()
        tasktype_tag = str(tags.get("Task Type", "")).strip()
        if not mode_tag or not tasktype_tag:
            return BlockState.ACTIONABLE_PENDING

    # ── READY：所有属性就绪
    return BlockState.READY


# ─── Phase 子排序 ────────────────────────────────────────────


def _reorder_children_by_phase(state: List[Dict[str, Any]]) -> int:
    """
    在每个项目内部，按 Phase emoji (0️⃣~9️⃣) 对 depth=1 子模块做物理排序。

    工作方式：
    1. 按 parent_id 分组所有 depth=1 且标题带 Phase emoji 的 block
    2. 在每组内比较当前物理顺序与按 Phase 排列的期望顺序
    3. 如果不一致，使用 Notion API 逐个移动到正确位置

    Returns: 实际移动的 block 数量
    """
    from collections import defaultdict
    from notion_client import append_children, delete_block, get_page_blocks

    # 收集所有 depth=1 且带 Phase emoji 的 block，按 parent 分组
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for task in state:
        depth = task.get("depth", 0)
        try:
            depth = int(depth)
        except (TypeError, ValueError):
            depth = 0
        if depth != 1:
            continue

        title = _task_title(task)
        phase = detect_phase_emoji(title)
        if phase is None:
            continue

        parent_id = str(task.get("parent_id") or "")
        if not parent_id:
            continue

        groups[parent_id].append(task)

    total_moved = 0

    for parent_id, children in groups.items():
        if len(children) < 2:
            continue

        # 当前物理顺序（按它们在 state 列表中的出现先后）
        state_index = {_task_id(t): idx for idx, t in enumerate(state) if _task_id(t)}
        current_order = sorted(children, key=lambda t: state_index.get(_task_id(t), 0))
        current_ids = [_task_id(t) for t in current_order]

        # 期望顺序：按 Phase 数字升序，同 Phase 保持原顺序
        desired_order = sorted(
            children,
            key=lambda t: (
                detect_phase_emoji(_task_title(t)) or 99,
                state_index.get(_task_id(t), 0),
            ),
        )
        desired_ids = [_task_id(t) for t in desired_order]

        # 如果顺序已经正确，跳过
        if current_ids == desired_ids:
            continue

        # 逐个移动不在正确位置的 block
        # 策略：从第二个开始，确保每个 block 在其前一个 block 之后
        import sys

        for i in range(1, len(desired_order)):
            prev_id = _task_id(desired_order[i - 1])
            curr_task = desired_order[i]
            curr_id = _task_id(curr_task)

            # 检查在 Notion 中 curr_id 是否已经在 prev_id 之后
            # 如果当前顺序中 curr_id 的位置已经正确，跳过
            if i < len(current_ids) and current_ids[i] == curr_id:
                continue

            # 构建 block payload 以重新创建
            block_type = curr_task.get("notion_type") or curr_task.get("type") or ""
            if block_type == "todo":
                block_type = "to_do"
            elif block_type == "bullet":
                block_type = "bulleted_list_item"

            title = str(
                curr_task.get("original_notion_title", curr_task.get("title", "")) or ""
            ).strip() or " "
            rich_text = [{"type": "text", "text": {"content": title}}]

            if block_type == "to_do":
                new_block_payload = {
                    "object": "block",
                    "type": "to_do",
                    "to_do": {
                        "rich_text": rich_text,
                        "checked": bool(curr_task.get("checked")),
                    },
                }
            else:
                safe_type = (
                    block_type
                    if block_type
                    in (
                        "bulleted_list_item",
                        "numbered_list_item",
                        "toggle",
                        "paragraph",
                    )
                    else "bulleted_list_item"
                )
                new_block_payload = {
                    "object": "block",
                    "type": safe_type,
                    safe_type: {"rich_text": rich_text},
                }

            try:
                # 在 prev_id 之后插入新 block
                append_res = append_children(
                    parent_id, [new_block_payload], after_id=prev_id
                )
                results = append_res.get("results", [])
                if results:
                    new_id = str(results[0].get("id", ""))
                    # 删除原始 block
                    delete_block(curr_id)

                    # 更新 state 中的 ID
                    curr_task["id"] = new_id
                    curr_task["notion_block_id"] = new_id

                    # 更新 desired_order 中后续引用
                    for j in range(i + 1, len(desired_order)):
                        if _task_id(desired_order[j]) == curr_id:
                            desired_order[j]["id"] = new_id
                            desired_order[j]["notion_block_id"] = new_id

                    total_moved += 1
                    phase_num = detect_phase_emoji(_task_title(curr_task))
                    sys.stdout.buffer.write(
                        f"  -> Phase {phase_num}: moved '{title[:30]}' after prev block\n".encode(
                            "utf-8"
                        )
                    )
            except Exception as e:
                sys.stdout.buffer.write(
                    f"  -> Failed to move phase block {curr_id}: {e}\n".encode("utf-8")
                )

    return total_moved


# ─── 主评估循环 ────────────────────────────────────────────


def run_evaluator() -> List[Dict[str, Any]]:
    """
    状态机主循环：拉取任务树 -> 逐节点评估 -> 触发缺失的转换 -> 写回。

    取代原有 run_flow / run_l1 / run_l2 / run_l3 的分级执行逻辑。
    """
    _log("Evaluator", "Starting state-driven flow evaluation")

    # ── Step 0: 加载合并状态 ──
    config_dict = load_config()
    structured_cfg = structure_yonctask_config(config_dict)

    notion_tree = fetch_and_build_task_tree()
    if not notion_tree:
        _log("Evaluator", "No tasks found in Notion")
        print("No tasks found in Notion.")
        return []

    flat_notion = flatten_tree(notion_tree)
    working_state = sync_from_notion(flat_notion)
    state = merge_states(notion_tree, working_state)
    _log("Evaluator", f"Loaded {len(state)} merged tasks")

    # ── Step 1: RAW -> Theme 解析 ──
    _log("Evaluator", "Phase: Theme Resolution")
    from llm_pipeline import theme_pass

    state = theme_pass(state, config_dict)
    state = reparent_theme_containers(state, config_dict)
    _log("Evaluator", "Theme pass complete")

    # ── Step 2: STRUCTURED -> WBS 计算 ──
    _log("Evaluator", "Phase: WBS Calculation")
    _bootstrap_timeliner_if_needed()
    from flow_pipeline import build_timeliner_scope

    scoped_ids, rank_by_task_id, _ = build_timeliner_scope(state)
    _log("Evaluator", f"Scoped {len(scoped_ids)} tasks from TIMELINER")

    from llm_pipeline import wbs_pass

    state = wbs_pass(state, config_dict, scoped_ids=scoped_ids)
    _log("Evaluator", "WBS pass complete")

    # ── Step 3: SCOPED -> Scope 锚定 (已在 build_timeliner_scope 中完成) ──

    # ── Step 4: SEQUENCED -> Priority 计算 ──
    _log("Evaluator", "Phase: Priority Calculation")
    from llm_pipeline import priority_pass

    before_priority = copy.deepcopy(state)
    state = priority_pass(
        state, config_dict, scoped_ids=scoped_ids, rank_by_task_id=rank_by_task_id
    )
    _log("Evaluator", "Priority pass complete")

    # ── Step 5: 物理排序（Root Rank + Phase 子排序）──
    _log("Evaluator", "Phase: Physical Ordering")
    from flow_pipeline import _reorder_state_by_root_rank

    before_reorder = copy.deepcopy(state)
    state = _reorder_state_by_root_rank(state)
    state = push_root_order_to_notion(before_reorder, state)
    _log("Evaluator", "Root-level physical ordering complete")

    # Phase 子排序：在每个项目内部，按 Phase emoji 排列 Depth=1 的子模块
    phase_moved = _reorder_children_by_phase(state)
    if phase_moved > 0:
        _log("Evaluator", f"Phase ordering: physically moved {phase_moved} blocks")
    else:
        _log("Evaluator", "Phase ordering: no blocks need moving")

    # ── Step 6: 推送标签到 Notion ──
    push_tags_to_notion(state, config_dict)
    _log("Evaluator", "Tag push to Notion complete")
    state = [task for task in state if not task.get("deleted")]

    # ── Step 7: EXPANDING -> 任务拆解（仅针对首次未拆解的节点）──
    _log("Evaluator", "Phase: Task Splitting (scoped, first-time only)")
    _, children_by_parent = build_state_indexes(state)

    split_parent_count = 0
    split_subtask_count = 0
    for task in list(state):
        block_state = evaluate_block_state(task, children_by_parent)
        if block_state != BlockState.EXPANDING:
            continue

        tid = _task_id(task)
        if tid not in scoped_ids:
            continue

        raw_title = task.get("original_notion_title", task.get("title", ""))
        clean_title = clean_task_title(raw_title, structured_cfg)
        if not any(c.isalnum() for c in clean_title):
            continue

        # 检查已完成标记
        if task.get("checked") or "💯✅" in raw_title:
            continue

        # 仅对 bullet/toggle 类型的大任务做拆解
        notion_type = task.get("notion_type") or task.get("type")
        if notion_type not in ("bulleted_list_item", "bullet", "toggle"):
            continue

        from block_info_reader import build_split_context
        from llm_pipeline import split_task

        context_payload = build_split_context(state, task)
        try:
            suggested = split_task(clean_title, context=context_payload)
        except Exception as exc:
            print(f"Failed to split task {tid}: {exc}")
            continue

        if not suggested:
            continue

        # 去重已有子节点标题
        existing_children = children_by_parent.get(tid, [])
        existing_titles = {
            str(c.get("original_notion_title", c.get("title", ""))).strip().lower()
            for c in existing_children
            if str(c.get("original_notion_title", c.get("title", ""))).strip()
        }
        deduped = []
        for s in suggested:
            key = str(s or "").strip().lower()
            if not key or key in existing_titles:
                continue
            existing_titles.add(key)
            deduped.append(str(s).strip())

        if not deduped:
            continue

        from flow_pipeline import (
            _register_generated_subtasks,
            _resolve_parent_theme_for_split,
        )
        from datetime import datetime

        parent_theme, parent_theme_color = _resolve_parent_theme_for_split(
            task, structured_cfg
        )
        created_subtasks = push_subtasks_to_notion(
            tid, deduped, parent_theme, parent_theme_color
        )
        _register_generated_subtasks(state, task, created_subtasks)
        task["split_stage"] = "suggested"
        task["split_batch_id"] = datetime.utcnow().isoformat() + "Z"
        split_parent_count += 1
        split_subtask_count += len(deduped)

    _log(
        "Evaluator",
        f"Split pass: {split_subtask_count} subtasks across {split_parent_count} parents",
    )

    # ── Step 8: ACTIONABLE_PENDING -> Mode/TaskType 推理 ──
    _log("Evaluator", "Phase: Mode/TaskType Inference")
    _, children_by_parent = build_state_indexes(state)

    from llm_pipeline import mode_tasktype_pass

    # 筛选出真正需要推理 Mode 的节点 ID
    actionable_ids: Set[str] = set()
    for task in state:
        block_state = evaluate_block_state(task, children_by_parent)
        if block_state == BlockState.ACTIONABLE_PENDING:
            tid = _task_id(task)
            if tid:
                actionable_ids.add(tid)

    if actionable_ids:
        state = mode_tasktype_pass(state, config_dict, scoped_ids=actionable_ids)
        _log("Evaluator", f"Mode/TaskType inferred for {len(actionable_ids)} tasks")

        # 重新推送带有 Mode 的标签
        push_tags_to_notion(state, config_dict)
        state = [task for task in state if not task.get("deleted")]
    else:
        _log("Evaluator", "No ACTIONABLE_PENDING tasks found, skipping Mode pass")

    # ── Step 9: 生成状态报告 ──
    _, children_by_parent = build_state_indexes(state)
    state_counts: Dict[str, int] = {}
    halted_blocks: List[str] = []
    for task in state:
        block_state = evaluate_block_state(task, children_by_parent)
        state_counts[block_state] = state_counts.get(block_state, 0) + 1
        if block_state in (BlockState.HUMAN_REVIEW, BlockState.PHASING_WAIT):
            title = _task_title(task)[:40]
            halted_blocks.append(f"  [{block_state}] {title}")

    _log("Evaluator", f"State distribution: {state_counts}")
    if halted_blocks:
        _log("Evaluator", f"Halted blocks requiring human action ({len(halted_blocks)}):")
        for line in halted_blocks[:10]:
            _log("Evaluator", line)

    # ── Step 10: 保存状态 ──
    save_state(state, STATE_FILE)
    _log("Evaluator", f"Saved {len(state)} tasks to state")
    print(f"Flow complete. State distribution: {state_counts}")
    return state


def _bootstrap_timeliner_if_needed() -> None:
    """确保 timeliner_state.json 缓存可用。"""
    from flow_pipeline import _bootstrap_timeliner_state_if_needed

    _bootstrap_timeliner_state_if_needed("Evaluator")
