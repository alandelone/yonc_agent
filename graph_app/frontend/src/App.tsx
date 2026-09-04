import ELK from "elkjs/lib/elk.bundled.js";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "./api";
import type { GraphEdge, GraphNode, GraphResponse, SplitSession, TimelineCell, TimelineResponse } from "./types";

type MainView = "canvas" | "timeline";
type TimelineMode = "forecast" | "capacity";
type Position = { x: number; y: number };
type ConnectorSide = "top" | "right" | "bottom" | "left";
type UndoAction = { kind: "local"; undo: () => Promise<void> | void } | { kind: "batch"; batchId: string };

const CARD_W = 164;
const COMPACT_CARD_H = 66;
const CANVAS_LAYOUT_VERSION = 2;
const projectPalette = [
  { hue: 160, saturation: 64 },
  { hue: 199, saturation: 93 },
  { hue: 258, saturation: 90 },
  { hue: 351, saturation: 95 },
  { hue: 38, saturation: 92 },
  { hue: 188, saturation: 85 },
  { hue: 84, saturation: 81 },
];
const wbsLightness = { 1: 52, 2: 42, 3: 32, 4: 22 } as const;
type ColorNode = Pick<GraphNode, "id" | "parent_id" | "wbs_level">;

function longTimelineRange(anchor = new Date()) {
  const start = new Date(anchor.getFullYear(), 0, 1, 12);
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
  const end = new Date(anchor.getFullYear() + 3, 11, 31, 12);
  end.setDate(end.getDate() + ((7 - end.getDay()) % 7));
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

const TIMELINE_RANGE = longTimelineRange();

function paletteIndexFor(value: string) {
  let hash = 0;
  for (const character of value) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return hash % projectPalette.length;
}

export function projectKeyForNode(node: ColorNode, nodesById: ReadonlyMap<string, ColorNode>) {
  let current = node;
  let topmost = node;
  const visited = new Set<string>();
  while (!visited.has(current.id)) {
    visited.add(current.id);
    topmost = current;
    if (current.wbs_level === 1) return current.id;
    if (!current.parent_id) break;
    const parent = nodesById.get(current.parent_id);
    if (!parent) break;
    current = parent;
  }
  return topmost.id;
}

export function wbsColorFor(projectKey: string, level: number | null) {
  const palette = projectPalette[paletteIndexFor(projectKey)];
  const normalizedLevel = level && level >= 1 && level <= 4 ? level as keyof typeof wbsLightness : 3;
  return `hsl(${palette.hue} ${palette.saturation}% ${wbsLightness[normalizedLevel]}%)`;
}

function colorsForNodes(nodes: GraphNode[]) {
  const nodesById = new Map<string, ColorNode>(nodes.map((node) => [node.id, node]));
  return Object.fromEntries(nodes.map((node) => [node.id, wbsColorFor(projectKeyForNode(node, nodesById), node.wbs_level)]));
}

export function canvasEdgeEndpoints(edge: Pick<GraphEdge, "source_id" | "target_id" | "relation">) {
  return edge.relation === "contains"
    ? { sourceId: edge.target_id, targetId: edge.source_id }
    : { sourceId: edge.source_id, targetId: edge.target_id };
}

function addDays(value: string, days: number) {
  const next = new Date(`${value}T12:00:00`);
  next.setDate(next.getDate() + days);
  return next.toISOString().slice(0, 10);
}

function daysBetween(left: string, right: string) {
  return Math.round((new Date(`${right}T12:00:00`).getTime() - new Date(`${left}T12:00:00`).getTime()) / 86_400_000);
}

export function anchoredScrollPosition(scrollLeft: number, scrollTop: number, anchorX: number, anchorY: number, currentZoom: number, nextZoom: number) {
  const worldX = (scrollLeft + anchorX) / currentZoom;
  const worldY = (scrollTop + anchorY) / currentZoom;
  return { left: Math.max(0, worldX * nextZoom - anchorX), top: Math.max(0, worldY * nextZoom - anchorY) };
}

function suggestedSpanDays(node: GraphNode, graph: GraphResponse) {
  const remainingHours = Math.max(0, node.forecast?.remaining_effort_hours ?? (node.estimated_effort_minutes ?? 60) / 60);
  if (remainingHours === 0) return 1;
  if (graph.pace.reliable && graph.pace.median_hours && graph.pace.median_hours > 0) {
    return Math.max(1, Math.ceil(remainingHours / graph.pace.median_hours * 7) + 1);
  }
  return Math.max(1, Math.min(28, Math.ceil(remainingHours / 2)));
}

function nodeSpanDays(node: GraphNode, graph: GraphResponse) {
  if (node.planned_start) return Math.max(1, daysBetween(node.planned_start, node.planned_end ?? node.planned_start) + 1);
  return suggestedSpanDays(node, graph);
}

const SINGLE_DAY_LABEL_WEEKS = 4;

export function scheduledModuleLayout(startDate: string, endDate: string, startWeek: number, endWeek: number, lastWeek: number) {
  const singleDay = startDate === endDate;
  return {
    singleDay,
    displayEndWeek: singleDay ? Math.min(lastWeek, startWeek + SINGLE_DAY_LABEL_WEEKS - 1) : endWeek,
  };
}

function fmtDate(value: string | null | undefined) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric" }).format(new Date(`${value}T12:00:00`));
}

function formatEffort(minutes: number | null | undefined) {
  if (!minutes) return "—";
  return minutes >= 60 ? `${Math.round(minutes / 6) / 10}h` : `${minutes}m`;
}

export function splitCardTitle(value: string) {
  const separator = value.match(/\s+[:：]\s+/);
  if (!separator || separator.index == null) return { title: value, description: null };
  const title = value.slice(0, separator.index).trim();
  const description = value.slice(separator.index + separator[0].length).trim();
  return title && description ? { title, description } : { title: value, description: null };
}

export function nodeCardInfo(node: Pick<GraphNode, "planned_start" | "deadline" | "estimated_effort_minutes" | "resource_count" | "health">) {
  const hasMeta = Boolean(node.planned_start || node.deadline || (node.estimated_effort_minutes ?? 0) > 0);
  const hasSignals = node.resource_count > 0 || (node.health?.length ?? 0) > 0;
  return { hasMeta, hasSignals };
}

export function nodeCardHeight(node: Pick<GraphNode, "planned_start" | "deadline" | "estimated_effort_minutes" | "resource_count" | "health">) {
  const { hasMeta, hasSignals } = nodeCardInfo(node);
  return COMPACT_CARD_H + (hasMeta ? 13 : 0) + (hasSignals ? 15 : 0);
}

export function healthWarningMessage(warning: GraphNode["health"][number], node?: GraphNode) {
  if (warning.code === "ACTIONABILITY_INCOMPLETE") {
    const missing = [!node?.start_cue && "start cue", !node?.done_when && "done-when condition"].filter(Boolean);
    return missing.length ? `Missing ${missing.join(" and ")}.` : "Add a start cue and a clear done-when condition.";
  }
  const messages: Record<string, string> = {
    MULTIPLE_CONTAINS_PARENTS: "This item has more than one structural parent.",
    DEADLINE_CONFLICT: "The planned finish is after this item's deadline.",
    ANCESTOR_DEADLINE_CONFLICT: "The planned finish is after a parent deadline.",
    DEPENDENCY_ORDER_CONFLICT: "The schedule starts before a required dependency is finished.",
    CONTAINS_CYCLE: "This item is part of a containment cycle.",
  };
  return messages[warning.code] ?? `Graph health warning: ${warning.code.replaceAll("_", " ").toLowerCase()}.`;
}

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <header><h2 id="modal-title">{title}</h2><button className="icon-button" onClick={onClose} aria-label="关闭">×</button></header>
        {children}
      </section>
    </div>
  );
}

function useElkPositions(nodes: GraphNode[], edges: GraphEdge[]) {
  const [positions, setPositions] = useState<Record<string, Position>>({});
  useEffect(() => {
    if (!nodes.length) return;
    let cancelled = false;
    const elk = new ELK();
    elk.layout({
      id: "root",
      layoutOptions: {
        "elk.algorithm": "layered",
        "elk.direction": "RIGHT",
        "elk.spacing.nodeNode": "18",
        "elk.layered.spacing.nodeNodeBetweenLayers": "56",
      },
      children: nodes.map((node) => ({ id: node.id, width: CARD_W, height: nodeCardHeight(node) })),
      edges: edges.filter((edge) => edge.relation === "contains").map((edge) => {
        const endpoints = canvasEdgeEndpoints(edge);
        return { id: edge.id, sources: [endpoints.sourceId], targets: [endpoints.targetId] };
      }),
    }).then((layout) => {
      if (cancelled) return;
      const next: Record<string, Position> = {};
      for (const node of layout.children ?? []) next[node.id] = { x: node.x ?? 0, y: node.y ?? 0 };
      setPositions(next);
    }).catch(() => {
      if (!cancelled) setPositions(Object.fromEntries(nodes.map((node, index) => [node.id, { x: (index % 7) * 188, y: Math.floor(index / 7) * 112 }])));
    });
    return () => { cancelled = true; };
  }, [nodes, edges]);
  return positions;
}

