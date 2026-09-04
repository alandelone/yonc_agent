export type WorkType = "UNCLASSIFIED" | "GOAL" | "DELIVERABLE" | "WORK_PACKAGE" | "ACTION";
export type Stage = "CAPTURED" | "PLANNING" | "READY" | "EXECUTION" | "REVIEW" | "CLOSED";
export type Status = "TODO" | "DOING" | "BLOCKED" | "DONE" | "CANCELLED" | "SUPERSEDED";

export interface Forecast {
  node_id: string;
  confidence: "low" | "medium" | "high";
  code?: string;
  remaining_effort_hours: number;
  finish_range: { earliest: string; likely: string; latest: string } | null;
  deadline: string | null;
  gap_days: number | null;
}

export interface GraphNode {
  id: string;
  title: string;
  node_kind: "WORK" | "ARTIFACT" | "RESOURCE" | "AGENT";
  work_type: WorkType;
  stage: Stage;
  status: Status;
  status_reason: string | null;
  parent_id: string | null;
  wbs_level: number | null;
  description: string | null;
  start_cue: string | null;
  inputs: unknown[];
  done_when: string | null;
  required: boolean;
  tags: Record<string, unknown>;
  estimated_effort_minutes: number | null;
  planned_start: string | null;
  planned_end: string | null;
  deadline: string | null;
  placement_source: string | null;
  resource_count: number;
  progress: { completed: number; total: number; ratio: number; weight_minutes: number; completed_weight_minutes: number };
  health: Array<{ code: string; [key: string]: unknown }>;
  forecast: Forecast;
  pressure: { score: number; level: "low" | "medium" | "high"; factors: unknown[] };
}

export interface GraphEdge {
  id: string;
  source_id: string;
  target_id: string;
  relation: string;
  required: boolean;
  metadata: Record<string, unknown>;
}

export interface GraphResponse {
  graph_version: number;
  schema_version: string;
  scope_node_id: string | null;
  nodes: GraphNode[];
  edges: GraphEdge[];
  pace: {
    confidence: string;
    reliable: boolean;
    code?: string;
    weeks: Record<string, number>;
    completion_count: number;
    distinct_weeks: number;
    median_hours: number | null;
  };
  health: { ok: boolean; warning_count: number; warnings: unknown[] };
}

export interface TimelineCell {
  date: string;
  iso_year: number;
  iso_week: number;
  month: string;
  weekday: string;
  allocations: string[];
  overlap_count: number;
  overflow_count: number;
  today: boolean;
  deadline_node_ids: string[];
}

export interface TimelineResponse {
  graph_version: number;
  start: string;
  end: string;
  cells: TimelineCell[];
  placements: Array<{ node_id: string; title: string; start: string; end: string; work_type: WorkType; status: Status }>;
  forecasts: Forecast[];
  warnings: Array<{ code: string; date?: string; count?: number }>;
  pace: GraphResponse["pace"];
}

export interface ProposalNode {
  temporary_id: string;
  title: string;
  work_type: WorkType;
  start_cue: string;
  done_when: string;
  estimated_effort_minutes: number;
  required: boolean;
}

export interface SplitSession {
  id: string;
  parent_node_id: string;
  state: string;
  context_graph_version: number;
  current_proposal_version: number;
  messages: Array<{ id: string; role: "user" | "assistant" | "system"; content: string; created_at: string }>;
  proposal: null | {
    id: string;
    version: number;
    rationale: string;
    nodes: ProposalNode[];
    edges: Array<{ source: string; target: string; relation: string; required: boolean }>;
    actionability_results: Array<{ temporary_id: string; valid: boolean }>;
    warnings: unknown[];
  };
}
