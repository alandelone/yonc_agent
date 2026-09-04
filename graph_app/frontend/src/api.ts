import type { GraphResponse, SplitSession, TimelineResponse } from "./types";

const chineseByCode: Record<string, string> = {
  GRAPH_VERSION_CONFLICT: "项目图已发生变化。请刷新上下文并重新确认。",
  PROPOSAL_VERSION_CONFLICT: "提案版本已更新。请查看最新提案后再提交。",
  MULTIPLE_CONTAINS_PARENTS: "一个正式节点只能有一个结构父节点。",
  GRAPH_CYCLE: "此操作会形成循环关系，因此没有应用。",
  DEADLINE_CONFLICT: "计划范围超过了截止日期。",
  ANCESTOR_DEADLINE_CONFLICT: "计划范围超过了父级截止日期。",
  DEPENDENCY_ORDER_CONFLICT: "计划顺序违反了依赖关系。",
  USER_ONLY_DONE: "完成状态只能由你确认。",
  TERMINAL_REASON_REQUIRED: "请输入取消或替代原因。",
  ACTIONABILITY_FAILED: "行动仍缺少开始提示或可检查的完成条件。",
  INVALID_PROPOSAL: "当前提案未通过检查，请先调整。",
  INSUFFICIENT_HISTORY: "历史完成数据不足，暂不显示预计完成日期。",
  BATCH_ALREADY_UNDONE: "这一步已经撤销。",
  BATCH_NOT_UNDOABLE: "这一步目前无法撤销。",
  BATCH_NOT_FOUND: "找不到需要撤销的操作。",
};

export type OperationBatchSummary = {
  id: string;
  actor_channel: string;
  source: string;
  graph_version_before: number;
  graph_version_after: number;
  undone_at: string | null;
  created_at: string;
};

export class ApiError extends Error {
  code: string;
  params: Record<string, unknown>;

  constructor(code: string, params: Record<string, unknown> = {}) {
    super(chineseByCode[code] ?? "操作未完成，请重试。");
    this.code = code;
    this.params = params;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.error ?? body.detail ?? {};
    throw new ApiError(detail.code ?? "UNKNOWN_ERROR", detail.params ?? {});
  }
  return body as T;
}

export const api = {
  graph: (scope?: string | null) => request<GraphResponse>(`/api/v2/graph${scope ? `?scope_node_id=${encodeURIComponent(scope)}` : ""}`),
  timeline: (start?: string, end?: string, scope?: string | null) => {
    const params = new URLSearchParams();
    if (start) params.set("start", start);
    if (end) params.set("end", end);
    if (scope) params.set("scope_node_id", scope);
    return request<TimelineResponse>(`/api/v2/timeline?${params}`);
  },
  transition: (nodeId: string, action: string, graphVersion: number, reason?: string) =>
    request<{ graph_version: number; operation_batch_id: string }>(`/api/v2/nodes/${nodeId}/transition`, { method: "POST", body: JSON.stringify({ action, reason, expected_graph_version: graphVersion }) }),
  schedule: (nodeId: string, start: string, end: string | null, graphVersion: number, autoSpan = false, preview = false) =>
    request<{ graph_version: number; operation_batch_id?: string; planned_start: string; planned_end: string; valid?: boolean }>(`/api/v2/nodes/${nodeId}/schedule`, { method: "PUT", body: JSON.stringify({ planned_start: start, planned_end: end, auto_span: autoSpan, preview, expected_graph_version: graphVersion }) }),
  patchNode: (nodeId: string, values: Record<string, unknown>, graphVersion: number) =>
    request<{ graph_version: number; operation_batch_id: string }>(`/api/v2/nodes/${nodeId}`, { method: "PATCH", body: JSON.stringify({ ...values, expected_graph_version: graphVersion }) }),
  viewState: (view: "canvas" | "timeline", scope?: string | null) => request<Record<string, unknown>>(`/api/v2/view-state/${view}${scope ? `?scope_node_id=${encodeURIComponent(scope)}` : ""}`),
  saveViewState: (view: "canvas" | "timeline", values: Record<string, unknown>, scope?: string | null) => request<Record<string, unknown>>(`/api/v2/view-state/${view}${scope ? `?scope_node_id=${encodeURIComponent(scope)}` : ""}`, { method: "PUT", body: JSON.stringify(values) }),
  startSplit: (parentNodeId: string) => request<SplitSession>("/api/v2/split-sessions", { method: "POST", body: JSON.stringify({ parent_node_id: parentNodeId }) }),
  splitMessage: (sessionId: string, content: string) => request<{ session_id: string }>(`/api/v2/split-sessions/${sessionId}/messages`, { method: "POST", body: JSON.stringify({ content }) }),
  split: (sessionId: string) => request<SplitSession>(`/api/v2/split-sessions/${sessionId}`),
  validateSplit: (sessionId: string) => request<{ valid: boolean; errors: unknown[]; warnings: unknown[] }>(`/api/v2/split-sessions/${sessionId}/validate`, { method: "POST" }),
  commitSplit: (sessionId: string, graphVersion: number, proposalVersion: number) => request<{ graph_version: number; operation_batch: OperationBatchSummary }>(`/api/v2/split-sessions/${sessionId}/commit`, { method: "POST", body: JSON.stringify({ expected_graph_version: graphVersion, proposal_version: proposalVersion }) }),
  discardSplit: (sessionId: string) => request(`/api/v2/split-sessions/${sessionId}/discard`, { method: "POST" }),
  operationBatches: (limit = 50) => request<OperationBatchSummary[]>(`/api/v2/operation-batches?limit=${limit}`),
  undoBatch: (batchId: string, graphVersion: number) => request<{ graph_version: number }>(`/api/v2/operation-batches/${batchId}/undo`, { method: "POST", body: JSON.stringify({ expected_graph_version: graphVersion }) }),
};