function NodeCard({ node, position, height, color, selected, onSelect, onSplit, onPointerDown }: {
  node: GraphNode;
  position: Position;
  height: number;
  color: string;
  selected: boolean;
  onSelect: () => void;
  onSplit: () => void;
  onPointerDown: (event: React.PointerEvent<HTMLElement>) => void;
}) {
  const display = splitCardTitle(node.title);
  const { hasMeta, hasSignals } = nodeCardInfo(node);
  const effort = (node.estimated_effort_minutes ?? 0) > 0 ? formatEffort(node.estimated_effort_minutes) : null;
  return (
    <article
      data-node-id={node.id}
      data-wbs-level={node.wbs_level ?? undefined}
      className={`node-card status-${node.status.toLowerCase()} pressure-${node.pressure?.level ?? "low"} ${selected ? "selected" : ""}`}
      style={{ height, transform: `translate(${position.x}px, ${position.y}px)`, "--node-color": color, "--progress": node.progress?.ratio ?? 0 } as React.CSSProperties}
      onClick={(event) => { event.stopPropagation(); onSelect(); }}
      onPointerDown={onPointerDown}
      tabIndex={0}
      aria-label={`${node.title}, ${node.work_type}, ${node.status}`}
      onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && onSelect()}
    >
      <div className="node-topline"><span>{node.wbs_level ? `L${node.wbs_level}` : "•"} {node.work_type.replace("_", " ")}</span><span className="node-state">{node.status}</span></div>
      <h3 className={display.description ? "with-description" : undefined}><span>{display.title}</span>{display.description && <small className="node-description">{display.description}</small>}</h3>
      {hasMeta && <div className="node-meta">{node.planned_start && <span>{fmtDate(node.planned_start)}</span>}{node.deadline ? <span className={!node.planned_start ? "meta-end" : undefined}>⚑ {fmtDate(node.deadline)}</span> : effort && <span className={!node.planned_start ? "meta-end" : undefined}>{effort}</span>}</div>}
      {hasSignals && <div className="node-signals">{node.resource_count > 0 && <span>{node.resource_count} refs</span>}{(node.health?.length ?? 0) > 0 && <span className="warning signal-end" title="Graph health warning">△ {node.health.length}</span>}</div>}
      <button className="split-plus" onClick={(event) => { event.stopPropagation(); onSplit(); }} aria-label="打开拆分会话">+</button>
    </article>
  );
}

function logarithmicDateOffset(value: string, anchor: string) {
  const delta = daysBetween(anchor, value);
  return Math.sign(delta) * Math.log1p(Math.abs(delta) / 30) * 520;
}

function LogarithmicTimeAxis({ start, end, anchor, todayX, height }: { start: string; end: string; anchor: string; todayX: number; height: number }) {
  const ticks: React.ReactNode[] = [];
  const cursor = new Date(`${start.slice(0, 7)}-01T12:00:00`);
  const last = new Date(`${end}T12:00:00`);
  while (cursor <= last) {
    const value = cursor.toISOString().slice(0, 10);
    const x = todayX + logarithmicDateOffset(value, anchor);
    const month = cursor.toLocaleString("en", { month: "long" });
    ticks.push(<div className="month-tick" key={value} style={{ left: x, height }}><b>{month}</b>{cursor.getMonth() === 0 && <span>{cursor.getFullYear()}</span>}</div>);
    cursor.setMonth(cursor.getMonth() + 1);
  }
  return <div className="time-axis"><div className="axis-title">Logarithmic time</div>{ticks}</div>;
}

function curvedOrthogonalPath(x1: number, y1: number, x2: number, y2: number, axis: "horizontal" | "vertical") {
  const xDirection = x2 >= x1 ? 1 : -1;
  const yDirection = y2 >= y1 ? 1 : -1;
  if (axis === "horizontal") {
    const mid = Math.round((x1 + x2) / 2);
    const radius = Math.min(14, Math.abs(y2 - y1) / 2, Math.abs(x2 - x1) / 4);
    if (radius < 1) return `M ${x1} ${y1} H ${x2}`;
    return `M ${x1} ${y1} H ${mid - xDirection * radius} Q ${mid} ${y1} ${mid} ${y1 + yDirection * radius} V ${y2 - yDirection * radius} Q ${mid} ${y2} ${mid + xDirection * radius} ${y2} H ${x2}`;
  }
  const mid = Math.round((y1 + y2) / 2);
  const radius = Math.min(14, Math.abs(x2 - x1) / 2, Math.abs(y2 - y1) / 4);
  if (radius < 1) return `M ${x1} ${y1} V ${y2}`;
  return `M ${x1} ${y1} V ${mid - yDirection * radius} Q ${x1} ${mid} ${x1 + xDirection * radius} ${mid} H ${x2 - xDirection * radius} Q ${x2} ${mid} ${x2} ${mid + yDirection * radius} V ${y2}`;
}

export function connectorRoute(source: Position, sourceHeight: number, target: Position, targetHeight: number) {
  const sourceCenter = { x: source.x + CARD_W / 2, y: source.y + sourceHeight / 2 };
  const targetCenter = { x: target.x + CARD_W / 2, y: target.y + targetHeight / 2 };
  const dx = targetCenter.x - sourceCenter.x;
  const dy = targetCenter.y - sourceCenter.y;
  const horizontal = Math.abs(dx) / CARD_W >= Math.abs(dy) / ((sourceHeight + targetHeight) / 2);
  let sourceSide: ConnectorSide;
  let targetSide: ConnectorSide;
  let x1: number;
  let y1: number;
  let x2: number;
  let y2: number;

  if (horizontal) {
    const leftToRight = dx >= 0;
    sourceSide = leftToRight ? "right" : "left";
    targetSide = leftToRight ? "left" : "right";
    x1 = source.x + (leftToRight ? CARD_W + 3 : -3);
    y1 = sourceCenter.y;
    x2 = target.x + (leftToRight ? -3 : CARD_W + 3);
    y2 = targetCenter.y;
  } else {
    const topToBottom = dy >= 0;
    sourceSide = topToBottom ? "bottom" : "top";
    targetSide = topToBottom ? "top" : "bottom";
    x1 = sourceCenter.x;
    y1 = source.y + (topToBottom ? sourceHeight + 3 : -3);
    x2 = targetCenter.x;
    y2 = target.y + (topToBottom ? -3 : targetHeight + 3);
  }

  return { sourceSide, targetSide, x1, y1, x2, y2, path: curvedOrthogonalPath(x1, y1, x2, y2, horizontal ? "horizontal" : "vertical") };
}

