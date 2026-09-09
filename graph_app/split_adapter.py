"""Model-agnostic task-decomposition adapter.

The adapter receives plain structured context and cannot access the database.
Production can opt into the repository's existing DSPy/Gemini ``split_task``
pipeline; tests and offline use rely on the deterministic implementation.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProposalDraft:
    rationale: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    actionability_results: list[dict[str, Any]]
    warnings: list[dict[str, Any]]


class SplitModelAdapter(Protocol):
    def propose(
        self,
        context: dict[str, Any],
        user_message: str,
        previous_proposal: dict[str, Any] | None = None,
        annotations: list[dict[str, Any]] | None = None,
    ) -> ProposalDraft: ...


def _action(temp_id: str, title: str, start_cue: str, done_when: str, minutes: int) -> dict[str, Any]:
    return {
        "temporary_id": temp_id,
        "title": title.strip()[:500],
        "node_kind": "WORK",
        "work_type": "ACTION",
        "stage": "READY",
        "status": "TODO",
        "description": "",
        "start_cue": start_cue,
        "inputs": [],
        "done_when": done_when,
        "estimated_effort_minutes": minutes,
        "estimate_source": "AI",
        "required": True,
        "tags": {},
    }


def _check_actionability(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "temporary_id": node["temporary_id"],
            "startable": bool(node.get("start_cue")),
            "observable_done": bool(node.get("done_when")),
            "single_intent": True,
            "bounded_effort": bool(node.get("estimated_effort_minutes")),
            "acceptable_decision_load": True,
            "valid": bool(node.get("start_cue") and node.get("done_when") and node.get("estimated_effort_minutes")),
        }
        for node in nodes
    ]


class DeterministicSplitAdapter:
    """Predictable proposal generator used offline and in automated tests."""

    def propose(
        self,
        context: dict[str, Any],
        user_message: str,
        previous_proposal: dict[str, Any] | None = None,
        annotations: list[dict[str, Any]] | None = None,
    ) -> ProposalDraft:
        parent_title = str(context.get("parent", {}).get("title") or "当前目标")
        annotations = annotations or []

        if previous_proposal and previous_proposal.get("nodes") and annotations:
            old_nodes = [dict(n) for n in previous_proposal["nodes"]]
            by_target: dict[str, list[dict[str, Any]]] = {}
            for ann in annotations:
                tid = ann.get("target_temporary_id")
                if tid:
                    by_target.setdefault(tid, []).append(ann)

            new_nodes: list[dict[str, Any]] = []
            for node in old_nodes:
                nid = node.get("temporary_id")
                anns = by_target.get(nid)
                if not anns:
                    new_nodes.append(node)
                    continue

                split_requested = False
                replacement_titles: list[str] = []
                for ann in anns:
                    comment = str(ann.get("comment", "")).strip()
                    highlighted = str(ann.get("highlighted_text", "")).strip()
                    clean_comment = re.sub(r"^(?:拆分为|拆分成|拆成|拆为|拆分|拆作|split into)\s*", "", comment, flags=re.IGNORECASE)
                    split_parts = [p.lstrip("为成:： ").strip() for p in re.split(r"[与和并,，;；\n]+", clean_comment) if p.lstrip("为成:： ").strip()]
                    if any(kw in comment for kw in ["拆", "分开", "split"]) and len(split_parts) >= 2:
                        split_requested = True
                        replacement_titles.extend(split_parts)
                    elif ann.get("field") == "done_when":
                        node["done_when"] = comment
                    elif ann.get("field") == "title" and comment:
                        if highlighted and highlighted in node.get("title", ""):
                            node["title"] = node.get("title", "").replace(highlighted, comment)
                        else:
                            node["title"] = comment

                if split_requested and replacement_titles:
                    for i, t in enumerate(replacement_titles):
                        sub_node = _action(
                            f"{nid}-sub{i+1}",
                            t,
                            f"打开与“{parent_title}”相关的资料，开始：{t}",
                            f"已产生可检查的“{t}”结果，并记录在项目资源中。",
                            max(30, int(node.get("estimated_effort_minutes", 60) / len(replacement_titles))),
                        )
                        new_nodes.append(sub_node)
                else:
                    new_nodes.append(node)

            reindexed_nodes = []
            for idx, node in enumerate(new_nodes):
                reindexed = dict(node)
                reindexed["temporary_id"] = f"draft-{idx + 1}"
                reindexed_nodes.append(reindexed)

            edges: list[dict[str, Any]] = []
            for node in reindexed_nodes:
                edges.append({"source": "parent", "target": node["temporary_id"], "relation": "contains", "required": True})
            for left, right in zip(reindexed_nodes, reindexed_nodes[1:]):
                edges.append({"source": right["temporary_id"], "target": left["temporary_id"], "relation": "depends_on", "required": True})

            return ProposalDraft(
                rationale=f"已根据对当前提案的 {len(annotations)} 处划词批注进行靶向调整。未批注项保持不变。",
                nodes=reindexed_nodes,
                edges=edges,
                actionability_results=_check_actionability(reindexed_nodes),
                warnings=[],
            )

        requested = [part.strip(" -\t") for part in re.split(r"[\n;；]+", user_message or "") if part.strip(" -\t")]
        if len(requested) >= 2:
            titles = requested[:6]
        elif previous_proposal and previous_proposal.get("nodes"):
            titles = [str(item.get("title") or "未命名行动") for item in previous_proposal["nodes"]]
        else:
            titles = [f"Clarify {parent_title}", f"Produce {parent_title} draft", f"Review {parent_title} result"]

        nodes = [
            _action(
                f"draft-{index + 1}",
                title,
                f"打开与“{parent_title}”相关的资料，开始：{title}",
                f"已产生可检查的“{title}”结果，并记录在项目资源中。",
                45 if index == 0 else 90,
            )
            for index, title in enumerate(titles)
        ]
        edges: list[dict[str, Any]] = []
        for node in nodes:
            edges.append({"source": "parent", "target": node["temporary_id"], "relation": "contains", "required": True})
        for left, right in zip(nodes, nodes[1:]):
            edges.append({"source": right["temporary_id"], "target": left["temporary_id"], "relation": "depends_on", "required": True})
        return ProposalDraft(
            rationale="这是一个可继续协商的初稿。每个叶节点都有明确的开始提示、完成条件和估算；提交前不会写入项目图。",
            nodes=nodes,
            edges=edges,
            actionability_results=_check_actionability(nodes),
            warnings=[],
        )


class ExistingDspySplitAdapter:
    """Thin wrapper around the repository's existing DSPy/Gemini splitter."""

    def propose(
        self,
        context: dict[str, Any],
        user_message: str,
        previous_proposal: dict[str, Any] | None = None,
        annotations: list[dict[str, Any]] | None = None,
    ) -> ProposalDraft:
        from llm_pipeline import split_task

        parent_title = str(context.get("parent", {}).get("title") or user_message or "当前目标")
        critique_notes = ""
        if annotations:
            notes = [
                f"- 对节点 [{ann.get('target_temporary_id')}] 的“{ann.get('field', 'title')}”（高亮词：“{ann.get('highlighted_text', '')}”）的批注：{ann.get('comment', '')}"
                for ann in annotations
            ]
            critique_notes = "\n【用户精准划词批注要求】:\n" + "\n".join(notes)
            user_message = f"{user_message}\n{critique_notes}".strip()

        raw = split_task(parent_title, context={**context, "annotations": annotations, "critique_notes": critique_notes})
        titles = [str(item).strip() for item in raw or [] if str(item).strip()]
        if not titles:
            return DeterministicSplitAdapter().propose(context, user_message, previous_proposal, annotations=annotations)
        nodes = [
            _action(
                f"draft-{index + 1}",
                title.split(":", 1)[0].strip(),
                f"打开“{parent_title}”上下文并开始：{title}",
                title.split(":", 1)[1].strip() if ":" in title else f"已完成并记录“{title}”的可检查结果。",
                60,
            )
            for index, title in enumerate(titles[:8])
        ]
        edges = [{"source": "parent", "target": node["temporary_id"], "relation": "contains", "required": True} for node in nodes]
        return ProposalDraft(
            rationale="已通过现有 DSPy/Gemini 拆分管线生成建议；请在提交前检查并调整。",
            nodes=nodes,
            edges=edges,
            actionability_results=_check_actionability(nodes),
            warnings=[],
        )


def get_split_adapter() -> SplitModelAdapter:
    return ExistingDspySplitAdapter() if os.getenv("YONC_SPLIT_ADAPTER", "").lower() == "dspy" else DeterministicSplitAdapter()
