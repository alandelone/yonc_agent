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

    def propose(self, context: dict[str, Any], user_message: str, previous_proposal: dict[str, Any] | None = None) -> ProposalDraft:
        parent_title = str(context.get("parent", {}).get("title") or "当前目标")
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

    def propose(self, context: dict[str, Any], user_message: str, previous_proposal: dict[str, Any] | None = None) -> ProposalDraft:
        from llm_pipeline import split_task

        parent_title = str(context.get("parent", {}).get("title") or user_message or "当前目标")
        raw = split_task(parent_title, context=context)
        titles = [str(item).strip() for item in raw or [] if str(item).strip()]
        if not titles:
            return DeterministicSplitAdapter().propose(context, user_message, previous_proposal)
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