function CanvasView({ graph, selectedId, onSelect, onClearSelection, onOpenSplit, onRegisterUndo }: {
  graph: GraphResponse;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onClearSelection: () => void;
  onOpenSplit: (node: GraphNode) => void;
  onRegisterUndo: (action: UndoAction) => void;
}) {
  const renderNodes = graph.nodes;
  const allowed = useMemo(() => new Set(renderNodes.map((node) => node.id)), [renderNodes]);
  const renderEdges = useMemo(() => graph.edges.filter((edge) => allowed.has(edge.source_id) && allowed.has(edge.target_id)), [graph.edges, allowed]);
  const nodeColors = useMemo(() => colorsForNodes(renderNodes), [renderNodes]);
  const nodeHeights = useMemo(() => Object.fromEntries(renderNodes.map((node) => [node.id, nodeCardHeight(node)])), [renderNodes]);
  const elkPositions = useElkPositions(renderNodes, renderEdges);
  const canvasRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const minimapViewportRef = useRef<HTMLDivElement>(null);
  const minimapNodeRefs = useRef(new Map<string, HTMLElement>());
  const edgeRefs = useRef(new Map<string, SVGPathElement>());
  const pan = useRef<{ pointerId: number; x: number; y: number; clientX: number; clientY: number; left: number; top: number; moved: boolean } | null>(null);
  const panFrame = useRef<number | null>(null);
  const viewportFrame = useRef<number | null>(null);
  const suppressNodeClick = useRef(false);
  const positionedToday = useRef(false);
  const [zoom, setZoom] = useState(1);
  const zoomTarget = useRef(1);
  const pendingZoomAnchor = useRef<null | { left: number; top: number }>(null);
  const [manualPositions, setManualPositions] = useState<Record<string, Position>>({});
  const nodeDrag = useRef<null | { id: string; pointerId: number; startX: number; startY: number; base: Position; dx: number; dy: number; moved: boolean; zoom: number; element: HTMLElement; positions: Record<string, Position>; edges: GraphEdge[]; width: number; height: number }>(null);
  const nodeDragFrame = useRef<number | null>(null);
  const today = new Date().toISOString().slice(0, 10);
  const scheduledDates = renderNodes.flatMap((node) => [node.planned_start, node.planned_end, node.deadline]).filter(Boolean) as string[];
  const years = scheduledDates.map((value) => Number(value.slice(0, 4)));
  const currentYear = new Date().getFullYear();
  const axisStart = `${Math.min(currentYear - 1, ...(years.length ? years.map((year) => year - 1) : [currentYear - 1]))}-01-01`;
  const axisEnd = `${Math.max(currentYear + 3, ...(years.length ? years.map((year) => year + 1) : [currentYear + 3]))}-12-31`;
  const minOffset = logarithmicDateOffset(axisStart, today);
  const maxOffset = logarithmicDateOffset(axisEnd, today);
  const todayX = 420 - minOffset;
  const persistPositions = useCallback((next: Record<string, Position>) => {
    const encoded: Record<string, number> = { __layout_direction_version: CANVAS_LAYOUT_VERSION };
    for (const [id, position] of Object.entries(next)) { encoded[`${id}:x`] = position.x; encoded[`${id}:y`] = position.y; }
    return api.saveViewState("canvas", { vertical_layout: encoded });
  }, []);

  useEffect(() => {
    let cancelled = false;
    api.viewState("canvas").then((state) => {
      if (cancelled) return;
      const stored = (state.vertical_layout ?? {}) as Record<string, unknown>;
      const next: Record<string, Position> = {};
      for (const node of renderNodes) {
        const x = stored[`${node.id}:x`];
        const y = stored[`${node.id}:y`];
        if (typeof x === "number" && typeof y === "number") next[node.id] = { x, y };
      }
      if (stored.__layout_direction_version !== CANVAS_LAYOUT_VERSION) {
        const xValues = Object.values(next).map((position) => position.x);
        if (xValues.length > 1) {
          const mirrorAxis = Math.min(...xValues) + Math.max(...xValues);
          for (const position of Object.values(next)) position.x = mirrorAxis - position.x;
        }
        void persistPositions(next).catch(() => undefined);
      }
      setManualPositions(next);
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [persistPositions, renderNodes]);

  const positions = useMemo(() => Object.fromEntries(renderNodes.map((node, index) => {
    const scheduled = node.planned_start ?? node.deadline;
    const elk = elkPositions[node.id] ?? { x: (index % 7) * 188, y: Math.floor(index / 7) * 112 };
    const derived = { x: scheduled ? todayX + logarithmicDateOffset(scheduled, today) : 90 + elk.x, y: 82 + elk.y };
    return [node.id, manualPositions[node.id] ?? derived];
  })), [renderNodes, elkPositions, manualPositions, today, todayX]);

  const edgePaths = renderEdges.map((edge) => {
    const endpoints = canvasEdgeEndpoints(edge);
    const source = positions[endpoints.sourceId];
    const target = positions[endpoints.targetId];
    if (!source || !target) return null;
    const route = connectorRoute(source, nodeHeights[endpoints.sourceId], target, nodeHeights[endpoints.targetId]);
    return <path ref={(element) => { if (element) edgeRefs.current.set(edge.id, element); else edgeRefs.current.delete(edge.id); }} key={edge.id} data-source={endpoints.sourceId} data-target={endpoints.targetId} data-source-side={route.sourceSide} data-target-side={route.targetSide} className={`edge edge-${edge.relation}`} d={route.path} markerEnd="url(#arrow)" />;
  });

  const height = Math.max(760, ...Object.entries(positions).map(([id, item]) => item.y + (nodeHeights[id] ?? COMPACT_CARD_H) + 120));
  const width = Math.max(1800, todayX + maxOffset + 520, ...Object.values(positions).map((item) => item.x + CARD_W + 180));
  const paintNodeDrag = useCallback(() => {
    nodeDragFrame.current = null;
    const current = nodeDrag.current;
    if (!current) return;
    const position = { x: current.base.x + current.dx, y: current.base.y + current.dy };
    current.element.style.transform = `translate(${position.x}px, ${position.y}px)`;
    for (const edge of current.edges) {
      const endpoints = canvasEdgeEndpoints(edge);
      const source = endpoints.sourceId === current.id ? position : current.positions[endpoints.sourceId];
      const target = endpoints.targetId === current.id ? position : current.positions[endpoints.targetId];
      const edgeElement = edgeRefs.current.get(edge.id);
      if (!source || !target || !edgeElement) continue;
      const route = connectorRoute(source, nodeHeights[endpoints.sourceId] ?? COMPACT_CARD_H, target, nodeHeights[endpoints.targetId] ?? COMPACT_CARD_H);
      edgeElement.setAttribute("d", route.path);
      edgeElement.dataset.sourceSide = route.sourceSide;
      edgeElement.dataset.targetSide = route.targetSide;
    }
    const minimapNode = minimapNodeRefs.current.get(current.id);
    if (minimapNode) {
      minimapNode.style.left = `${Math.min(98, position.x / current.width * 100)}%`;
      minimapNode.style.top = `${Math.min(96, position.y / current.height * 100)}%`;
    }
  }, [nodeHeights]);
  useEffect(() => {
    const move = (event: PointerEvent) => {
      const current = nodeDrag.current;
      if (!current || event.pointerId !== current.pointerId) return;
      current.dx = (event.clientX - current.startX) / current.zoom;
      current.dy = (event.clientY - current.startY) / current.zoom;
      current.moved ||= Math.abs(event.clientX - current.startX) + Math.abs(event.clientY - current.startY) > 4;
      if (nodeDragFrame.current == null) nodeDragFrame.current = window.requestAnimationFrame(paintNodeDrag);
    };
    const finish = (event: PointerEvent) => {
      const current = nodeDrag.current;
      if (!current || event.pointerId !== current.pointerId) return;
      if (nodeDragFrame.current != null) {
        window.cancelAnimationFrame(nodeDragFrame.current);
        nodeDragFrame.current = null;
      }
      paintNodeDrag();
      nodeDrag.current = null;
      current.element.classList.remove("dragging");
      stageRef.current?.classList.remove("node-dragging");
      if (current.element.hasPointerCapture(current.pointerId)) current.element.releasePointerCapture(current.pointerId);
      if (!current.moved) {
        current.element.style.transform = `translate(${current.base.x}px, ${current.base.y}px)`;
        return;
      }
      suppressNodeClick.current = true;
      window.setTimeout(() => { suppressNodeClick.current = false; }, 80);
      setManualPositions((previous) => {
        const next = { ...previous, [current.id]: { x: current.base.x + current.dx, y: current.base.y + current.dy } };
        const initialSave = persistPositions(next);
        onRegisterUndo({ kind: "local", undo: async () => { await initialSave.catch(() => undefined); setManualPositions(previous); await persistPositions(previous); } });
        return next;
      });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", finish);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
      if (nodeDragFrame.current != null) window.cancelAnimationFrame(nodeDragFrame.current);
    };
  }, [onRegisterUndo, paintNodeDrag, persistPositions]);
  const updateViewport = () => {
    if (viewportFrame.current != null) return;
    viewportFrame.current = window.requestAnimationFrame(() => {
      viewportFrame.current = null;
      const canvas = canvasRef.current;
      const viewport = minimapViewportRef.current;
      if (!canvas || !viewport) return;
      viewport.style.left = `${canvas.scrollLeft / zoom / width * 100}%`;
      viewport.style.top = `${canvas.scrollTop / zoom / height * 100}%`;
      viewport.style.width = `${Math.min(100, canvas.clientWidth / zoom / width * 100)}%`;
      viewport.style.height = `${Math.min(100, canvas.clientHeight / zoom / height * 100)}%`;
    });
  };
  useEffect(() => () => {
    if (panFrame.current != null) window.cancelAnimationFrame(panFrame.current);
    if (viewportFrame.current != null) window.cancelAnimationFrame(viewportFrame.current);
  }, []);
  useEffect(() => {
    if (positionedToday.current || !canvasRef.current) return;
    canvasRef.current.scrollTo({ left: Math.max(0, todayX * zoom - canvasRef.current.clientWidth / 2), top: 0 });
    positionedToday.current = true;
    updateViewport();
  }, [todayX, zoom]);
  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const pending = pendingZoomAnchor.current;
    if (pending) {
      canvas.scrollTo(pending);
      pendingZoomAnchor.current = null;
    }
    zoomTarget.current = zoom;
    updateViewport();
  }, [zoom, width, height]);
  const horizontalFitZoom = () => {
    const canvas = canvasRef.current;
    if (!canvas) return .01;
    return Math.max(.01, Math.min(1, (canvas.clientWidth - 28) / width));
  };
  const setZoomAtPoint = (nextValue: number, clientX?: number, clientY?: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const next = Math.max(horizontalFitZoom(), Math.min(1.6, nextValue));
    const rect = canvas.getBoundingClientRect();
    const pointerInsideCanvas = clientX != null && clientY != null && clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom;
    const anchorX = pointerInsideCanvas ? clientX! - rect.left : canvas.clientWidth / 2;
    const anchorY = pointerInsideCanvas ? clientY! - rect.top : canvas.clientHeight / 2;
    if (Math.abs(next - zoom) < .0001) { pendingZoomAnchor.current = null; zoomTarget.current = next; return; }
    pendingZoomAnchor.current = anchoredScrollPosition(canvas.scrollLeft, canvas.scrollTop, anchorX, anchorY, zoom, next);
    zoomTarget.current = next;
    setZoom(next);
  };
  const setZoomAroundCenter = (nextValue: number) => setZoomAtPoint(nextValue);
  const fitAll = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const next = horizontalFitZoom();
    const worldCenterY = (canvas.scrollTop + canvas.clientHeight / 2) / zoom;
    pendingZoomAnchor.current = null;
    setZoom(next);
    zoomTarget.current = next;
    window.requestAnimationFrame(() => { canvas.scrollTo({ left: 0, top: Math.max(0, worldCenterY * next - canvas.clientHeight / 2), behavior: "smooth" }); updateViewport(); });
  };
  useEffect(() => {
    const zoomWithMouse = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      const factor = Math.exp(-event.deltaY * .0015);
      setZoomAtPoint(zoomTarget.current * factor, event.clientX, event.clientY);
    };
    window.addEventListener("wheel", zoomWithMouse, { passive: false });
    return () => window.removeEventListener("wheel", zoomWithMouse);
  }, [zoom, width]);
  const navigate = (direction: -1 | 0 | 1) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (direction === 0) canvas.scrollTo({ left: Math.max(0, todayX * zoom - canvas.clientWidth / 2), behavior: "smooth" });
    else canvas.scrollBy({ left: direction * Math.max(420, canvas.clientWidth * .55), behavior: "smooth" });
  };
  const moveCanvas = (event: React.PointerEvent<HTMLDivElement>) => {
    const current = pan.current;
    if (!current || event.pointerId !== current.pointerId) return;
    current.clientX = event.clientX;
    current.clientY = event.clientY;
    current.moved ||= Math.abs(event.clientX - current.x) + Math.abs(event.clientY - current.y) > 4;
    if (panFrame.current != null) return;
    const canvas = event.currentTarget;
    panFrame.current = window.requestAnimationFrame(() => {
      panFrame.current = null;
      const latest = pan.current;
      if (!latest) return;
      canvas.scrollLeft = latest.left - (latest.clientX - latest.x);
      canvas.scrollTop = latest.top - (latest.clientY - latest.y);
    });
  };
  const finishCanvasMove = (event: React.PointerEvent<HTMLDivElement>, cancelled = false) => {
    const current = pan.current;
    if (!current || event.pointerId !== current.pointerId) return;
    if (panFrame.current != null) {
      window.cancelAnimationFrame(panFrame.current);
      panFrame.current = null;
      event.currentTarget.scrollLeft = current.left - (current.clientX - current.x);
      event.currentTarget.scrollTop = current.top - (current.clientY - current.y);
    }
    pan.current = null;
    event.currentTarget.classList.remove("panning");
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (!cancelled && !current.moved) onClearSelection();
  };
  return (
    <div className="canvas-view">
      <div ref={canvasRef} className="canvas-scroll" onScroll={updateViewport} onPointerDown={(event) => { if (event.button !== 0 || (event.target as HTMLElement).closest(".node-card")) return; pan.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, clientX: event.clientX, clientY: event.clientY, left: event.currentTarget.scrollLeft, top: event.currentTarget.scrollTop, moved: false }; event.currentTarget.classList.add("panning"); event.currentTarget.setPointerCapture(event.pointerId); }} onPointerMove={moveCanvas} onPointerUp={(event) => finishCanvasMove(event)} onPointerCancel={(event) => finishCanvasMove(event, true)}>
        <div className="canvas-zoom-space" style={{ width: width * zoom, height: height * zoom }}>
          <LogarithmicTimeAxis start={axisStart} end={axisEnd} anchor={today} todayX={todayX * zoom} height={height * zoom} />
          <div ref={stageRef} className="canvas-stage" style={{ width, height, transform: `scale(${zoom})` }}>
            <div className="today-line" style={{ left: todayX, height }} />
            <svg className="edge-layer" width={width} height={height} aria-hidden="true"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" /></marker></defs>{edgePaths}</svg>
            {renderNodes.map((node) => <NodeCard key={node.id} node={node} position={positions[node.id]} height={nodeHeights[node.id]} color={nodeColors[node.id]} selected={selectedId === node.id} onSelect={() => { if (suppressNodeClick.current) { suppressNodeClick.current = false; return; } onSelect(node.id); }} onSplit={() => onOpenSplit(node)} onPointerDown={(event) => { if (event.button !== 0 || (event.target as HTMLElement).closest("button")) return; event.stopPropagation(); const element = event.currentTarget; const base = positions[node.id]; nodeDrag.current = { id: node.id, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, base, dx: 0, dy: 0, moved: false, zoom, element, positions, edges: renderEdges.filter((edge) => edge.source_id === node.id || edge.target_id === node.id), width, height }; element.classList.add("dragging"); stageRef.current?.classList.add("node-dragging"); element.setPointerCapture(event.pointerId); }} />)}
          </div>
        </div>
      </div>
      <div className="canvas-overlay-tools">
        <div className="canvas-zoom-controls"><button onClick={() => setZoomAroundCenter(zoomTarget.current - .1)} aria-label="Zoom out">−</button><button onClick={() => setZoomAroundCenter(.25)}>25%</button><button onClick={() => setZoomAroundCenter(.5)}>50%</button><button onClick={fitAll}>Fit</button><button onClick={() => setZoomAroundCenter(zoomTarget.current + .1)} aria-label="Zoom in">+</button><span>{Math.round(zoom * 100)}%</span></div>
        <div className="canvas-controls"><button onClick={() => navigate(-1)}>← Quarter</button><button onClick={() => navigate(0)}>Today</button><button onClick={() => navigate(1)}>Quarter →</button></div>
      </div>
      <div className="minimap" aria-label="Canvas minimap" onClick={(event) => { const canvas = canvasRef.current; if (!canvas) return; const rect = event.currentTarget.getBoundingClientRect(); const targetX = (event.clientX - rect.left) / rect.width * width; const targetY = (event.clientY - rect.top) / rect.height * height; canvas.scrollTo({ left: Math.max(0, targetX * zoom - canvas.clientWidth / 2), top: Math.max(0, targetY * zoom - canvas.clientHeight / 2), behavior: "smooth" }); }}>{renderNodes.map((node) => <i ref={(element) => { if (element) minimapNodeRefs.current.set(node.id, element); else minimapNodeRefs.current.delete(node.id); }} key={node.id} style={{ left: `${Math.min(98, positions[node.id].x / width * 100)}%`, top: `${Math.min(96, positions[node.id].y / height * 100)}%`, background: nodeColors[node.id] }} />)}<div ref={minimapViewportRef} className="minimap-viewport" /></div>
    </div>
  );
}

