"""Narrow stdio MCP facade for the Yonc semantic project API.

The process owns service credentials. They are never accepted as tool arguments or
returned to the model. Graph writes remain behind version checks and a single-use
user authorization created by the trusted local UI.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - gives a useful error in minimal installs
    FastMCP = None  # type: ignore[assignment]


API_URL = os.getenv("YONC_API_URL", "http://127.0.0.1:8765").rstrip("/")
MAX_RESULTS = 50


def _request(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, commit: bool = False) -> Any:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if commit:
        token = os.getenv("YONC_AGENT_COMMIT_TOKEN", "").strip()
        if not token:
            raise PermissionError("YONC_AGENT_COMMIT_TOKEN is not configured.")
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{API_URL}{path}",
        data=json.dumps(payload or {}).encode("utf-8") if payload is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - loopback URL is operator configured
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"Yonc API returned HTTP {exc.code}: {detail}") from exc


def _bounded(value: int, maximum: int = MAX_RESULTS) -> int:
    return max(1, min(int(value), maximum))


if FastMCP is not None:
    mcp = FastMCP("yonc-project")

    @mcp.tool()
    def yonc_status() -> dict[str, Any]:
        """Verify the Yonc API, schema, graph version, and database identity."""
        return _request("/api/v2/health")

    @mcp.tool()
    def yonc_search_projects(query: str, limit: int = 20) -> dict[str, Any]:
        """Search the committed project graph by title or description."""
        graph = _request("/api/v2/graph")
        needle = query.strip().casefold()
        nodes = [
            node for node in graph.get("nodes", [])
            if not needle
            or needle in str(node.get("title", "")).casefold()
            or needle in str(node.get("description", "")).casefold()
        ][:_bounded(limit)]
        return {"graph_version": graph.get("graph_version"), "count": len(nodes), "nodes": nodes}

    @mcp.tool()
    def yonc_get_node_context(node_id: str) -> dict[str, Any]:
        """Read one project node together with its bounded graph context."""
        return _request(f"/api/v2/graph?scope_node_id={urllib.parse.quote(node_id)}")

    @mcp.tool()
    def yonc_list_split_sessions(parent_node_id: str = "", state: str = "") -> list[dict[str, Any]]:
        """List split discussions and their current draft state."""
        query = urllib.parse.urlencode({key: value for key, value in {"parent_node_id": parent_node_id, "state": state}.items() if value})
        result = _request(f"/api/v2/split-sessions{'?' + query if query else ''}")
        return result[:MAX_RESULTS]

    @mcp.tool()
    def yonc_start_split(parent_node_id: str, message: str = "") -> dict[str, Any]:
        """Start a scoped draft discussion; this never writes to the committed graph."""
        return _request("/api/v2/split-sessions", method="POST", payload={"parent_node_id": parent_node_id, "message": message or None})

    @mcp.tool()
    def yonc_continue_split(session_id: str, message: str) -> dict[str, Any]:
        """Continue a split discussion and persist its next immutable proposal version."""
        return _request(f"/api/v2/split-sessions/{urllib.parse.quote(session_id)}/messages", method="POST", payload={"content": message, "annotations": []})

    @mcp.tool()
    def yonc_validate_split(session_id: str) -> dict[str, Any]:
        """Run structural and semantic readiness checks without committing."""
        return _request(f"/api/v2/split-sessions/{urllib.parse.quote(session_id)}/validate", method="POST", payload={})

    @mcp.tool()
    def yonc_commit_authorized_split(session_id: str, authorization_id: str) -> dict[str, Any]:
        """Commit only a proposal covered by a fresh single-use user authorization."""
        return _request(
            f"/api/v2/agent/split-sessions/{urllib.parse.quote(session_id)}/commit",
            method="POST",
            payload={"authorization_id": authorization_id},
            commit=True,
        )

    @mcp.tool()
    def yonc_recent_history(limit: int = 20) -> list[dict[str, Any]]:
        """Read recent committed operation batches for traceability."""
        return _request(f"/api/v2/operation-batches?limit={_bounded(limit, 100)}")


def main() -> None:
    if FastMCP is None:
        raise SystemExit("The 'mcp' package is required. Install project requirements first.")
    mcp.run()


if __name__ == "__main__":
    main()