function NodeInspector({ node, color, graphVersion, onClose, onRefresh, onOpenSplit, onError, onRegisterUndo }: {
  node: GraphNode | null;
  color: string;
  graphVersion: number;
  onClose: () => void;
  onRefresh: () => Promise<void>;
  onOpenSplit: (node: GraphNode) => void;
  onError: (error: unknown) => void;
  onRegisterUndo: (action: UndoAction) => void;
}) {
  const [dialog, setDialog] = useState<"done" | "deadline" | null>(null);
  const [deadline, setDeadline] = useState("");
  if (!node) return null;
  const performDone = async () => {
    try { const result = await api.transition(node.id, "done", graphVersion); onRegisterUndo({ kind: "batch", batchId: result.operation_batch_id }); setDialog(null); await onRefresh(); } catch (error) { onError(error); }
  };
  const saveDeadline = async () => {
    try { const result = await api.patchNode(node.id, { deadline: deadline || null }, graphVersion); onRegisterUndo({ kind: "batch", batchId: result.operation_batch_id }); setDialog(null); await onRefresh(); } catch (error) { onError(error); }
  };
  return (
    <aside className="inspector floating-inspector">
      <button className="inspector-close" onClick={onClose} aria-label="关闭详情">×</button>
      <div className="inspector-heading"><span className="status-dot" style={{ background: color }} /><div><span className="eyebrow">{node.work_type.replace("_", " ")} · {node.stage}</span><h2>{node.title}</h2></div></div>
      <div className="detail-grid"><span>Status</span><b>{node.status}</b><span>Progress</span><b>{Math.round((node.progress?.ratio ?? 0) * 100)}%</b><span>Estimated Effort</span><b>{formatEffort(node.estimated_effort_minutes)}</b><span>Planned Span</span><b>{node.planned_start ? `${fmtDate(node.planned_start)} – ${fmtDate(node.planned_end ?? node.planned_start)}` : "Unscheduled"}</b><span>Deadline</span><b>{fmtDate(node.deadline)}</b><span>Pressure</span><b className={`pressure-text ${node.pressure?.level}`}>{node.pressure?.level ?? "low"}</b></div>
      <div className="meter"><i style={{ width: `${Math.round((node.progress?.ratio ?? 0) * 100)}%` }} /></div>
      {node.health?.length > 0 && <section className="health-warnings" aria-label="Warnings"><div className="section-heading"><h3>Warnings</h3><span>{node.health.length}</span></div><ul>{node.health.map((warning, index) => <li key={`${warning.code}-${index}`}><span aria-hidden="true">△</span><p>{healthWarningMessage(warning, node)}</p></li>)}</ul></section>}
      <section><h3>Description</h3><p>{node.description || "No description yet."}</p></section>
      <section><h3>Execution definition</h3><p><small>Start</small>{node.start_cue || "—"}</p><p><small>Done when</small>{node.done_when || "—"}</p></section>
      <section><h3>Forecast</h3>{node.forecast?.finish_range ? <p>{fmtDate(node.forecast.finish_range.earliest)} – {fmtDate(node.forecast.finish_range.latest)} <small>{node.forecast.confidence} confidence</small></p> : <p>Insufficient completed history for a finish range.</p>}</section>
      <section><h3>References</h3><p>{node.resource_count} linked resources</p></section>
      <div className="inspector-actions"><button className="primary" onClick={() => onOpenSplit(node)}>Open Split</button><button onClick={() => { setDeadline(node.deadline ?? ""); setDialog("deadline"); }}>Edit Deadline</button>{node.status !== "DONE" && <button onClick={() => setDialog("done")}>Mark Done</button>}</div>
      {dialog === "done" && <Modal title="确认完成" onClose={() => setDialog(null)}><p>确认标记为完成？完成状态只能由你确认。</p><div className="modal-actions"><button onClick={() => setDialog(null)}>取消</button><button className="primary" onClick={performDone}>标记完成</button></div></Modal>}
      {dialog === "deadline" && <Modal title="修改截止日期" onClose={() => setDialog(null)}><p>修改截止日期会重新计算预测和时间压力。</p><label className="field">截止日期<input type="date" value={deadline} onChange={(event) => setDeadline(event.target.value)} /></label><div className="modal-actions"><button onClick={() => setDialog(null)}>取消</button><button className="primary" onClick={saveDeadline}>确认修改</button></div></Modal>}
    </aside>
  );
}

function TimelineGrid({ timeline, graph, selectedId, calendarRef, onSelect, onRefresh, onError, onRegisterUndo }: {
  timeline: TimelineResponse;
  graph: GraphResponse;
  selectedId: string | null;
  calendarRef: React.RefObject<HTMLElement | null>;
  onSelect: (id: string) => void;
  onRefresh: () => Promise<void>;
  onError: (error: unknown) => void;
  onRegisterUndo: (action: UndoAction) => void;
}) {
  const weeks = useMemo(() => Array.from(new Set(timeline.cells.map((cell) => `${cell.iso_year}-${cell.iso_week}`))), [timeline.cells]);
  const weekIndex = useMemo(() => Object.fromEntries(weeks.map((week, index) => [week, index])), [weeks]);
  const byId = useMemo(() => Object.fromEntries(graph.nodes.map((node) => [node.id, node])), [graph.nodes]);
  const nodeColors = useMemo(() => colorsForNodes(graph.nodes), [graph.nodes]);
  const unscheduled = graph.nodes.filter((node) => !node.planned_start && ["GOAL", "DELIVERABLE", "WORK_PACKAGE", "ACTION", "UNCLASSIFIED"].includes(node.work_type));
  const scheduledModules = graph.nodes.filter((node) => node.planned_start && ["GOAL", "DELIVERABLE", "WORK_PACKAGE", "ACTION", "UNCLASSIFIED"].includes(node.work_type)).sort((a, b) => (a.planned_start ?? "").localeCompare(b.planned_start ?? ""));
  const [rangeNode, setRangeNode] = useState<GraphNode | null>(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [draggedNodeId, setDraggedNodeId] = useState<string | null>(null);
  const [dragAnchorOffset, setDragAnchorOffset] = useState(0);
  const [dropPreviewDate, setDropPreviewDate] = useState<string | null>(null);
  const [pendingPlacement, setPendingPlacement] = useState<{ nodeId: string; start: string; end: string } | null>(null);
  const positionedOnce = useRef(false);
  const cellSize = 44;
  const previewNodeId = draggedNodeId ?? pendingPlacement?.nodeId ?? null;
  const previewNode = previewNodeId ? byId[previewNodeId] : null;
  const dropPreviewColor = previewNode ? nodeColors[previewNode.id] : "#8b5cf6";
  const previewStart = pendingPlacement?.start ?? (draggedNodeId && dropPreviewDate ? addDays(dropPreviewDate, -dragAnchorOffset) : null);
  const previewEnd = pendingPlacement?.end ?? (previewStart && previewNode ? addDays(previewStart, nodeSpanDays(previewNode, graph) - 1) : null);
  const stripModules = scheduledModules.map((node) => ({ node, pending: false }));
  if (pendingPlacement && !stripModules.some(({ node }) => node.id === pendingPlacement.nodeId) && byId[pendingPlacement.nodeId]) stripModules.push({ node: byId[pendingPlacement.nodeId], pending: true });
  const scheduledLaneItems = (() => {
    const firstDate = timeline.cells[0]?.date;
    const lastDate = timeline.cells[timeline.cells.length - 1]?.date;
    if (!firstDate || !lastDate) return [];
    const intervals = stripModules.flatMap(({ node, pending }) => {
      const startDate = pending && pendingPlacement ? pendingPlacement.start : node.planned_start;
      const endDate = pending && pendingPlacement ? pendingPlacement.end : node.planned_end ?? node.planned_start;
      if (!startDate || !endDate || endDate < firstDate || startDate > lastDate) return [];
      const visibleStart = startDate < firstDate ? firstDate : startDate;
      const visibleEnd = endDate > lastDate ? lastDate : endDate;
      const startCell = timeline.cells.find((cell) => cell.date === visibleStart);
      const endCell = timeline.cells.find((cell) => cell.date === visibleEnd);
      if (!startCell || !endCell) return [];
      const startWeek = weekIndex[`${startCell.iso_year}-${startCell.iso_week}`];
      const endWeek = weekIndex[`${endCell.iso_year}-${endCell.iso_week}`];
      return [{ node, pending, startDate, endDate, startWeek, endWeek, ...scheduledModuleLayout(startDate, endDate, startWeek, endWeek, weeks.length - 1) }];
    }).sort((a, b) => a.startWeek - b.startWeek || a.endWeek - b.endWeek || a.node.title.localeCompare(b.node.title));
    const laneEnds: number[] = [];
    return intervals.map((item) => {
      let lane = laneEnds.findIndex((displayEndWeek) => item.startWeek > displayEndWeek);
      if (lane < 0) lane = laneEnds.length;
      laneEnds[lane] = item.displayEndWeek;
      return { ...item, lane };
    });
  })();
  const scheduledLaneCount = Math.max(1, ...scheduledLaneItems.map((item) => item.lane + 1));
  const beginModuleDrag = (event: React.DragEvent, nodeId: string, anchorOffset = 0) => {
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/yonc-node", nodeId);
    // The hovered calendar cell is the allocation preview, so suppress the
    // browser's default card-sized drag image.
    const transparent = document.createElement("canvas");
    transparent.width = 1;
    transparent.height = 1;
    Object.assign(transparent.style, { position: "fixed", left: "0", top: "0", opacity: "0", pointerEvents: "none" });
    document.body.appendChild(transparent);
    event.dataTransfer.setDragImage(transparent, 0, 0);
    window.requestAnimationFrame(() => transparent.remove());
    setDraggedNodeId(nodeId);
    setDragAnchorOffset(anchorOffset);
    setDropPreviewDate(null);
  };
  const clearModuleDrag = () => {
    setDraggedNodeId(null);
    setDragAnchorOffset(0);
    setDropPreviewDate(null);
  };
  useEffect(() => {
    if (positionedOnce.current || !calendarRef.current) return;
    const todayCell = calendarRef.current.querySelector<HTMLElement>(`[data-date="${new Date().toISOString().slice(0, 10)}"]`);
    if (!todayCell) return;
    calendarRef.current.scrollLeft = Math.max(0, todayCell.offsetLeft - calendarRef.current.clientWidth / 2 + todayCell.clientWidth / 2);
    positionedOnce.current = true;
  }, [calendarRef, timeline.cells]);
  const drop = async (event: React.DragEvent, cell: TimelineCell) => {
    event.preventDefault();
    const nodeId = event.dataTransfer.getData("text/yonc-node") || draggedNodeId;
    if (!nodeId) return;
    const node = byId[nodeId];
    const newStart = addDays(cell.date, -dragAnchorOffset);
    const scheduledMove = Boolean(node?.planned_start);
    const suggestedEnd = node ? addDays(newStart, nodeSpanDays(node, graph) - 1) : newStart;
    clearModuleDrag();
    setPendingPlacement({ nodeId, start: newStart, end: suggestedEnd });
    try {
      const scheduled = await api.schedule(nodeId, newStart, scheduledMove ? suggestedEnd : null, graph.graph_version, !scheduledMove);
      if (scheduled.operation_batch_id) onRegisterUndo({ kind: "batch", batchId: scheduled.operation_batch_id });
      setPendingPlacement({ nodeId, start: scheduled.planned_start, end: scheduled.planned_end });
      await onRefresh();
    } catch (error) { onError(error); } finally { setPendingPlacement(null); }
  };
  const openRange = (node: GraphNode) => { setRangeNode(node); setStart(node.planned_start ?? ""); setEnd(node.planned_end ?? node.planned_start ?? ""); onSelect(node.id); };
  const saveRange = async () => {
    if (!rangeNode || !start || !end) return;
    try { const scheduled = await api.schedule(rangeNode.id, start, end, graph.graph_version); if (scheduled.operation_batch_id) onRegisterUndo({ kind: "batch", batchId: scheduled.operation_batch_id }); setRangeNode(null); await onRefresh(); } catch (error) { onError(error); }
  };
  return (
    <div className="timeline-layout">
      <aside className="module-pool"><span className="eyebrow">Unscheduled modules</span><h2>Module pool</h2>{unscheduled.length ? unscheduled.map((node) => <article key={node.id} className={draggedNodeId === node.id || pendingPlacement?.nodeId === node.id ? "dragging" : ""} draggable aria-label={`Drag ${node.title} to a date`} onDragStart={(event) => beginModuleDrag(event, node.id)} onDragEnd={clearModuleDrag} onClick={() => onSelect(node.id)}><i style={{ background: nodeColors[node.id] }} /><div><b>{node.title}</b><small>{node.work_type.replace("_", " ")} · {formatEffort(node.estimated_effort_minutes)}</small></div><span>⋮</span></article>) : <p className="quiet">Everything in this project file has a start date.</p>}</aside>
      <section ref={calendarRef} className={`calendar-wrap ${draggedNodeId ? "accepting-drop" : ""}`} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropPreviewDate(null); }}>
        <div className="calendar-grid" style={{ gridTemplateColumns: `56px repeat(${weeks.length}, ${cellSize}px)`, "--cell-size": `${cellSize}px`, "--drop-color": dropPreviewColor } as React.CSSProperties}>
          <div className="corner-label" />
          {weeks.map((week, index) => {
            const first = timeline.cells.find((cell) => `${cell.iso_year}-${cell.iso_week}` === week)!;
            const previousWeek = index > 0 ? timeline.cells.find((cell) => `${cell.iso_year}-${cell.iso_week}` === weeks[index - 1]) : undefined;
            const showYear = !previousWeek || previousWeek.iso_year !== first.iso_year;
            const showMonth = showYear || !previousWeek || previousWeek.month !== first.month;
            return <div key={week} className="week-label" style={{ gridColumn: index + 2 }}>{showYear && <em>{first.iso_year}</em>}{showMonth && <b>{first.month}</b>}<span>W{first.iso_week}</span></div>;
          })}
          {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day, index) => <div key={day} className="day-label" style={{ gridRow: index + 2 }}>{day}</div>)}
          {timeline.cells.map((cell) => {
            const key = `${cell.iso_year}-${cell.iso_week}`;
            const row = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].indexOf(cell.weekday) + 2;
            const colors = cell.allocations.slice(0, 2).map((id) => nodeColors[id] ?? "#8b5cf6");
            const background = !colors.length ? undefined : colors.length === 1 ? colors[0] : `linear-gradient(135deg, ${colors[0]} 0 50%, ${colors[1]} 50%)`;
            const selected = selectedId ? cell.allocations.includes(selectedId) : false;
            const dragAllocationId = selectedId && cell.allocations.includes(selectedId) ? selectedId : cell.allocations[0] ?? null;
            const draggingSource = Boolean(draggedNodeId && cell.allocations.includes(draggedNodeId));
            const dropPreview = Boolean(previewStart && previewEnd && cell.date >= previewStart && cell.date <= previewEnd);
            const previewRangeStart = dropPreview && cell.date === previewStart;
            return <button key={cell.date} data-date={cell.date} className={`day-cell ${cell.today ? "today" : ""} ${cell.deadline_node_ids.length ? "deadline" : ""} ${cell.overlap_count > 2 ? "overload" : ""} ${selected ? "range-selected" : ""} ${draggingSource ? "drag-source" : ""} ${dropPreview ? "drop-preview" : ""} ${previewRangeStart ? "drop-preview-start" : ""}`} style={{ gridColumn: weekIndex[key] + 2, gridRow: row, background }} draggable={Boolean(dragAllocationId)} onDragStart={(event) => { if (dragAllocationId) { const node = byId[dragAllocationId]; beginModuleDrag(event, dragAllocationId, node?.planned_start ? daysBetween(node.planned_start, cell.date) : 0); } }} onDragEnd={clearModuleDrag} onDragEnter={(event) => { event.preventDefault(); if (draggedNodeId) setDropPreviewDate(cell.date); }} onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "move"; if (draggedNodeId && dropPreviewDate !== cell.date) setDropPreviewDate(cell.date); }} onDrop={(event) => drop(event, cell)} onClick={() => dragAllocationId && openRange(byId[dragAllocationId])} aria-label={`${cell.date}, ${cell.overlap_count} planned allocation${cell.overlap_count === 1 ? "" : "s"}${dragAllocationId ? ", draggable scheduled range" : ""}${dropPreview ? `, previewing ${previewNode?.title ?? "module"} from ${previewStart} to ${previewEnd}` : ""}`}><span>{new Date(`${cell.date}T12:00:00`).getDate()}</span>{cell.overflow_count > 0 && <b>+{cell.overflow_count}</b>}{cell.deadline_node_ids.length > 0 && <i>⚑</i>}</button>;
          })}
        </div>
        <footer className="scheduled-module-lane" aria-label="Scheduled modules by week" style={{ gridTemplateColumns: `56px repeat(${weeks.length}, ${cellSize}px)`, gridTemplateRows: `repeat(${scheduledLaneCount}, 22px)` }}><span style={{ gridColumn: 1, gridRow: `1 / ${scheduledLaneCount + 1}` }}>Scheduled</span>{scheduledLaneItems.map(({ node, pending, startDate, endDate, startWeek, displayEndWeek, singleDay, lane }) => <button key={node.id} className={`${pending ? "pending " : ""}${singleDay ? "single-day" : "range"}`} style={{ "--module-color": nodeColors[node.id], gridColumn: `${startWeek + 2} / ${displayEndWeek + 3}`, gridRow: lane + 1 } as React.CSSProperties} draggable={!pending} onDragStart={(event) => !pending && beginModuleDrag(event, node.id)} onDragEnd={clearModuleDrag} onClick={() => !pending && openRange(node)} title={`${node.title} — ${singleDay ? startDate : `${startDate} to ${endDate}`}`} aria-label={`${node.title}, scheduled ${singleDay ? `on ${startDate}` : `from ${startDate} to ${endDate}`}`}><span className="scheduled-module-copy">{singleDay && <small>{fmtDate(startDate)}</small>}<b>{node.title}</b></span></button>)}</footer>
      </section>
      {rangeNode && <aside className="range-inspector floating-range"><button className="inspector-close" onClick={() => setRangeNode(null)} aria-label="关闭范围详情">×</button><span className="eyebrow">Selected range</span><h2>{rangeNode.title}</h2><label className="field">Start<input type="date" value={start} onChange={(event) => setStart(event.target.value)} /></label><label className="field">End<input type="date" value={end} onChange={(event) => setEnd(event.target.value)} /></label><p className="quiet">Moving or resizing changes planned dates, never estimated effort.</p><button className="primary" onClick={saveRange}>Apply Range</button><hr /><span className="eyebrow">Weekly capacity</span><p>{timeline.warnings.length ? `${timeline.warnings.length} overlap warning${timeline.warnings.length === 1 ? "" : "s"}` : "No overloaded cells in this range."}</p></aside>}
    </div>
  );
}

function ForecastView({ graph }: { graph: GraphResponse }) {
  const projects = graph.nodes.filter((node) => ["GOAL", "DELIVERABLE"].includes(node.work_type)).slice(0, 12);
  const nodeColors = useMemo(() => colorsForNodes(graph.nodes), [graph.nodes]);
  const max = Math.max(1, ...Object.values(graph.pace.weeks));
  return (
    <div className="forecast-view">
      <section className="forecast-hero"><span className="eyebrow">Observed delivery pace</span><h2>{graph.pace.reliable ? `${graph.pace.median_hours?.toFixed(1)}h / week` : "Building a baseline"}</h2><p>{graph.pace.reliable ? `Based on ${graph.pace.completion_count} valid Done transitions across the last eight completed ISO weeks.` : "At least three completed Actions across two separate weeks are needed before showing a finish date."}</p><div className="pace-bars">{Object.entries(graph.pace.weeks).map(([week, value]) => <div key={week}><i style={{ height: `${Math.max(4, value / max * 100)}%` }} /><span>{week.slice(5)}</span></div>)}</div></section>
      <section className="forecast-list"><span className="eyebrow">Project forecasts</span>{projects.map((node) => <article key={node.id}><div><i style={{ background: nodeColors[node.id] }} /><h3>{node.title}</h3><span>{node.work_type}</span></div><dl><div><dt>Remaining</dt><dd>{node.forecast?.remaining_effort_hours?.toFixed(1) ?? "—"}h</dd></div><div><dt>Likely finish</dt><dd>{fmtDate(node.forecast?.finish_range?.likely)}</dd></div><div><dt>Deadline</dt><dd>{fmtDate(node.deadline)}</dd></div><div><dt>Gap</dt><dd>{node.forecast?.gap_days == null ? "—" : `${node.forecast.gap_days}d`}</dd></div></dl></article>)}</section>
    </div>
  );
}

function TimelineView({ timeline, graph, selectedId, mode, onMode, onSelect, onRefresh, onError, onRegisterUndo }: {
  timeline: TimelineResponse;
  graph: GraphResponse;
  selectedId: string | null;
  mode: TimelineMode;
  onMode: (mode: TimelineMode) => void;
  onSelect: (id: string) => void;
  onRefresh: () => Promise<void>;
  onError: (error: unknown) => void;
  onRegisterUndo: (action: UndoAction) => void;
}) {
  const calendarRef = useRef<HTMLElement>(null);
  const navigate = (direction: -1 | 0 | 1) => {
    const calendar = calendarRef.current;
    if (!calendar) return;
    if (direction === 0) {
      const today = calendar.querySelector<HTMLElement>(`[data-date="${new Date().toISOString().slice(0, 10)}"]`);
      if (today) calendar.scrollTo({ left: Math.max(0, today.offsetLeft - calendar.clientWidth / 2 + today.clientWidth / 2), behavior: "smooth" });
      return;
    }
    calendar.scrollBy({ left: direction * 13 * 49, behavior: "smooth" });
  };
  return <div className="timeline-view"><header className="timeline-toolbar"><div className="segmented"><button className={mode === "forecast" ? "active" : ""} onClick={() => onMode("forecast")}>Forecast</button><button className={mode === "capacity" ? "active" : ""} onClick={() => onMode("capacity")}>Capacity Grid</button></div>{mode === "capacity" && <div className="date-navigation"><button onClick={() => navigate(-1)}>← Quarter</button><button onClick={() => navigate(0)}>Today</button><button onClick={() => navigate(1)}>Quarter →</button></div>}</header>{mode === "forecast" ? <ForecastView graph={graph} /> : <TimelineGrid timeline={timeline} graph={graph} selectedId={selectedId} calendarRef={calendarRef} onSelect={onSelect} onRefresh={onRefresh} onError={onError} onRegisterUndo={onRegisterUndo} />}</div>;
}

function SplitPanel({ split, graphVersion, onClose, onRefresh, onError, onRegisterUndo }: {
  split: SplitSession;
  graphVersion: number;
  onClose: () => void;
  onRefresh: () => Promise<void>;
  onError: (error: unknown) => void;
  onRegisterUndo: (action: UndoAction) => void;
}) {
  const [current, setCurrent] = useState(split);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const reload = async () => setCurrent(await api.split(current.id));
  const send = async () => {
    if (!message.trim()) return;
    setBusy(true);
    try { await api.splitMessage(current.id, message); setMessage(""); await reload(); } catch (error) { onError(error); } finally { setBusy(false); }
  };
  const validate = async () => {
    setBusy(true);
    try { const result = await api.validateSplit(current.id); window.alert(result.valid ? "提案已通过可执行性与项目图检查。" : "提案尚未通过检查，请继续调整。"); } catch (error) { onError(error); } finally { setBusy(false); }
  };
  const commit = async () => {
    if (!window.confirm("确认提交拆分？提交后将创建正式节点和关系。")) return;
    setBusy(true);
    try { const result = await api.commitSplit(current.id, graphVersion, current.current_proposal_version); onRegisterUndo({ kind: "batch", batchId: result.operation_batch.id }); await onRefresh(); onClose(); } catch (error) { onError(error); } finally { setBusy(false); }
  };
  const discard = async () => {
    if (!window.confirm("放弃当前拆分提案？未提交的内容不会写入项目图。")) return;
    try { await api.discardSplit(current.id); onClose(); } catch (error) { onError(error); }
  };
  return (
    <aside className="split-panel" role="dialog" aria-modal="true" aria-label="拆分会话">
      <header><div><span className="eyebrow">拆分会话</span><h2>协作拆分</h2></div><button className="icon-button" onClick={onClose} aria-label="关闭拆分会话">×</button></header>
      <div className="split-context"><span>当前状态</span><b>{current.state}</b><span>提案版本</span><b>v{current.current_proposal_version}</b></div>
      <div className="conversation">{current.messages.map((item) => <div key={item.id} className={`message ${item.role}`}><small>{item.role === "user" ? "你" : item.role === "assistant" ? "拆分助手" : "系统"}</small><p>{item.content}</p></div>)}</div>
      <section className="proposal-tree"><header><h3>当前提案 v{current.proposal?.version ?? 0}</h3><span>尚未写入项目图</span></header>{current.proposal?.nodes.map((node, index) => <article key={node.temporary_id}><i>{index + 1}</i><div><b>{node.title}</b><p>{node.done_when}</p><small>{node.estimated_effort_minutes} 分钟 · {node.required ? "必需" : "可选"}</small></div><span>✓</span></article>) ?? <p className="quiet">告诉我你希望如何拆分，或让我先提出一个版本。</p>}</section>
      <div className="split-compose"><textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="例如：合并第 1、2 项，把最后一项拆得更具体……" /><button className="primary" disabled={busy || !message.trim()} onClick={send}>发送并生成新版本</button></div>
      <footer><button onClick={discard}>放弃提案</button><button onClick={validate} disabled={!current.proposal || busy}>检查提案</button><button className="primary" onClick={commit} disabled={!current.proposal || busy}>提交拆分</button></footer>
    </aside>
  );
}

function MobileFallback({ graph, onDone, onSplit }: { graph: GraphResponse; onDone: (node: GraphNode) => void; onSplit: (node: GraphNode) => void }) {
  const actions = graph.nodes.filter((node) => node.work_type === "ACTION" && !["DONE", "CANCELLED", "SUPERSEDED"].includes(node.status)).slice(0, 12);
  return <main className="mobile-fallback"><header><span className="eyebrow">Global project file</span><h1>Yonc</h1><p>{graph.health.warning_count} graph warnings · {graph.pace.reliable ? `${graph.pace.median_hours?.toFixed(1)}h/week` : "pace baseline pending"}</p></header><section><h2>Next Actions</h2>{actions.length ? actions.map((node) => <article key={node.id}><div><b>{node.title}</b><span>{fmtDate(node.deadline)} · {formatEffort(node.estimated_effort_minutes)}</span></div><button onClick={() => onSplit(node)}>Split</button><button className="primary" onClick={() => onDone(node)}>Done</button></article>) : <p className="quiet">No open Actions in this project file.</p>}</section></main>;
}

export default function App() {
  const [view, setView] = useState<MainView>("canvas");
  const [timelineMode, setTimelineMode] = useState<TimelineMode>("capacity");
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [split, setSplit] = useState<SplitSession | null>(null);
  const [mobileDoneCandidate, setMobileDoneCandidate] = useState<GraphNode | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [undoNotice, setUndoNotice] = useState<string | null>(null);
  const initialised = useRef(false);
  const latestLoad = useRef(0);
  const undoStack = useRef<UndoAction[]>([]);
  const undoing = useRef(false);
  const undoNoticeTimer = useRef<number | null>(null);

  const registerUndo = useCallback((action: UndoAction) => {
    undoStack.current.push(action);
    if (undoStack.current.length > 100) undoStack.current.shift();
  }, []);
  const showUndoNotice = useCallback((message: string) => {
    setUndoNotice(message);
    if (undoNoticeTimer.current != null) window.clearTimeout(undoNoticeTimer.current);
    undoNoticeTimer.current = window.setTimeout(() => setUndoNotice(null), 1600);
  }, []);

  const handleError = useCallback((unknownError: unknown) => {
    setError(unknownError instanceof ApiError ? unknownError.message : "无法载入项目图，请重试。");
  }, []);

  const load = useCallback(async (blocking = false, reportError = blocking) => {
    // Keep the current view mounted during ordinary mutations. Replacing the
    // whole workspace with the initial-loading skeleton made every drag feel
    // like a page navigation instead of a direct manipulation.
    const requestId = ++latestLoad.current;
    if (blocking) setLoading(true);
    try {
      const [nextGraph, nextTimeline] = await Promise.all([api.graph(), api.timeline(TIMELINE_RANGE.start, TIMELINE_RANGE.end)]);
      if (requestId !== latestLoad.current) return;
      setGraph(nextGraph);
      setTimeline(nextTimeline);
      setSelectedId((current) => current && nextGraph.nodes.some((node) => node.id === current) ? current : null);
    } catch (unknownError) { if (reportError) handleError(unknownError); } finally { if (blocking) setLoading(false); }
  }, [handleError]);

  useEffect(() => {
    if (initialised.current) return;
    initialised.current = true;
    (async () => {
      try {
        await load(true, true);
      } catch (unknownError) { handleError(unknownError); setLoading(false); }
    })();
  }, [handleError, load]);

  const refresh = useCallback(async () => { await load(); }, [load]);
  useEffect(() => {
    const undoFromKeyboard = (event: KeyboardEvent) => {
      if ((!event.ctrlKey && !event.metaKey) || event.shiftKey || event.key.toLowerCase() !== "z") return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return;
      event.preventDefault();
      if (undoing.current || !graph) return;
      undoing.current = true;
      void (async () => {
        let action = undoStack.current.pop();
        try {
          if (!action) {
            const batches = await api.operationBatches(50);
            const latest = batches.find((batch) => !batch.undone_at && batch.actor_channel === "user_ui");
            if (latest) action = { kind: "batch", batchId: latest.id };
          }
          if (!action) { showUndoNotice("没有可撤销的操作"); return; }
          if (action.kind === "local") await action.undo();
          else { await api.undoBatch(action.batchId, graph.graph_version); await refresh(); }
          showUndoNotice("已撤销上一步操作");
        } catch (unknownError) {
          if (action) undoStack.current.push(action);
          handleError(unknownError);
        } finally { undoing.current = false; }
      })();
    };
    window.addEventListener("keydown", undoFromKeyboard);
    return () => window.removeEventListener("keydown", undoFromKeyboard);
  }, [graph, handleError, refresh, showUndoNotice]);
  useEffect(() => {
    if (!initialised.current) return;
    const quietlySync = () => { if (document.visibilityState === "visible") void load(); };
    const timer = window.setInterval(quietlySync, 30_000);
    window.addEventListener("focus", quietlySync);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", quietlySync); };
  }, [load]);
  const openSplit = async (node: GraphNode) => {
    try { setSplit(await api.startSplit(node.id)); } catch (unknownError) { handleError(unknownError); }
  };
  const selected = graph?.nodes.find((node) => node.id === selectedId) ?? null;
  const nodeColors = useMemo(() => graph ? colorsForNodes(graph.nodes) : {}, [graph]);
  const mobileDone = (node: GraphNode) => { setSelectedId(node.id); setMobileDoneCandidate(node); };
  const confirmMobileDone = async () => {
    if (!mobileDoneCandidate || !graph) return;
    try {
      const result = await api.transition(mobileDoneCandidate.id, "done", graph.graph_version);
      registerUndo({ kind: "batch", batchId: result.operation_batch_id });
      setMobileDoneCandidate(null);
      await refresh();
    } catch (unknownError) { handleError(unknownError); }
  };

  return (
    <div className={`app-shell view-${view}`}>
      <nav className="side-nav" aria-label="Primary"><a className="brand" href="/v2/" aria-label="Yonc home">Y</a><button className={view === "canvas" ? "active" : ""} onClick={() => setView("canvas")} aria-label="Canvas"><span>▦</span><small>Canvas</small></button><button className={view === "timeline" ? "active" : ""} onClick={() => setView("timeline")} aria-label="Timeline"><span>◫</span><small>Timeline</small></button><button className="nav-settings" onClick={() => setSettingsOpen(true)} aria-label="Settings"><span>⚙</span><small>Settings</small></button><a className="legacy-link" href="/legacy" title="Open legacy UI">v1</a></nav>
      {loading && <div className="loading-state"><div /><div /><div /><p>Loading project graph…</p></div>}
      {!loading && graph && timeline && <>
        <main className="desktop-content">{view === "canvas" ? <CanvasView graph={graph} selectedId={selectedId} onSelect={setSelectedId} onClearSelection={() => setSelectedId(null)} onOpenSplit={openSplit} onRegisterUndo={registerUndo} /> : <TimelineView timeline={timeline} graph={graph} selectedId={selectedId} mode={timelineMode} onMode={setTimelineMode} onSelect={setSelectedId} onRefresh={refresh} onError={handleError} onRegisterUndo={registerUndo} />}</main>
        {view === "canvas" && selected && <NodeInspector node={selected} color={nodeColors[selected.id]} graphVersion={graph.graph_version} onClose={() => setSelectedId(null)} onRefresh={refresh} onOpenSplit={openSplit} onError={handleError} onRegisterUndo={registerUndo} />}
        <MobileFallback graph={graph} onDone={mobileDone} onSplit={openSplit} />
      </>}
      {!loading && graph && !graph.nodes.length && <div className="empty-state"><h1>No work in this project file</h1><p>Import existing work or capture a Goal to begin.</p></div>}
      {split && graph && <SplitPanel split={split} graphVersion={graph.graph_version} onClose={() => setSplit(null)} onRefresh={refresh} onError={handleError} onRegisterUndo={registerUndo} />}
      {mobileDoneCandidate && <Modal title="确认完成" onClose={() => setMobileDoneCandidate(null)}><p>确认标记“{mobileDoneCandidate.title}”为完成？完成状态只能由你确认。</p><div className="modal-actions"><button onClick={() => setMobileDoneCandidate(null)}>取消</button><button className="primary" onClick={confirmMobileDone}>标记完成</button></div></Modal>}
      {settingsOpen && <Modal title="设置" onClose={() => setSettingsOpen(false)}><p>当前使用全局项目视图。排期只能在 Timeline 中修改，Canvas 保持为只读时间定位。</p><div className="modal-actions"><button className="primary" onClick={() => setSettingsOpen(false)}>完成</button></div></Modal>}
      {error && <Modal title="操作未完成" onClose={() => setError(null)}><p>{error}</p><div className="modal-actions"><button className="primary" onClick={() => setError(null)}>知道了</button></div></Modal>}
      {undoNotice && <div className="undo-notice" role="status">{undoNotice}</div>}
    </div>
  );
}
