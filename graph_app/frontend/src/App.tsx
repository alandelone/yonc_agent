import ELK from "elkjs/lib/elk.bundled.js";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "./api";
import type { GraphEdge, GraphNode, GraphResponse, SplitAnnotation, SplitSession, TimelineCell, TimelineResponse, YoncConfig } from "./types";

type MainView = "canvas" | "timeline";
type TimelineMode = "forecast" | "capacity";
export type TimelinePoolFilter = "all" | "jobs" | "tasks";
type Position = { x: number; y: number };
type SelectionBounds = { left: number; top: number; right: number; bottom: number };
type ConnectorSide = "top" | "right" | "bottom" | "left";
type UndoAction = { kind: "local"; undo: () => Promise<void> | void } | { kind: "batch"; batchId: string };

const CARD_W = 184;
const COMPACT_CARD_H = 66;
const CANVAS_AXIS_HEIGHT = 54;
const CANVAS_TIME_PAST_MONTHS = 18;
const CANVAS_TIME_FUTURE_MONTHS = 60;
const CANVAS_TIME_START_PADDING = 180;
const CANVAS_TIME_END_PADDING = 220;
const CANVAS_TIME_MIN_PX_PER_DAY = 1.8;
const CANVAS_LAYOUT_VERSION = 9;
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

export function nodeCardWidth(node: Pick<GraphNode, "wbs_level">) {
  if (node.wbs_level === 1) return 244;
  if (node.wbs_level === 2) return 220;
  if (node.wbs_level === 3) return 200;
  if (node.wbs_level === 4) return 180;
  return CARD_W;
}

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

function shadeHexColor(hex: string, factor: number) {
  const value = Number.parseInt(hex.slice(1), 16);
  if (!Number.isFinite(value)) return hex;
  const channel = (shift: number) => Math.max(0, Math.min(255, Math.round(((value >> shift) & 255) * factor)));
  return `#${[channel(16), channel(8), channel(0)].map((item) => item.toString(16).padStart(2, "0")).join("")}`;
}

export function configuredThemeColor(node: GraphNode, nodesById: ReadonlyMap<string, GraphNode>, config?: YoncConfig | null) {
  if (!config?.themes.length) return null;
  let current: GraphNode | undefined = node;
  const visited = new Set<string>();
  while (current && !visited.has(current.id)) {
    visited.add(current.id);
    const rawTag = current.tags?.["Task Theme with colour"];
    const tag = Array.isArray(rawTag) ? rawTag.join(" | ") : String(rawTag ?? "");
    const theme = [...config.themes].sort((a, b) => b.name.length - a.name.length).find((candidate) => (
      tag === candidate.name || tag.startsWith(`${candidate.name} `) || candidate.sub_themes.some((subTheme) => tag === subTheme)
    ));
    if (theme) return shadeHexColor(theme.color, ({ 1: 1.16, 2: 1.03, 3: .9, 4: .76 } as Record<number, number>)[node.wbs_level ?? 3] ?? .9);
    current = current.parent_id ? nodesById.get(current.parent_id) : undefined;
  }
  return null;
}

export function colorsForNodes(nodes: GraphNode[], config?: YoncConfig | null) {
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  return Object.fromEntries(nodes.map((node) => [node.id, configuredThemeColor(node, nodesById, config) ?? wbsColorFor(projectKeyForNode(node, nodesById), node.wbs_level)]));
}

const timelineWorkTypes = new Set(["GOAL", "DELIVERABLE", "WORK_PACKAGE", "ACTION", "UNCLASSIFIED"]);

export function timelinePoolMatches(nodes: GraphNode[], query: string, filter: TimelinePoolFilter) {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return nodes
    .filter((node) => timelineWorkTypes.has(node.work_type))
    .filter((node) => filter === "all" || (filter === "tasks" ? node.work_type === "ACTION" : node.work_type !== "ACTION" && node.work_type !== "UNCLASSIFIED"))
    .filter((node) => terms.every((term) => node.title.toLocaleLowerCase().includes(term)))
    .sort((a, b) => {
      if (!terms.length && Boolean(a.planned_start) !== Boolean(b.planned_start)) return a.planned_start ? 1 : -1;
      const normalizedQuery = terms.join(" ");
      const aTitle = a.title.toLocaleLowerCase();
      const bTitle = b.title.toLocaleLowerCase();
      const aRank = aTitle === normalizedQuery ? 0 : aTitle.startsWith(normalizedQuery) ? 1 : 2;
      const bRank = bTitle === normalizedQuery ? 0 : bTitle.startsWith(normalizedQuery) ? 1 : 2;
      return aRank - bRank || a.title.localeCompare(b.title);
    });
}

export function canvasEdgeEndpoints(edge: Pick<GraphEdge, "source_id" | "target_id" | "relation">) {
  return edge.relation === "contains"
    ? { sourceId: edge.target_id, targetId: edge.source_id }
    : { sourceId: edge.source_id, targetId: edge.target_id };
}

export function canvasContentBounds(positions: Record<string, Position>, nodeHeights: Record<string, number>, nodeWidths: Record<string, number> = {}) {
  const entries = Object.entries(positions);
  if (!entries.length) return null;
  return {
    left: Math.min(...entries.map(([, position]) => position.x)),
    top: Math.min(...entries.map(([, position]) => position.y)),
    right: Math.max(...entries.map(([id, position]) => position.x + (nodeWidths[id] ?? CARD_W))),
    bottom: Math.max(...entries.map(([id, position]) => position.y + (nodeHeights[id] ?? COMPACT_CARD_H))),
  };
}

export function nodesInSelectionBounds(positions: Record<string, Position>, nodeHeights: Record<string, number>, bounds: SelectionBounds, nodeWidths: Record<string, number> = {}) {
  return Object.entries(positions).filter(([id, position]) => (
    position.x < bounds.right
    && position.x + (nodeWidths[id] ?? CARD_W) > bounds.left
    && position.y < bounds.bottom
    && position.y + (nodeHeights[id] ?? COMPACT_CARD_H) > bounds.top
  )).map(([id]) => id);
}

export function arrangeCanvasPositions(desired: Record<string, Position>, nodeHeights: Record<string, number>, nodeWidths: Record<string, number> = {}) {
  const gap = 18;
  const arranged: Record<string, Position> = {};
  const placed: Array<{ id: string; x: number; y: number; width: number; height: number }> = [];
  const ordered = Object.entries(desired).sort(([, left], [, right]) => left.y - right.y || left.x - right.x);
  for (const [id, position] of ordered) {
    const height = nodeHeights[id] ?? COMPACT_CARD_H;
    const width = nodeWidths[id] ?? CARD_W;
    let y = position.y;
    while (true) {
      const conflicts = placed.filter((item) =>
        position.x < item.x + item.width + gap
        && position.x + width + gap > item.x
        && y < item.y + item.height + gap
        && y + height + gap > item.y,
      );
      if (!conflicts.length) break;
      y = Math.max(...conflicts.map((item) => item.y + item.height + gap));
    }
    arranged[id] = { x: position.x, y };
    placed.push({ id, x: position.x, y, width, height });
  }
  return arranged;
}

export function canvasPositionForNode(node: Pick<GraphNode, "planned_start" | "deadline">, automatic: Position, manual?: Position) {
  const timelinePositioned = Boolean(node.planned_start || node.deadline);
  return {
    x: timelinePositioned ? automatic.x : manual?.x ?? automatic.x,
    y: manual?.y ?? automatic.y,
  };
}

export function placeChildrenBeforeDatedParents(
  nodes: Array<Pick<GraphNode, "id" | "parent_id" | "planned_start" | "deadline">>,
  positions: Record<string, Position>,
  layerGap = 56,
) {
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  const next = Object.fromEntries(Object.entries(positions).map(([id, position]) => [id, { ...position }]));
  for (const node of nodes) {
    if (node.planned_start || node.deadline || !next[node.id]) continue;
    let ancestorId = node.parent_id;
    let depth = 1;
    let rightmostAllowed = Number.POSITIVE_INFINITY;
    const visited = new Set<string>([node.id]);
    while (ancestorId && !visited.has(ancestorId)) {
      visited.add(ancestorId);
      const ancestor = nodesById.get(ancestorId);
      if (!ancestor) break;
      if ((ancestor.planned_start || ancestor.deadline) && next[ancestor.id]) {
        rightmostAllowed = Math.min(rightmostAllowed, next[ancestor.id].x - depth * (CARD_W + layerGap));
      }
      ancestorId = ancestor.parent_id;
      depth += 1;
    }
    if (Number.isFinite(rightmostAllowed)) next[node.id].x = Math.min(next[node.id].x, rightmostAllowed);
  }
  return next;
}

type CanvasFamilyNode = Pick<GraphNode, "id" | "parent_id" | "wbs_level" | "planned_start" | "deadline">;

export function wideCanvasFamilyLayout(
  members: CanvasFamilyNode[],
  seedPositions: Record<string, Position>,
  nodeHeights: Record<string, number>,
) {
  const byId = new Map(members.map((node) => [node.id, node]));
  const root = members.find((node) => node.wbs_level === 1) ?? members.find((node) => !node.parent_id) ?? members[0];
  if (!root) return {};
  const ordered = (items: CanvasFamilyNode[]) => [...items].sort((left, right) =>
    (seedPositions[left.id]?.y ?? 0) - (seedPositions[right.id]?.y ?? 0)
    || (seedPositions[left.id]?.x ?? 0) - (seedPositions[right.id]?.x ?? 0)
    || left.id.localeCompare(right.id));
  const levelTwo = ordered(members.filter((node) => node.id !== root.id && node.wbs_level === 2));
  const branchMembers = new Map<string, CanvasFamilyNode[]>(levelTwo.map((node) => [node.id, [node]]));
  const miscellaneous: CanvasFamilyNode[] = [];
  for (const node of members) {
    if (node.id === root.id || node.wbs_level === 2) continue;
    let ancestorId = node.parent_id;
    const visited = new Set<string>();
    let branchId: string | null = null;
    while (ancestorId && !visited.has(ancestorId)) {
      visited.add(ancestorId);
      const ancestor = byId.get(ancestorId);
      if (!ancestor) break;
      if (ancestor.wbs_level === 2) { branchId = ancestor.id; break; }
      ancestorId = ancestor.parent_id;
    }
    if (branchId && branchMembers.has(branchId)) branchMembers.get(branchId)!.push(node);
    else miscellaneous.push(node);
  }
  const rawBranches = levelTwo.map((node) => branchMembers.get(node.id)!).filter(Boolean);
  if (miscellaneous.length || !rawBranches.length) rawBranches.push(miscellaneous.length ? miscellaneous : [root]);

  const branchLayouts = rawBranches.map((branch) => {
    const positions: Record<string, Position> = {};
    let cursorX = 0;
    let branchHeight = 0;
    const groups = [
      ordered(branch.filter((node) => node.wbs_level === 4 || node.wbs_level == null)),
      ordered(branch.filter((node) => node.wbs_level === 3)),
      ordered(branch.filter((node) => node.wbs_level === 2)),
    ].filter((group) => group.length);
    for (const group of groups) {
      const level = group[0].wbs_level;
      const preferredRows = level === 4 || level == null ? (group.length > 10 ? 4 : 2) : level === 3 ? 3 : 1;
      const rows = Math.min(preferredRows, group.length);
      const columns = Math.ceil(group.length / rows);
      const cellWidth = Math.max(...group.map(nodeCardWidth)) + 26;
      const cellHeight = Math.max(...group.map((node) => nodeHeights[node.id] ?? COMPACT_CARD_H)) + 24;
      group.forEach((node, index) => {
        positions[node.id] = { x: cursorX + Math.floor(index / rows) * cellWidth, y: (index % rows) * cellHeight };
      });
      cursorX += columns * cellWidth + 64;
      branchHeight = Math.max(branchHeight, rows * cellHeight - 24);
    }
    return { positions, width: Math.max(0, cursorX - 64), height: Math.max(COMPACT_CARD_H, branchHeight) };
  });

  const branchColumns = Math.max(1, Math.ceil(Math.sqrt(branchLayouts.length / 2)));
  const cellWidth = Math.max(...branchLayouts.map((branch) => branch.width)) + 72;
  const cellHeight = Math.max(...branchLayouts.map((branch) => branch.height)) + 58;
  const result: Record<string, Position> = {};
  branchLayouts.forEach((branch, index) => {
    const offsetX = (index % branchColumns) * cellWidth;
    const offsetY = Math.floor(index / branchColumns) * cellHeight;
    for (const [id, position] of Object.entries(branch.positions)) result[id] = { x: position.x + offsetX, y: position.y + offsetY };
  });
  const gridWidth = Math.min(branchLayouts.length, branchColumns) * cellWidth - 72;
  const gridHeight = Math.ceil(branchLayouts.length / branchColumns) * cellHeight - 58;
  result[root.id] = { x: gridWidth + 86, y: Math.max(0, (gridHeight - (nodeHeights[root.id] ?? COMPACT_CARD_H)) / 2) };
  return result;
}

export function canvasSubtreeIds(nodes: Array<Pick<GraphNode, "id" | "parent_id">>, rootId: string) {
  const children = new Map<string, string[]>();
  for (const node of nodes) {
    if (!node.parent_id) continue;
    const siblings = children.get(node.parent_id) ?? [];
    siblings.push(node.id);
    children.set(node.parent_id, siblings);
  }
  const result: string[] = [];
  const queue = [rootId];
  const visited = new Set<string>();
  while (queue.length) {
    const id = queue.shift()!;
    if (visited.has(id)) continue;
    visited.add(id);
    result.push(id);
    queue.push(...(children.get(id) ?? []));
  }
  return result;
}

export function arrangeCanvasFamilies(
  nodes: CanvasFamilyNode[],
  seedPositions: Record<string, Position>,
  nodeHeights: Record<string, number>,
  todayX: number,
  gap = 48,
) {
  const nodesById = new Map<string, ColorNode>(nodes.map((node) => [node.id, node]));
  const families = new Map<string, CanvasFamilyNode[]>();
  for (const node of nodes) {
    if (!seedPositions[node.id]) continue;
    const key = projectKeyForNode(node, nodesById);
    const members = families.get(key) ?? [];
    members.push(node);
    families.set(key, members);
  }
  const items = [...families.entries()].map(([key, members]) => {
    const scheduled = members.some((node) => Boolean(node.planned_start || node.deadline));
    const widePositions = wideCanvasFamilyLayout(members, seedPositions, nodeHeights);
    const datedAnchor = members.find((node) => (node.planned_start || node.deadline) && seedPositions[node.id]);
    const anchorDx = datedAnchor ? seedPositions[datedAnchor.id].x - widePositions[datedAnchor.id].x : 0;
    const memberPositions = Object.fromEntries(members.map((node) => {
      const wide = widePositions[node.id] ?? seedPositions[node.id];
      const x = node.planned_start || node.deadline ? seedPositions[node.id].x : wide.x + anchorDx;
      return [node.id, { x, y: wide.y }];
    }));
    const memberWidths = Object.fromEntries(members.map((node) => [node.id, nodeCardWidth(node)]));
    const bounds = canvasContentBounds(memberPositions, nodeHeights, memberWidths)!;
    return { key, members, bounds, memberPositions, scheduled };
  }).sort((left, right) => Number(left.scheduled) - Number(right.scheduled) || left.bounds.top - right.bounds.top || left.key.localeCompare(right.key));

  const arranged: Record<string, Position> = {};
  const placed: Array<{ x: number; y: number; width: number; height: number }> = [];
  const futureStart = todayX + 120;
  const futureBoundary = futureStart + 2600;
  let shelfLeft = futureStart;
  let shelfTop = 82;
  let shelfBottom = shelfTop;

  for (const item of items) {
    const familyWidth = item.bounds.right - item.bounds.left;
    let targetLeft = item.bounds.left;
    let targetTop = 82;
    if (!item.scheduled) {
      if (shelfLeft > futureStart && shelfLeft + familyWidth > futureBoundary) {
        shelfLeft = futureStart;
        shelfTop = shelfBottom + gap;
      }
      targetLeft = Math.max(futureStart, Math.min(shelfLeft, futureBoundary - familyWidth));
      targetTop = shelfTop;
    }
    const dx = targetLeft - item.bounds.left;
    let dy = targetTop - item.bounds.top;
    for (let pass = 0; pass < nodes.length + 1; pass += 1) {
      let pushDown = 0;
      for (const node of item.members) {
        const position = item.memberPositions[node.id];
        if (!position) continue;
        const x = position.x + dx;
        const y = position.y + dy;
        const width = nodeCardWidth(node);
        const height = nodeHeights[node.id] ?? COMPACT_CARD_H;
        for (const other of placed) {
          const overlapsX = x < other.x + other.width + gap && x + width + gap > other.x;
          const overlapsY = y < other.y + other.height + gap && y + height + gap > other.y;
          if (overlapsX && overlapsY) pushDown = Math.max(pushDown, other.y + other.height + gap - y);
        }
      }
      if (pushDown <= 0) break;
      dy += pushDown;
    }
    for (const node of item.members) {
      const position = item.memberPositions[node.id];
      if (!position) continue;
      const next = { x: position.x + dx, y: position.y + dy };
      arranged[node.id] = next;
      placed.push({ x: next.x, y: next.y, width: nodeCardWidth(node), height: nodeHeights[node.id] ?? COMPACT_CARD_H });
    }
    if (!item.scheduled) {
      shelfLeft = targetLeft + familyWidth + gap;
      shelfBottom = Math.max(shelfBottom, item.bounds.bottom + dy);
    }
  }
  return arranged;
}

function addDays(value: string, days: number) {
  const next = new Date(`${value}T12:00:00`);
  next.setDate(next.getDate() + days);
  return next.toISOString().slice(0, 10);
}

function daysBetween(left: string, right: string) {
  return Math.round((new Date(`${right}T12:00:00`).getTime() - new Date(`${left}T12:00:00`).getTime()) / 86_400_000);
}

export function anchoredScrollPosition(scrollLeft: number, scrollTop: number, anchorX: number, anchorY: number, currentZoom: number, nextZoom: number, fixedTop = 0) {
  const worldX = (scrollLeft + anchorX) / currentZoom;
  const worldY = (scrollTop + anchorY - fixedTop) / currentZoom;
  return { left: Math.max(0, worldX * nextZoom - anchorX), top: Math.max(0, fixedTop + worldY * nextZoom - anchorY) };
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

export function nodeCardHeight(node: Pick<GraphNode, "planned_start" | "deadline" | "estimated_effort_minutes" | "resource_count" | "health"> & { wbs_level?: number | null }) {
  const { hasMeta, hasSignals } = nodeCardInfo(node);
  const baseHeight = node.wbs_level === 1 ? 88 : node.wbs_level === 2 ? 78 : node.wbs_level === 3 ? 72 : COMPACT_CARD_H;
  return baseHeight + (hasMeta ? 13 : 0) + (hasSignals ? 15 : 0);
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
      children: nodes.map((node) => ({ id: node.id, width: nodeCardWidth(node), height: nodeCardHeight(node) })),
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

export function taskTypeEmojisForNode(node: Pick<GraphNode, "tags">, yoncConfig?: YoncConfig | null): string[] {
  const raw = node.tags?.["Task Type"] ?? node.tags?.["task_type"] ?? node.tags?.["Task Types"];
  if (!raw || typeof raw !== "string") return [];
  const parts = raw.split(",").map((s) => s.trim()).filter(Boolean);
  const emojis: string[] = [];
  const configTypes = yoncConfig?.task_types ?? [];

  for (const part of parts) {
    const [left, right] = part.split("|").map((s) => s.trim());
    const typeName = (right || left || "").toLowerCase();
    const configMatch = configTypes.find(
      (t) => t.name.toLowerCase() === typeName || t.tag.toLowerCase() === typeName || (t.emoji && left.includes(t.emoji))
    );
    const emoji = configMatch?.emoji || (left && /\p{Extended_Pictographic}/u.test(left) ? left : "");
    if (emoji && !emojis.includes(emoji)) {
      emojis.push(emoji);
    }
  }
  return emojis;
}

export function modeInfoForNode(node: Pick<GraphNode, "tags">, yoncConfig?: YoncConfig | null) {
  const raw = node.tags?.["Modes"] ?? node.tags?.["Mode"] ?? node.tags?.["mode"];
  if (!raw || typeof raw !== "string") return null;
  const modeStr = String(raw).trim();
  if (!modeStr) return null;
  const configModes = yoncConfig?.modes ?? [];
  const configMatch = configModes.find(
    (m) => m.mode_name.toLowerCase() === modeStr.toLowerCase() ||
           modeStr.toLowerCase().includes(m.mode_name.toLowerCase()) ||
           m.mode_name.toLowerCase().includes(modeStr.toLowerCase())
  );
  return {
    raw: modeStr,
    name: configMatch?.mode_name ?? modeStr,
    color: configMatch?.color ?? "#64748b",
  };
}

function NodeCard({ node, position, height, color, selected, yoncConfig, onSelect, onSplit, onPointerDown, registerElement }: {
  node: GraphNode;
  position: Position;
  height: number;
  color: string;
  selected: boolean;
  yoncConfig?: YoncConfig | null;
  onSelect: () => void;
  onSplit: () => void;
  onPointerDown: (event: React.PointerEvent<HTMLElement>) => void;
  registerElement: (element: HTMLElement | null) => void;
}) {
  const display = splitCardTitle(node.title);
  const cardDescription = node.description || display.description;
  const { hasMeta, hasSignals } = nodeCardInfo(node);
  const effort = (node.estimated_effort_minutes ?? 0) > 0 ? formatEffort(node.estimated_effort_minutes) : null;
  const taskEmojis = taskTypeEmojisForNode(node, yoncConfig);
  const mode = modeInfoForNode(node, yoncConfig);
  const progressRatio = node.progress?.ratio ?? 0;
  const isRingCovered = node.status === "DONE" || progressRatio >= 0.82;

  const [modeWidth, setModeWidth] = useState<number | null>(null);
  const modeRef = useCallback((el: HTMLElement | null) => {
    if (el) {
      const width = el.offsetWidth || el.getBoundingClientRect().width;
      if (width > 0) setModeWidth(Math.ceil(width));
    }
  }, []);

  const estWidth = mode ? Math.max(30, Math.round(mode.name.length * 8.5)) : 0;
  const activeWidth = modeWidth ?? estWidth;
  const cutStart = 8;
  const cutEnd = 10 + activeWidth + 3;

  return (
    <article
      ref={registerElement}
      data-node-id={node.id}
      data-wbs-level={node.wbs_level ?? undefined}
      className={`node-card status-${node.status.toLowerCase()} pressure-${node.pressure?.level ?? "low"} ${selected ? "selected" : ""} ${mode ? "has-mode" : ""}`}
      style={{
        width: nodeCardWidth(node),
        height,
        transform: `translate(${position.x}px, ${position.y}px)`,
        "--node-color": color,
        "--progress": progressRatio,
        "--mode-cut-start": `${cutStart}px`,
        "--mode-cut-end": `${cutEnd}px`,
      } as React.CSSProperties}
      onClick={(event) => { event.stopPropagation(); if (!event.shiftKey) onSelect(); }}
      onPointerDown={onPointerDown}
      tabIndex={0}
      aria-selected={selected}
      aria-label={`${node.title}, ${node.work_type}, ${node.status}`}
      onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && onSelect()}
    >
      {mode && (
        <span
          ref={modeRef}
          className={`node-mode-text ${isRingCovered ? "ring-passed" : ""}`}
          style={{ "--mode-color": mode.color } as React.CSSProperties}
          title={`Mode: ${mode.name}`}
          aria-hidden="true"
        >
          {mode.name}
        </span>
      )}
      <div className="node-topline">
        <span className="node-wbs-meta">
          {taskEmojis.length > 0 && (
            <span className="node-task-emoji" title={String(node.tags?.["Task Type"] || "")} aria-hidden="true">
              {taskEmojis.join("")}
            </span>
          )}
          <span className="node-wbs-text">{node.wbs_level ? `L${node.wbs_level}` : "•"} {node.work_type.replace("_", " ")}</span>
        </span>
        <span className="node-state">{node.status}</span>
      </div>
      <h3 className={cardDescription ? "with-description" : undefined}><span>{display.title}</span>{cardDescription && <small className="node-description">{cardDescription}</small>}</h3>
      {hasMeta && <div className="node-meta">{node.planned_start && <span>{fmtDate(node.planned_start)}</span>}{node.deadline ? <span className={!node.planned_start ? "meta-end" : undefined}>⚑ {fmtDate(node.deadline)}</span> : effort && <span className={!node.planned_start ? "meta-end" : undefined}>{effort}</span>}</div>}
      {hasSignals && <div className="node-signals">{node.resource_count > 0 && <span>{node.resource_count} refs</span>}{(node.health?.length ?? 0) > 0 && <span className="warning signal-end" title="Graph health warning">△ {node.health.length}</span>}</div>}
      <button className="split-plus" onClick={(event) => { event.stopPropagation(); onSplit(); }} aria-label="打开拆分会话">+</button>
    </article>
  );
}

export function logarithmicDateOffset(value: string, anchor: string) {
  const delta = daysBetween(anchor, value);
  const distance = Math.abs(delta);
  return Math.sign(delta) * (Math.log1p(distance / 30) * 520 + distance * CANVAS_TIME_MIN_PX_PER_DAY);
}

function monthBoundary(anchor: Date, offset: number) {
  return new Date(anchor.getFullYear(), anchor.getMonth() + offset, 1, 12).toISOString().slice(0, 10);
}

export function canvasTimeRange(anchor: Date, scheduledDates: string[]) {
  const starts = [monthBoundary(anchor, -CANVAS_TIME_PAST_MONTHS), ...scheduledDates.map((value) => monthBoundary(new Date(`${value}T12:00:00`), -6))];
  const ends = [monthBoundary(anchor, CANVAS_TIME_FUTURE_MONTHS), ...scheduledDates.map((value) => monthBoundary(new Date(`${value}T12:00:00`), 18))];
  return { start: starts.sort()[0], end: ends.sort().at(-1)! };
}

function LogarithmicTimeAxis({ start, end, anchor, todayX, zoom, height }: { start: string; end: string; anchor: string; todayX: number; zoom: number; height: number }) {
  const ticks: React.ReactNode[] = [];
  const cursor = new Date(`${start.slice(0, 7)}-01T12:00:00`);
  const last = new Date(`${end}T12:00:00`);
  while (cursor <= last) {
    const value = cursor.toISOString().slice(0, 10);
    const x = (todayX + logarithmicDateOffset(value, anchor)) * zoom;
    const month = cursor.toLocaleString("en", { month: "long" });
    ticks.push(<div className="month-tick" key={value} style={{ left: x, height }}><b>{month}</b>{cursor.getMonth() === 0 && <span>{cursor.getFullYear()}</span>}</div>);
    cursor.setMonth(cursor.getMonth() + 1);
  }
  return <div className="time-axis"><div className="axis-title">Logarithmic time</div>{ticks}</div>;
}

export type ObstacleBox = {
  id?: string;
  left: number;
  top: number;
  right: number;
  bottom: number;
};

export function segmentIntersectsBox(p1: Position, p2: Position, box: ObstacleBox, pad = 6) {
  const bLeft = box.left - pad;
  const bRight = box.right + pad;
  const bTop = box.top - pad;
  const bBottom = box.bottom + pad;
  if (p1.y === p2.y) {
    const minX = Math.min(p1.x, p2.x);
    const maxX = Math.max(p1.x, p2.x);
    return bLeft < maxX && minX < bRight && bTop < p1.y && p1.y < bBottom;
  }
  if (p1.x === p2.x) {
    const minY = Math.min(p1.y, p2.y);
    const maxY = Math.max(p1.y, p2.y);
    return bLeft < p1.x && p1.x < bRight && bTop < maxY && minY < bBottom;
  }
  return false;
}

export function pathIntersectsObstacles(points: Position[], obstacles: ObstacleBox[], pad = 6) {
  for (let i = 0; i < points.length - 1; i++) {
    for (const obs of obstacles) {
      if (segmentIntersectsBox(points[i], points[i + 1], obs, pad)) {
        return true;
      }
    }
  }
  return false;
}

export function simplifyPoints(points: Position[]): Position[] {
  const cleaned: Position[] = [];
  for (const p of points) {
    if (!cleaned.length) {
      cleaned.push(p);
      continue;
    }
    const last = cleaned[cleaned.length - 1];
    if (Math.abs(last.x - p.x) < 0.5 && Math.abs(last.y - p.y) < 0.5) continue;
    cleaned.push(p);
  }
  if (cleaned.length <= 2) return cleaned;
  const result: Position[] = [cleaned[0]];
  for (let i = 1; i < cleaned.length - 1; i++) {
    const prev = result[result.length - 1];
    const curr = cleaned[i];
    const next = cleaned[i + 1];
    if ((prev.x === curr.x && curr.x === next.x) || (prev.y === curr.y && curr.y === next.y)) {
      continue;
    }
    result.push(curr);
  }
  result.push(cleaned[cleaned.length - 1]);
  return result;
}

export function curvedOrthogonalPathFromPoints(points: Position[]) {
  if (points.length <= 1) return "";
  if (points.length === 2) {
    if (points[0].y === points[1].y) return `M ${points[0].x} ${points[0].y} H ${points[1].x}`;
    if (points[0].x === points[1].x) return `M ${points[0].x} ${points[0].y} V ${points[1].y}`;
    return `M ${points[0].x} ${points[0].y} L ${points[1].x} ${points[1].y}`;
  }
  let path = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length - 1; i++) {
    const prev = points[i - 1];
    const curr = points[i];
    const next = points[i + 1];
    const lenPrev = Math.hypot(curr.x - prev.x, curr.y - prev.y);
    const lenNext = Math.hypot(next.x - curr.x, next.y - curr.y);
    const radius = Math.min(14, lenPrev / 2, lenNext / 2);
    const dx1 = Math.sign(curr.x - prev.x);
    const dy1 = Math.sign(curr.y - prev.y);
    const dx2 = Math.sign(next.x - curr.x);
    const dy2 = Math.sign(next.y - curr.y);
    if (radius < 1) {
      if (curr.x !== prev.x) path += ` H ${curr.x}`;
      else if (curr.y !== prev.y) path += ` V ${curr.y}`;
    } else {
      if (dx1 !== 0) path += ` H ${curr.x - dx1 * radius}`;
      else if (dy1 !== 0) path += ` V ${curr.y - dy1 * radius}`;
      path += ` Q ${curr.x} ${curr.y} ${curr.x + dx2 * radius} ${curr.y + dy2 * radius}`;
    }
  }
  const last = points[points.length - 1];
  const secondLast = points[points.length - 2];
  if (last.x !== secondLast.x) path += ` H ${last.x}`;
  else if (last.y !== secondLast.y) path += ` V ${last.y}`;
  return path;
}

function hashString(value: string) {
  let hash = 0;
  for (let i = 0; i < value.length; i++) hash = (hash * 31 + value.charCodeAt(i)) >>> 0;
  return hash;
}

export function routeObstacleFreePath(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  horizontal: boolean,
  obstacles: ObstacleBox[] = [],
  edgeId = "",
): Position[] {
  const defaultMid = Math.round(horizontal ? (x1 + x2) / 2 : (y1 + y2) / 2);
  const defaultPoints = horizontal
    ? [{ x: x1, y: y1 }, { x: defaultMid, y: y1 }, { x: defaultMid, y: y2 }, { x: x2, y: y2 }]
    : [{ x: x1, y: y1 }, { x: x1, y: defaultMid }, { x: x2, y: defaultMid }, { x: x2, y: y2 }];
  const simplifiedDefault = simplifyPoints(defaultPoints);

  if (!obstacles.length || !pathIntersectsObstacles(simplifiedDefault, obstacles)) {
    return simplifiedDefault;
  }

  const pad = 12;
  const minX = Math.min(x1, x2) - pad;
  const maxX = Math.max(x1, x2) + pad;
  const minY = Math.min(y1, y2) - pad;
  const maxY = Math.max(y1, y2) + pad;
  const relevant = obstacles.filter((obs) => (
    obs.right > minX && obs.left < maxX && obs.bottom > minY - 100 && obs.top < maxY + 100
  ));

  if (!relevant.length || !pathIntersectsObstacles(simplifiedDefault, relevant)) {
    return simplifiedDefault;
  }

  const lane = edgeId ? hashString(edgeId) % 3 : 0;
  const laneOffset = lane * 6;
  const candidates: Array<{ points: Position[]; length: number }> = [];

  if (horizontal) {
    const leftToRight = x2 >= x1;
    const colliding = relevant.filter((obs) => (
      segmentIntersectsBox({ x: x1, y: y1 }, { x: defaultMid, y: y1 }, obs) ||
      segmentIntersectsBox({ x: defaultMid, y: y1 }, { x: defaultMid, y: y2 }, obs) ||
      segmentIntersectsBox({ x: defaultMid, y: y2 }, { x: x2, y: y2 }, obs)

    ));
    const obstacleGroup = colliding.length ? colliding : relevant;

    const firstObsLeft = leftToRight
      ? Math.min(...relevant.map((o) => o.left))
      : Math.max(...relevant.map((o) => o.right));
    const lastObsRight = leftToRight
      ? Math.max(...relevant.map((o) => o.right))
      : Math.min(...relevant.map((o) => o.left));

    const xTurn1 = leftToRight
      ? Math.round(firstObsLeft > x1 + 10 ? (x1 + firstObsLeft) / 2 : x1 + 16)
      : Math.round(firstObsLeft < x1 - 10 ? (x1 + firstObsLeft) / 2 : x1 - 16);
    const xTurn2 = leftToRight
      ? Math.round(lastObsRight < x2 - 10 ? (lastObsRight + x2) / 2 : x2 - 16)
      : Math.round(lastObsRight > x2 + 10 ? (lastObsRight + x2) / 2 : x2 + 16);

    const yAbove = Math.min(...obstacleGroup.map((o) => o.top)) - 14 - laneOffset;
    const yBelow = Math.max(...obstacleGroup.map((o) => o.bottom)) + 14 + laneOffset;
    const yLevels = [yAbove, yBelow];

    const sortedByTop = [...obstacleGroup].sort((a, b) => a.top - b.top);
    for (let i = 0; i < sortedByTop.length - 1; i++) {
      const gap = sortedByTop[i + 1].top - sortedByTop[i].bottom;
      if (gap >= 16) {
        yLevels.push(Math.round((sortedByTop[i].bottom + sortedByTop[i + 1].top) / 2));
      }
    }

    const directDrop = simplifyPoints([
      { x: x1, y: y1 },
      { x: xTurn1, y: y1 },
      { x: xTurn1, y: y2 },
      { x: x2, y: y2 },
    ]);
    if (!pathIntersectsObstacles(directDrop, relevant)) {
      candidates.push({ points: directDrop, length: Math.abs(x2 - x1) + Math.abs(y2 - y1) });
    }

    for (const yCorridor of yLevels) {
      const pts = simplifyPoints([
        { x: x1, y: y1 },
        { x: xTurn1, y: y1 },
        { x: xTurn1, y: yCorridor },
        { x: xTurn2, y: yCorridor },
        { x: xTurn2, y: y2 },
        { x: x2, y: y2 },
      ]);
      if (!pathIntersectsObstacles(pts, relevant)) {
        let len = 0;
        for (let i = 0; i < pts.length - 1; i++) {
          len += Math.hypot(pts[i + 1].x - pts[i].x, pts[i + 1].y - pts[i].y);
        }
        candidates.push({ points: pts, length: len });
      }
    }
  } else {
    const topToBottom = y2 >= y1;
    const colliding = relevant.filter((obs) => (
      segmentIntersectsBox({ x: x1, y: y1 }, { x: x1, y: defaultMid }, obs) ||
      segmentIntersectsBox({ x: x1, y: defaultMid }, { x: x2, y: defaultMid }, obs) ||
      segmentIntersectsBox({ x: x2, y: defaultMid }, { x: x2, y: y2 }, obs)
    ));
    const obstacleGroup = colliding.length ? colliding : relevant;

    const firstObsTop = topToBottom
      ? Math.min(...relevant.map((o) => o.top))
      : Math.max(...relevant.map((o) => o.bottom));
    const lastObsBottom = topToBottom
      ? Math.max(...relevant.map((o) => o.bottom))
      : Math.min(...relevant.map((o) => o.left));

    const yTurn1 = topToBottom
      ? Math.round(firstObsTop > y1 + 10 ? (y1 + firstObsTop) / 2 : y1 + 16)
      : Math.round(firstObsTop < y1 - 10 ? (y1 + firstObsTop) / 2 : y1 - 16);
    const yTurn2 = topToBottom
      ? Math.round(lastObsBottom < y2 - 10 ? (lastObsBottom + y2) / 2 : y2 - 16)
      : Math.round(lastObsBottom > y2 + 10 ? (lastObsBottom + y2) / 2 : y2 + 16);

    const xLeft = Math.min(...obstacleGroup.map((o) => o.left)) - 14 - laneOffset;
    const xRight = Math.max(...obstacleGroup.map((o) => o.right)) + 14 + laneOffset;
    const xLevels = [xLeft, xRight];

    const sortedByLeft = [...obstacleGroup].sort((a, b) => a.left - b.left);
    for (let i = 0; i < sortedByLeft.length - 1; i++) {
      const gap = sortedByLeft[i + 1].left - sortedByLeft[i].right;
      if (gap >= 16) {
        xLevels.push(Math.round((sortedByLeft[i].right + sortedByLeft[i + 1].left) / 2));
      }
    }

    const directShift = simplifyPoints([
      { x: x1, y: y1 },
      { x: x1, y: yTurn1 },
      { x: x2, y: yTurn1 },
      { x: x2, y: y2 },
    ]);
    if (!pathIntersectsObstacles(directShift, relevant)) {
      candidates.push({ points: directShift, length: Math.abs(x2 - x1) + Math.abs(y2 - y1) });
    }

    for (const xCorridor of xLevels) {
      const pts = simplifyPoints([
        { x: x1, y: y1 },
        { x: x1, y: yTurn1 },
        { x: xCorridor, y: yTurn1 },
        { x: xCorridor, y: yTurn2 },
        { x: x2, y: yTurn2 },
        { x: x2, y: y2 },
      ]);
      if (!pathIntersectsObstacles(pts, relevant)) {
        let len = 0;
        for (let i = 0; i < pts.length - 1; i++) {
          len += Math.hypot(pts[i + 1].x - pts[i].x, pts[i + 1].y - pts[i].y);
        }
        candidates.push({ points: pts, length: len });
      }
    }
  }

  if (candidates.length) {
    candidates.sort((a, b) => a.length - b.length);
    return candidates[0].points;
  }

  return simplifiedDefault;
}

export function connectorRoute(
  source: Position,
  sourceHeight: number,
  target: Position,
  targetHeight: number,
  sourceWidth = CARD_W,
  targetWidth = CARD_W,
  obstacles: ObstacleBox[] = [],
  edgeId = "",
) {
  const sourceCenter = { x: source.x + sourceWidth / 2, y: source.y + sourceHeight / 2 };
  const targetCenter = { x: target.x + targetWidth / 2, y: target.y + targetHeight / 2 };
  const dx = targetCenter.x - sourceCenter.x;
  const dy = targetCenter.y - sourceCenter.y;
  const horizontal = Math.abs(dx) / ((sourceWidth + targetWidth) / 2) >= Math.abs(dy) / ((sourceHeight + targetHeight) / 2);
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
    x1 = source.x + (leftToRight ? sourceWidth + 3 : -3);
    y1 = sourceCenter.y;
    x2 = target.x + (leftToRight ? -3 : targetWidth + 3);
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

  const points = routeObstacleFreePath(x1, y1, x2, y2, horizontal, obstacles, edgeId);
  return { sourceSide, targetSide, x1, y1, x2, y2, path: curvedOrthogonalPathFromPoints(points) };
}


function CanvasView({ graph, yoncConfig, selectedIds, onSelectionChange, onOpenSplit, onRegisterUndo }: {
  graph: GraphResponse;
  yoncConfig: YoncConfig | null;
  selectedIds: string[];
  onSelectionChange: (ids: string[]) => void;
  onOpenSplit: (node: GraphNode) => void;
  onRegisterUndo: (action: UndoAction) => void;
}) {
  const renderNodes = graph.nodes;
  const allowed = useMemo(() => new Set(renderNodes.map((node) => node.id)), [renderNodes]);
  const renderEdges = useMemo(() => graph.edges.filter((edge) => allowed.has(edge.source_id) && allowed.has(edge.target_id)), [graph.edges, allowed]);
  const nodeColors = useMemo(() => colorsForNodes(renderNodes, yoncConfig), [renderNodes, yoncConfig]);
  const nodeHeights = useMemo(() => Object.fromEntries(renderNodes.map((node) => [node.id, nodeCardHeight(node)])), [renderNodes]);
  const nodeWidths = useMemo(() => Object.fromEntries(renderNodes.map((node) => [node.id, nodeCardWidth(node)])), [renderNodes]);
  const elkPositions = useElkPositions(renderNodes, renderEdges);
  const canvasRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const minimapViewportRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef(new Map<string, HTMLElement>());
  const minimapNodeRefs = useRef(new Map<string, HTMLElement>());
  const edgeRefs = useRef(new Map<string, SVGPathElement>());
  const pan = useRef<{ pointerId: number; x: number; y: number; clientX: number; clientY: number; left: number; top: number; moved: boolean } | null>(null);
  const panFrame = useRef<number | null>(null);
  const viewportFrame = useRef<number | null>(null);
  const viewportSaveTimer = useRef<number | null>(null);
  const restoredViewport = useRef<null | { zoom: number; left: number; top: number }>(null);
  const restoringViewport = useRef(false);
  const latestViewport = useRef<null | { zoom: number; pan: { x: number; y: number } }>(null);
  const suppressNodeClick = useRef(false);
  const initialArrangePending = useRef(false);
  const initialFitDone = useRef(false);
  const fitAfterArrange = useRef(false);
  const manualZoomChosen = useRef(false);
  const [shiftHeld, setShiftHeld] = useState(false);
  const [zoom, setZoom] = useState(1);
  const zoomTarget = useRef(1);
  const pendingZoomAnchor = useRef<null | { left: number; top: number }>(null);
  const [manualPositions, setManualPositions] = useState<Record<string, Position>>({});
  const [viewStateLoaded, setViewStateLoaded] = useState(false);
  const nodeDrag = useRef<null | { ids: string[]; lockX: boolean; pointerId: number; startX: number; startY: number; bases: Record<string, Position>; dx: number; dy: number; moved: boolean; zoom: number; element: HTMLElement; positions: Record<string, Position>; edges: GraphEdge[]; width: number; height: number }>(null);
  const nodeDragFrame = useRef<number | null>(null);
  const marqueeDrag = useRef<null | { pointerId: number; startX: number; startY: number; currentX: number; currentY: number; baseIds: string[]; moved: boolean }>(null);
  const [marqueeBounds, setMarqueeBounds] = useState<SelectionBounds | null>(null);
  const today = new Date().toISOString().slice(0, 10);
  const scheduledDates = renderNodes.flatMap((node) => [node.planned_start, node.planned_end, node.deadline]).filter(Boolean) as string[];
  const { start: axisStart, end: axisEnd } = canvasTimeRange(new Date(`${today}T12:00:00`), scheduledDates);
  const minOffset = logarithmicDateOffset(axisStart, today);
  const maxOffset = logarithmicDateOffset(axisEnd, today);
  const todayX = CANVAS_TIME_START_PADDING - minOffset;
  const persistPositions = useCallback((next: Record<string, Position>) => {
    const encoded: Record<string, number> = { __layout_direction_version: CANVAS_LAYOUT_VERSION };
    for (const [id, position] of Object.entries(next)) { encoded[`${id}:x`] = position.x; encoded[`${id}:y`] = position.y; }
    return api.saveViewState("canvas", { vertical_layout: encoded });
  }, []);

  useEffect(() => {
    let cancelled = false;
    setViewStateLoaded(false);
    api.viewState("canvas").then((state) => {
      if (cancelled) return;
      const stored = (state.vertical_layout ?? {}) as Record<string, unknown>;
      const next: Record<string, Position> = {};
      for (const node of renderNodes) {
        const x = stored[`${node.id}:x`];
        const y = stored[`${node.id}:y`];
        if (typeof x === "number" && typeof y === "number") next[node.id] = { x, y };
      }
      if (stored.__layout_direction_version !== CANVAS_LAYOUT_VERSION) initialArrangePending.current = true;
      const savedZoom = typeof state.zoom === "number" ? Math.max(.05, Math.min(1.6, state.zoom)) : 1;
      const savedPan = (state.pan ?? {}) as Record<string, unknown>;
      const savedLeft = typeof savedPan.x === "number" ? Math.max(0, savedPan.x) : 0;
      const savedTop = typeof savedPan.y === "number" ? Math.max(0, savedPan.y) : 0;
      if (Math.abs(savedZoom - 1) > .0001 || savedLeft > .5 || savedTop > .5) {
        restoredViewport.current = { zoom: savedZoom, left: savedLeft, top: savedTop };
        restoringViewport.current = true;
        manualZoomChosen.current = true;
        zoomTarget.current = savedZoom;
        setZoom(savedZoom);
      }
      setManualPositions(next);
    }).catch(() => {
      if (!cancelled) {
        initialArrangePending.current = true;
        setManualPositions({});
      }
    }).finally(() => { if (!cancelled) setViewStateLoaded(true); });
    return () => { cancelled = true; };
  }, [persistPositions, renderNodes]);

  const desiredPositions = useMemo(() => Object.fromEntries(renderNodes.map((node, index) => {
    const scheduled = node.planned_start ?? node.deadline;
    const elk = elkPositions[node.id] ?? { x: (index % 7) * 188, y: Math.floor(index / 7) * 112 };
    return [node.id, { x: scheduled ? todayX + logarithmicDateOffset(scheduled, today) : 90 + elk.x, y: 82 + elk.y }];
  })), [renderNodes, elkPositions, today, todayX]);
  const automaticPositions = useMemo(() => arrangeCanvasPositions(desiredPositions, nodeHeights, nodeWidths), [desiredPositions, nodeHeights, nodeWidths]);
  const timelineAwareAutomaticPositions = useMemo(() => placeChildrenBeforeDatedParents(renderNodes, automaticPositions), [renderNodes, automaticPositions]);
  const familyAutomaticPositions = useMemo(() => arrangeCanvasFamilies(renderNodes, timelineAwareAutomaticPositions, nodeHeights, todayX), [renderNodes, timelineAwareAutomaticPositions, nodeHeights, todayX]);
  const basePositions = useMemo(() => Object.fromEntries(renderNodes.map((node) => [node.id, canvasPositionForNode(node, familyAutomaticPositions[node.id], manualPositions[node.id])])), [renderNodes, manualPositions, familyAutomaticPositions]);
  const positions = useMemo(() => placeChildrenBeforeDatedParents(renderNodes, basePositions), [renderNodes, basePositions]);
  const layoutReady = renderNodes.length === 0 || renderNodes.every((node) => Boolean(elkPositions[node.id]));

  const nodeBoxes = useMemo(() => {
    const boxes: ObstacleBox[] = [];
    for (const node of renderNodes) {
      const pos = positions[node.id];
      if (!pos) continue;
      boxes.push({
        id: node.id,
        left: pos.x,
        top: pos.y,
        right: pos.x + (nodeWidths[node.id] ?? CARD_W),
        bottom: pos.y + (nodeHeights[node.id] ?? COMPACT_CARD_H),
      });
    }
    return boxes;
  }, [renderNodes, positions, nodeWidths, nodeHeights]);


  const edgePaths = renderEdges.map((edge) => {
    const endpoints = canvasEdgeEndpoints(edge);
    const source = positions[endpoints.sourceId];
    const target = positions[endpoints.targetId];
    if (!source || !target) return null;
    const obstacles = nodeBoxes.filter((box) => box.id !== endpoints.sourceId && box.id !== endpoints.targetId);
    const route = connectorRoute(source, nodeHeights[endpoints.sourceId], target, nodeHeights[endpoints.targetId], nodeWidths[endpoints.sourceId], nodeWidths[endpoints.targetId], obstacles, edge.id);
    return <path ref={(element) => { if (element) edgeRefs.current.set(edge.id, element); else edgeRefs.current.delete(edge.id); }} key={edge.id} data-source={endpoints.sourceId} data-target={endpoints.targetId} data-source-side={route.sourceSide} data-target-side={route.targetSide} className={`edge edge-${edge.relation}`} d={route.path} markerEnd="url(#arrow)" />;
  });

  const height = Math.max(760, ...Object.entries(positions).map(([id, item]) => item.y + (nodeHeights[id] ?? COMPACT_CARD_H) + 120));
  const width = Math.max(1800, todayX + maxOffset + CANVAS_TIME_END_PADDING, ...Object.entries(positions).map(([id, item]) => item.x + (nodeWidths[id] ?? CARD_W) + CANVAS_TIME_END_PADDING));
  const paintNodeDrag = useCallback(() => {
    nodeDragFrame.current = null;
    const current = nodeDrag.current;
    if (!current) return;
    const livePositions = { ...current.positions };
    for (const id of current.ids) {
      const base = current.bases[id];
      if (!base) continue;
      const position = { x: base.x + (current.lockX ? 0 : current.dx), y: base.y + current.dy };
      livePositions[id] = position;
      const element = nodeRefs.current.get(id);
      if (element) element.style.transform = `translate(${position.x}px, ${position.y}px)`;
      const minimapNode = minimapNodeRefs.current.get(id);
      if (minimapNode) {
        minimapNode.style.left = `${Math.min(98, position.x / current.width * 100)}%`;
        minimapNode.style.top = `${Math.min(96, position.y / current.height * 100)}%`;
      }
    }
    const liveObstacles: ObstacleBox[] = [];
    for (const node of renderNodes) {
      const pos = livePositions[node.id];
      if (!pos) continue;
      liveObstacles.push({
        id: node.id,
        left: pos.x,
        top: pos.y,
        right: pos.x + (nodeWidths[node.id] ?? CARD_W),
        bottom: pos.y + (nodeHeights[node.id] ?? COMPACT_CARD_H),
      });
    }
    for (const edge of current.edges) {
      const endpoints = canvasEdgeEndpoints(edge);
      const source = livePositions[endpoints.sourceId];
      const target = livePositions[endpoints.targetId];
      const edgeElement = edgeRefs.current.get(edge.id);
      if (!source || !target || !edgeElement) continue;
      const obstacles = liveObstacles.filter((box) => box.id !== endpoints.sourceId && box.id !== endpoints.targetId);
      const route = connectorRoute(source, nodeHeights[endpoints.sourceId] ?? COMPACT_CARD_H, target, nodeHeights[endpoints.targetId] ?? COMPACT_CARD_H, nodeWidths[endpoints.sourceId] ?? CARD_W, nodeWidths[endpoints.targetId] ?? CARD_W, obstacles, edge.id);
      edgeElement.setAttribute("d", route.path);
      edgeElement.dataset.sourceSide = route.sourceSide;
      edgeElement.dataset.targetSide = route.targetSide;
    }
  }, [nodeHeights, nodeWidths, renderNodes]);

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
      for (const id of current.ids) nodeRefs.current.get(id)?.classList.remove("dragging");
      stageRef.current?.classList.remove("node-dragging");
      if (current.element.hasPointerCapture(current.pointerId)) current.element.releasePointerCapture(current.pointerId);
      if (!current.moved) {
        for (const id of current.ids) {
          const base = current.bases[id];
          const element = nodeRefs.current.get(id);
          if (base && element) element.style.transform = `translate(${base.x}px, ${base.y}px)`;
        }
        return;
      }
      suppressNodeClick.current = true;
      window.setTimeout(() => { suppressNodeClick.current = false; }, 80);
      setManualPositions((previous) => {
        const next = { ...previous };
        for (const id of current.ids) {
          const base = current.bases[id];
          if (base) next[id] = { x: base.x + (current.lockX ? 0 : current.dx), y: base.y + current.dy };
        }
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
  const scheduleViewportSave = () => {
    const canvas = canvasRef.current;
    if (!canvas || !viewStateLoaded || restoringViewport.current) return;
    latestViewport.current = { zoom: zoomTarget.current, pan: { x: canvas.scrollLeft, y: canvas.scrollTop } };
    if (viewportSaveTimer.current != null) window.clearTimeout(viewportSaveTimer.current);
    viewportSaveTimer.current = window.setTimeout(() => {
      viewportSaveTimer.current = null;
      const latest = latestViewport.current;
      if (latest) void api.saveViewState("canvas", latest).catch(() => undefined);
    }, 250);
  };
  useEffect(() => () => {
    if (panFrame.current != null) window.cancelAnimationFrame(panFrame.current);
    if (viewportFrame.current != null) window.cancelAnimationFrame(viewportFrame.current);
    if (viewportSaveTimer.current != null) window.clearTimeout(viewportSaveTimer.current);
    const latest = latestViewport.current;
    if (latest) void api.saveViewState("canvas", latest).catch(() => undefined);
  }, []);
  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const restored = restoredViewport.current;
    if (restored && viewStateLoaded && layoutReady && Math.abs(restored.zoom - zoom) < .0001) {
      canvas.scrollTo({ left: restored.left, top: restored.top });
      restoredViewport.current = null;
      window.requestAnimationFrame(() => { restoringViewport.current = false; });
    } else {
      const pending = pendingZoomAnchor.current;
      if (pending) {
        canvas.scrollTo(pending);
        pendingZoomAnchor.current = null;
      }
    }
    zoomTarget.current = zoom;
    updateViewport();
    scheduleViewportSave();
  }, [zoom, width, height, viewStateLoaded, layoutReady]);
  const horizontalFitZoom = () => {
    const canvas = canvasRef.current;
    if (!canvas) return .01;
    return Math.max(.01, Math.min(1, (canvas.clientWidth - 28) / width));
  };
  const setZoomAtPoint = (nextValue: number, clientX?: number, clientY?: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    manualZoomChosen.current = true;
    const next = Math.max(horizontalFitZoom(), Math.min(1.6, nextValue));
    const rect = canvas.getBoundingClientRect();
    const pointerInsideCanvas = clientX != null && clientY != null && clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom;
    const anchorX = pointerInsideCanvas ? clientX! - rect.left : canvas.clientWidth / 2;
    const anchorY = pointerInsideCanvas ? clientY! - rect.top : canvas.clientHeight / 2;
    if (Math.abs(next - zoom) < .0001) { pendingZoomAnchor.current = null; zoomTarget.current = next; return; }
    pendingZoomAnchor.current = anchoredScrollPosition(canvas.scrollLeft, canvas.scrollTop, anchorX, anchorY, zoom, next, CANVAS_AXIS_HEIGHT);
    zoomTarget.current = next;
    setZoom(next);
  };
  const setZoomAroundCenter = (nextValue: number) => setZoomAtPoint(nextValue);
  const fitAll = () => {
    const canvas = canvasRef.current;
    const bounds = canvasContentBounds(positions, nodeHeights, nodeWidths);
    if (!canvas || !bounds) return;
    const axisHeight = CANVAS_AXIS_HEIGHT;
    const contentWidth = Math.max(1, bounds.right - bounds.left);
    const contentHeight = Math.max(1, bounds.bottom - bounds.top);
    const availableHeight = Math.max(1, canvas.clientHeight - axisHeight);
    const next = Math.max(.05, Math.min(1, (canvas.clientWidth - 80) / contentWidth, (availableHeight - 80) / contentHeight));
    const target = {
      left: Math.max(0, ((bounds.left + bounds.right) / 2) * next - canvas.clientWidth / 2),
      top: Math.max(0, ((bounds.top + bounds.bottom) / 2) * next - availableHeight / 2),
    };
    pendingZoomAnchor.current = target;
    zoomTarget.current = next;
    if (Math.abs(next - zoom) < .0001) {
      pendingZoomAnchor.current = null;
      canvas.scrollTo(target);
      updateViewport();
    } else {
      setZoom(next);
    }
  };
  const autoArrangeAll = (shouldFit = true) => {
    if (!layoutReady) return;
    const arranged = arrangeCanvasFamilies(renderNodes, positions, nodeHeights, todayX);
    fitAfterArrange.current = shouldFit;
    setManualPositions(arranged);
    void persistPositions(arranged).catch(() => undefined);
  };
  useLayoutEffect(() => {
    if (!fitAfterArrange.current) return;
    fitAfterArrange.current = false;
    fitAll();
  }, [positions]);
  useEffect(() => {
    if (!viewStateLoaded || !layoutReady || initialFitDone.current) return;
    initialFitDone.current = true;
    if (initialArrangePending.current) {
      initialArrangePending.current = false;
      autoArrangeAll(!manualZoomChosen.current);
    } else if (!manualZoomChosen.current) {
      fitAll();
    }
  }, [viewStateLoaded, layoutReady, automaticPositions]);
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
  const pointInStage = (clientX: number, clientY: number) => {
    const rect = stageRef.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return { x: (clientX - rect.left) / zoom, y: (clientY - rect.top) / zoom };
  };
  const normalizedSelectionBounds = (startX: number, startY: number, currentX: number, currentY: number): SelectionBounds => ({
    left: Math.min(startX, currentX),
    top: Math.min(startY, currentY),
    right: Math.max(startX, currentX),
    bottom: Math.max(startY, currentY),
  });
  const selectionForBounds = (baseIds: string[], bounds: SelectionBounds) => [...new Set([...baseIds, ...nodesInSelectionBounds(positions, nodeHeights, bounds, nodeWidths)])];
  const moveCanvas = (event: React.PointerEvent<HTMLDivElement>) => {
    const selection = marqueeDrag.current;
    if (selection && event.pointerId === selection.pointerId) {
      const point = pointInStage(event.clientX, event.clientY);
      selection.currentX = point.x;
      selection.currentY = point.y;
      selection.moved ||= Math.abs(selection.currentX - selection.startX) + Math.abs(selection.currentY - selection.startY) > 3 / zoom;
      const bounds = normalizedSelectionBounds(selection.startX, selection.startY, selection.currentX, selection.currentY);
      setMarqueeBounds(bounds);
      if (selection.moved) onSelectionChange(selectionForBounds(selection.baseIds, bounds));
      return;
    }
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
    const selection = marqueeDrag.current;
    if (selection && event.pointerId === selection.pointerId) {
      if (cancelled) onSelectionChange(selection.baseIds);
      else if (selection.moved) {
        const bounds = normalizedSelectionBounds(selection.startX, selection.startY, selection.currentX, selection.currentY);
        onSelectionChange(selectionForBounds(selection.baseIds, bounds));
      }
      marqueeDrag.current = null;
      setMarqueeBounds(null);
      event.currentTarget.classList.remove("selecting");
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
      return;
    }
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
    if (!cancelled && !current.moved) onSelectionChange([]);
  };
  const beginCanvasMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || (event.target as HTMLElement).closest(".node-card")) return;
    if (event.shiftKey) {
      const point = pointInStage(event.clientX, event.clientY);
      marqueeDrag.current = { pointerId: event.pointerId, startX: point.x, startY: point.y, currentX: point.x, currentY: point.y, baseIds: selectedIds, moved: false };
      setMarqueeBounds(normalizedSelectionBounds(point.x, point.y, point.x, point.y));
      event.currentTarget.classList.add("selecting");
    } else {
      pan.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, clientX: event.clientX, clientY: event.clientY, left: event.currentTarget.scrollLeft, top: event.currentTarget.scrollTop, moved: false };
      event.currentTarget.classList.add("panning");
    }
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  useEffect(() => {
    const clearWithEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (selectedIds.length) onSelectionChange([]);
    };
    window.addEventListener("keydown", clearWithEscape);
    return () => window.removeEventListener("keydown", clearWithEscape);
  }, [selectedIds, onSelectionChange]);
  useEffect(() => {
    const updateShift = (event: KeyboardEvent) => {
      if (event.key === "Shift") setShiftHeld(event.type === "keydown");
    };
    const clearShift = () => setShiftHeld(false);
    window.addEventListener("keydown", updateShift);
    window.addEventListener("keyup", updateShift);
    window.addEventListener("blur", clearShift);
    return () => {
      window.removeEventListener("keydown", updateShift);
      window.removeEventListener("keyup", updateShift);
      window.removeEventListener("blur", clearShift);
    };
  }, []);
  return (
    <div className="canvas-view">
      <div ref={canvasRef} className={`canvas-scroll${shiftHeld ? " select-ready" : ""}`} onScroll={() => { updateViewport(); scheduleViewportSave(); }} onPointerDown={beginCanvasMove} onPointerMove={moveCanvas} onPointerUp={(event) => finishCanvasMove(event)} onPointerCancel={(event) => finishCanvasMove(event, true)}>
        <div className="canvas-zoom-space" style={{ width: width * zoom, height: height * zoom + CANVAS_AXIS_HEIGHT }}>
          <LogarithmicTimeAxis start={axisStart} end={axisEnd} anchor={today} todayX={todayX} zoom={zoom} height={height * zoom + CANVAS_AXIS_HEIGHT} />
          <div ref={stageRef} className="canvas-stage" style={{ width, height, transform: `scale(${zoom})` }}>
            <div className="today-line" style={{ left: todayX, height }} />
            <svg className="edge-layer" width={width} height={height} aria-hidden="true"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" /></marker></defs>{edgePaths}</svg>
            {marqueeBounds && <div className="selection-marquee" style={{ left: marqueeBounds.left, top: marqueeBounds.top, width: marqueeBounds.right - marqueeBounds.left, height: marqueeBounds.bottom - marqueeBounds.top }} aria-hidden="true" />}
            {renderNodes.map((node) => <NodeCard key={node.id} node={node} position={positions[node.id]} height={nodeHeights[node.id]} color={nodeColors[node.id]} selected={selectedIds.includes(node.id)} yoncConfig={yoncConfig} registerElement={(element) => { if (element) nodeRefs.current.set(node.id, element); else nodeRefs.current.delete(node.id); }} onSelect={() => { if (suppressNodeClick.current) { suppressNodeClick.current = false; return; } onSelectionChange([node.id]); }} onSplit={() => onOpenSplit(node)} onPointerDown={(event) => {
              if (event.button !== 0 || (event.target as HTMLElement).closest("button")) return;
              event.stopPropagation();
              const isSelected = selectedIds.includes(node.id);
              if (event.shiftKey) {
                suppressNodeClick.current = true;
                window.setTimeout(() => { suppressNodeClick.current = false; }, 80);
                onSelectionChange(isSelected ? selectedIds.filter((id) => id !== node.id) : [...selectedIds, node.id]);
                return;
              }
              const ids = isSelected && selectedIds.length > 1 ? selectedIds : canvasSubtreeIds(renderNodes, node.id);
              if (!isSelected || ids.length !== selectedIds.length || ids.some((id) => !selectedIds.includes(id))) onSelectionChange(ids);
              const bases = Object.fromEntries(ids.map((id) => [id, positions[id]]).filter((entry): entry is [string, Position] => Boolean(entry[1])));
              const lockX = ids.some((id) => { const item = renderNodes.find((candidate) => candidate.id === id); return Boolean(item?.planned_start || item?.deadline); });
              const draggedIds = new Set(ids);
              nodeDrag.current = { ids, lockX, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, bases, dx: 0, dy: 0, moved: false, zoom, element: event.currentTarget, positions, edges: renderEdges.filter((edge) => draggedIds.has(edge.source_id) || draggedIds.has(edge.target_id)), width, height };
              for (const id of ids) nodeRefs.current.get(id)?.classList.add("dragging");
              stageRef.current?.classList.add("node-dragging");
              event.currentTarget.setPointerCapture(event.pointerId);
            }} />)}
          </div>
        </div>
      </div>
      <div className="canvas-overlay-tools">
        <div className="canvas-zoom-controls"><button onClick={() => autoArrangeAll()} disabled={!layoutReady}>Auto Arrange</button><button onClick={() => setZoomAroundCenter(zoomTarget.current - .1)} aria-label="Zoom out">−</button><button onClick={() => setZoomAroundCenter(.75)}>75%</button><button onClick={() => setZoomAroundCenter(1)}>100%</button><button onClick={() => { manualZoomChosen.current = true; fitAll(); }}>Fit</button><button onClick={() => setZoomAroundCenter(zoomTarget.current + .1)} aria-label="Zoom in">+</button><span>{Math.round(zoom * 100)}%</span></div>
        <div className="canvas-controls"><button onClick={() => navigate(-1)}>← Quarter</button><button onClick={() => navigate(0)}>Today</button><button onClick={() => navigate(1)}>Quarter →</button></div>
      </div>
      <div className={`canvas-selection-status${selectedIds.length > 1 ? " active" : ""}`}>
        <span>{selectedIds.length > 1 ? `${selectedIds.length} selected · Drag any selected block to move all` : "Drag canvas to pan · Hold Shift to select multiple"}</span>
        {selectedIds.length > 0 && <button className="clear-selection" onClick={() => onSelectionChange([])}>Clear</button>}
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
  const [isEditingExecution, setIsEditingExecution] = useState(false);
  const [isEditingDeadline, setIsEditingDeadline] = useState(false);
  const [isEditingDescription, setIsEditingDescription] = useState(false);
  const [isConfirmingDone, setIsConfirmingDone] = useState(false);
  const [isConfirmingReopen, setIsConfirmingReopen] = useState(false);
  const [deadline, setDeadline] = useState(node?.deadline ?? "");
  const [startCue, setStartCue] = useState(node?.start_cue ?? "");
  const [doneWhen, setDoneWhen] = useState(node?.done_when ?? "");
  const [descriptionText, setDescriptionText] = useState(node?.description ?? "");

  const statusRowRef = useRef<HTMLDivElement | null>(null);
  const deadlineRowRef = useRef<HTMLDivElement | null>(null);
  const deadlineInputRef = useRef<HTMLInputElement | null>(null);
  const executionSectionRef = useRef<HTMLElement | null>(null);
  const startCueInputRef = useRef<HTMLTextAreaElement | null>(null);
  const descriptionSectionRef = useRef<HTMLElement | null>(null);
  const descriptionInputRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    setIsEditingExecution(false);
    setIsEditingDeadline(false);
    setIsEditingDescription(false);
    setIsConfirmingDone(false);
    setIsConfirmingReopen(false);
    setDeadline(node?.deadline ?? "");
    setStartCue(node?.start_cue ?? "");
    setDoneWhen(node?.done_when ?? "");
    setDescriptionText(node?.description ?? "");
  }, [node?.id]);

  if (!node) return null;

  const isAction = node.work_type === "ACTION" || (node.wbs_level ?? 0) >= 4;

  const performDone = async () => {
    try {
      const result = await api.transition(node.id, "done", graphVersion);
      onRegisterUndo({ kind: "batch", batchId: result.operation_batch_id });
      setIsConfirmingDone(false);
      await onRefresh();
    } catch (error) {
      onError(error);
    }
  };

  const performReopen = async () => {
    try {
      const result = await api.transition(node.id, "reopen", graphVersion);
      onRegisterUndo({ kind: "batch", batchId: result.operation_batch_id });
      setIsConfirmingReopen(false);
      await onRefresh();
    } catch (error) {
      onError(error);
    }
  };

  const saveDeadline = async () => {
    try {
      const result = await api.patchNode(node.id, { deadline: deadline.trim() || null }, graphVersion);
      onRegisterUndo({ kind: "batch", batchId: result.operation_batch_id });
      setIsEditingDeadline(false);
      await onRefresh();
    } catch (error) {
      onError(error);
    }
  };

  const saveDescription = async () => {
    try {
      const result = await api.patchNode(node.id, { description: descriptionText.trim() || null }, graphVersion);
      onRegisterUndo({ kind: "batch", batchId: result.operation_batch_id });
      setIsEditingDescription(false);
      await onRefresh();
    } catch (error) {
      onError(error);
    }
  };

  const saveExecution = async () => {
    try {
      const result = await api.patchNode(
        node.id,
        {
          start_cue: startCue.trim() || null,
          done_when: doneWhen.trim() || null,
        },
        graphVersion,
      );
      onRegisterUndo({ kind: "batch", batchId: result.operation_batch_id });
      setIsEditingExecution(false);
      await onRefresh();
    } catch (error) {
      onError(error);
    }
  };

  const scrollToExecution = () => {
    setIsEditingExecution(true);
    setStartCue(node.start_cue ?? "");
    setDoneWhen(node.done_when ?? "");
    setTimeout(() => {
      executionSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      startCueInputRef.current?.focus();
    }, 40);
  };

  const scrollToDeadline = () => {
    setIsEditingDeadline(true);
    setDeadline(node.deadline ?? "");
    setTimeout(() => {
      deadlineRowRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      deadlineInputRef.current?.focus();
    }, 40);
  };

  const scrollToDone = () => {
    setIsConfirmingDone(true);
    setIsConfirmingReopen(false);
    setTimeout(() => {
      statusRowRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 40);
  };

  const scrollToReopen = () => {
    setIsConfirmingReopen(true);
    setIsConfirmingDone(false);
    setTimeout(() => {
      statusRowRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 40);
  };

  const scrollToDescription = () => {
    setIsEditingDescription(true);
    setDescriptionText(node.description ?? "");
    setTimeout(() => {
      descriptionSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      descriptionInputRef.current?.focus();
    }, 40);
  };

  return (
    <aside className="inspector floating-inspector">
      <button className="inspector-close" onClick={onClose} aria-label="关闭详情">×</button>
      <div className="inspector-heading"><span className="status-dot" style={{ background: color }} /><div><span className="eyebrow">{node.work_type.replace("_", " ")} · {node.stage}</span><h2>{node.title}</h2></div></div>
      <div className="detail-grid">
        <span>Status</span>
        <div ref={statusRowRef} className="status-cell-wrap">
          {node.status === "DONE" ? (
            <b
              className="editable-cell hover-edit-trigger status-done-clickable"
              onClick={scrollToReopen}
              title="已完成 · 点击撤销完成"
              role="button"
              tabIndex={0}
              onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") scrollToReopen(); }}
            >
              {node.status} <span className="edit-icon" aria-hidden="true">↺</span>
            </b>
          ) : (
            <b>{node.status}</b>
          )}
          {isConfirmingDone && (
            <div className="inline-confirm-box">
              <span>确认标记为完成？</span>
              <div className="inline-actions">
                <button type="button" className="btn-sm" onClick={() => setIsConfirmingDone(false)}>取消</button>
                <button type="button" className="btn-sm primary" onClick={performDone}>确认完成</button>
              </div>
            </div>
          )}
          {isConfirmingReopen && (
            <div className="inline-confirm-box">
              <span>确认撤销完成？</span>
              <div className="inline-actions">
                <button type="button" className="btn-sm" onClick={() => setIsConfirmingReopen(false)}>取消</button>
                <button type="button" className="btn-sm primary" onClick={performReopen}>确认恢复</button>
              </div>
            </div>
          )}
        </div>
        <span>Progress</span><b>{Math.round((node.progress?.ratio ?? 0) * 100)}%</b>
        <span>Estimated Effort</span><b>{formatEffort(node.estimated_effort_minutes)}</b>
        <span>Planned Span</span><b>{node.planned_start ? `${fmtDate(node.planned_start)} – ${fmtDate(node.planned_end ?? node.planned_start)}` : "Unscheduled"}</b>
        <span>Deadline</span>
        <div ref={deadlineRowRef} className="deadline-cell-wrap">
          {isEditingDeadline ? (
            <div className="inline-edit-field">
              <input
                ref={deadlineInputRef}
                type="date"
                value={deadline}
                onChange={(event) => setDeadline(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") saveDeadline();
                  if (event.key === "Escape") setIsEditingDeadline(false);
                }}
              />
              <div className="inline-actions">
                <button type="button" className="btn-sm" onClick={() => setIsEditingDeadline(false)}>✕</button>
                <button type="button" className="btn-sm primary" onClick={saveDeadline}>保存</button>
              </div>
            </div>
          ) : (
            <b
              className="editable-cell hover-edit-trigger"
              onClick={scrollToDeadline}
              title="点击修改截止日期"
              role="button"
              tabIndex={0}
              onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") scrollToDeadline(); }}
            >
              {fmtDate(node.deadline)} <span className="edit-icon" aria-hidden="true">✎</span>
            </b>
          )}
        </div>
        <span>Pressure</span><b className={`pressure-text ${node.pressure?.level}`}>{node.pressure?.level ?? "low"}</b>
      </div>
      <div className="meter"><i style={{ width: `${Math.round((node.progress?.ratio ?? 0) * 100)}%` }} /></div>
      {node.health?.length > 0 && (
        <section className="health-warnings" aria-label="Warnings">
          <div className="section-heading"><h3>Warnings</h3><span>{node.health.length}</span></div>
          <ul>
            {node.health.map((warning, index) => {
              const isExecutionWarning = warning.code === "ACTIONABILITY_INCOMPLETE";
              return (
                <li
                  key={`${warning.code}-${index}`}
                  className={isExecutionWarning ? "warning-actionable" : ""}
                  onClick={isExecutionWarning ? scrollToExecution : undefined}
                  role={isExecutionWarning ? "button" : undefined}
                  tabIndex={isExecutionWarning ? 0 : undefined}
                  onKeyDown={isExecutionWarning ? (event) => { if (event.key === "Enter" || event.key === " ") scrollToExecution(); } : undefined}
                >
                  <span aria-hidden="true">△</span>
                  <p>
                    {healthWarningMessage(warning, node)}
                    {isExecutionWarning && <span className="inline-fix-link"> 完善定义 →</span>}
                  </p>
                </li>
              );
            })}
          </ul>
        </section>
      )}
      <section ref={descriptionSectionRef} className={`inspector-section hover-edit-trigger${isEditingDescription ? " is-editing" : ""}`}>
        <div className="section-heading">
          <h3>Description</h3>
          {!isEditingDescription ? (
            <button
              type="button"
              className="icon-action-btn"
              onClick={scrollToDescription}
              title="编辑描述"
              aria-label="编辑描述"
            >
              <span className="edit-icon" aria-hidden="true">✎</span>
            </button>
          ) : (
            <button type="button" className="link-action" onClick={() => setIsEditingDescription(false)}>Cancel</button>
          )}
        </div>
        {isEditingDescription ? (
          <div className="description-edit-box">
            <textarea
              ref={descriptionInputRef}
              rows={3}
              value={descriptionText}
              onChange={(event) => setDescriptionText(event.target.value)}
              placeholder="输入任务描述..."
            />
            <div className="inline-actions">
              <button type="button" className="btn-sm" onClick={() => setIsEditingDescription(false)}>取消</button>
              <button type="button" className="btn-sm primary" onClick={saveDescription}>保存</button>
            </div>
          </div>
        ) : (
          <p
            className="editable-text-block"
            onClick={scrollToDescription}
            title="点击编辑描述"
            role="button"
            tabIndex={0}
            onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") scrollToDescription(); }}
          >
            {node.description || "No description yet."}
          </p>
        )}
      </section>
      <section ref={executionSectionRef} className={`execution-section hover-edit-trigger${isEditingExecution ? " is-editing" : ""}`}>
        <div className="section-heading">
          <h3>Execution definition</h3>
          {!isEditingExecution ? (
            <button
              type="button"
              className="icon-action-btn"
              onClick={scrollToExecution}
              title="编辑执行定义"
              aria-label="编辑执行定义"
            >
              <span className="edit-icon" aria-hidden="true">✎</span>
            </button>
          ) : (
            <button type="button" className="link-action" onClick={() => setIsEditingExecution(false)}>Cancel</button>
          )}
        </div>
        {isEditingExecution ? (
          <div className="execution-edit-box">
            <label className="field">
              <span>Start cue (trigger / first step)</span>
              <textarea
                ref={startCueInputRef}
                rows={2}
                value={startCue}
                onChange={(event) => setStartCue(event.target.value)}
                placeholder="例如：准备好器件清单并打开焊台 / 拉取最新代码"
              />
            </label>
            <label className="field">
              <span>Done when (observable completion criteria)</span>
              <textarea
                rows={2}
                value={doneWhen}
                onChange={(event) => setDoneWhen(event.target.value)}
                placeholder="例如：所有模块通过自检测试并输出报告"
              />
            </label>
            <div className="inline-actions">
              <button type="button" className="btn-sm" onClick={() => setIsEditingExecution(false)}>取消</button>
              <button type="button" className="btn-sm primary" onClick={saveExecution}>保存定义</button>
            </div>
          </div>
        ) : (
          <div
            className="editable-text-block"
            onClick={scrollToExecution}
            title="点击编辑执行定义"
            role="button"
            tabIndex={0}
            onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") scrollToExecution(); }}
          >
            <p><small>Start</small>{node.start_cue || "—"}</p>
            <p><small>Done when</small>{node.done_when || "—"}</p>
          </div>
        )}
      </section>
      <section><h3>Forecast</h3>{node.forecast?.finish_range ? <p>{fmtDate(node.forecast.finish_range.earliest)} – {fmtDate(node.forecast.finish_range.latest)} <small>{node.forecast.confidence} confidence</small></p> : <p>Insufficient completed history for a finish range.</p>}</section>
      <section><h3>References</h3><p>{node.resource_count} linked resources</p></section>
      <div className="inspector-actions">
        {!isAction ? (
          <button className="primary" onClick={() => onOpenSplit(node)}>Open Split</button>
        ) : (
          <button className={!node.start_cue || !node.done_when ? "primary" : ""} onClick={scrollToExecution}>Edit Execution</button>
        )}
        {node.status !== "DONE" ? (
          <button className={isAction && node.start_cue && node.done_when ? "primary" : ""} onClick={scrollToDone}>Mark Done</button>
        ) : (
          <button onClick={scrollToReopen}>Undo Done</button>
        )}
      </div>
    </aside>
  );
}

function TimelineGrid({ timeline, graph, yoncConfig, selectedId, calendarRef, onSelect, onRefresh, onError, onRegisterUndo }: {
  timeline: TimelineResponse;
  graph: GraphResponse;
  yoncConfig: YoncConfig | null;
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
  const nodeColors = useMemo(() => colorsForNodes(graph.nodes, yoncConfig), [graph.nodes, yoncConfig]);
  const unscheduled = graph.nodes.filter((node) => !node.planned_start && timelineWorkTypes.has(node.work_type));
  const scheduledModules = graph.nodes.filter((node) => node.planned_start && timelineWorkTypes.has(node.work_type)).sort((a, b) => (a.planned_start ?? "").localeCompare(b.planned_start ?? ""));
  const [searchQuery, setSearchQuery] = useState("");
  const [poolFilter, setPoolFilter] = useState<TimelinePoolFilter>("all");
  const [rangeNode, setRangeNode] = useState<GraphNode | null>(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [rangeDeadline, setRangeDeadline] = useState("");
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
    const newStart = cell.date;
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
  const openRange = (node: GraphNode) => {
    setRangeNode(node);
    setStart(node.planned_start ?? "");
    setEnd(node.planned_end ?? node.planned_start ?? "");
    setRangeDeadline(node.deadline ?? "");
    onSelect(node.id);
  };
  const normalizedSearch = searchQuery.trim();
  const poolNodes = useMemo(() => {
    const candidates = normalizedSearch ? graph.nodes : unscheduled;
    return timelinePoolMatches(candidates, normalizedSearch, poolFilter);
  }, [graph.nodes, normalizedSearch, poolFilter]);
  const choosePoolNode = (node: GraphNode) => {
    if (node.planned_start) {
      openRange(node);
      window.requestAnimationFrame(() => {
        const cell = calendarRef.current?.querySelector<HTMLElement>(`[data-date="${node.planned_start}"]`);
        if (cell && calendarRef.current) calendarRef.current.scrollTo({ left: Math.max(0, cell.offsetLeft - calendarRef.current.clientWidth / 2 + cell.clientWidth / 2), behavior: "smooth" });
      });
    } else onSelect(node.id);
  };
  const saveRange = async () => {
    if (!rangeNode || !start || !end) return;
    try {
      const scheduled = await api.schedule(rangeNode.id, start, end, graph.graph_version);
      if (scheduled.operation_batch_id) onRegisterUndo({ kind: "batch", batchId: scheduled.operation_batch_id });
      let nextVersion = scheduled.graph_version;
      const targetDeadline = rangeDeadline.trim() || null;
      if (targetDeadline !== (rangeNode.deadline ?? null)) {
        const patched = await api.patchNode(rangeNode.id, { deadline: targetDeadline }, nextVersion);
        if (patched.operation_batch_id) onRegisterUndo({ kind: "batch", batchId: patched.operation_batch_id });
      }
      setRangeNode(null);
      await onRefresh();
    } catch (error) {
      onError(error);
    }
  };
  return (
    <div className="timeline-layout">
      <aside className="module-pool">
        <div className="module-pool-head">
          <span className="eyebrow">Unscheduled modules</span><h2>Module pool</h2>
          <div className="module-search">
            <span aria-hidden="true">⌕</span>
            <input type="search" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && poolNodes[0]) choosePoolNode(poolNodes[0]); }} placeholder="Search all job & task titles…" aria-label="Search all job and task titles" />
            {searchQuery && <button type="button" onClick={() => setSearchQuery("")} aria-label="Clear search">×</button>}
          </div>
          <div className="module-search-filters" aria-label="Filter search results">
            {(["all", "jobs", "tasks"] as TimelinePoolFilter[]).map((filter) => <button key={filter} type="button" className={poolFilter === filter ? "active" : ""} aria-pressed={poolFilter === filter} onClick={() => setPoolFilter(filter)}>{filter[0].toUpperCase() + filter.slice(1)}</button>)}
          </div>
          <p className="module-result-count" aria-live="polite">{normalizedSearch ? `${poolNodes.length} result${poolNodes.length === 1 ? "" : "s"} across the timeline` : `${poolNodes.length} unscheduled ${poolNodes.length === 1 ? "item" : "items"}`}</p>
        </div>
        <div className="module-pool-list">
          {poolNodes.length ? poolNodes.map((node) => <article key={node.id} className={`${draggedNodeId === node.id || pendingPlacement?.nodeId === node.id ? "dragging " : ""}${selectedId === node.id ? "selected" : ""}`} draggable aria-label={`Drag ${node.title} to a date`} onDragStart={(event) => beginModuleDrag(event, node.id)} onDragEnd={clearModuleDrag} onClick={() => choosePoolNode(node)}><i style={{ background: nodeColors[node.id] }} /><div><b>{node.title}</b><small>{node.work_type.replace("_", " ")} · {node.planned_start ? fmtDate(node.planned_start) : "Unscheduled"} · {formatEffort(node.estimated_effort_minutes)}</small></div><span>›</span></article>) : <p className="quiet">{normalizedSearch ? `No titles match “${normalizedSearch}”.` : poolFilter === "all" ? "Everything in this project file has a start date." : `No unscheduled ${poolFilter}.`}</p>}
        </div>
      </aside>
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
      {rangeNode && <aside className="range-inspector floating-range"><button className="inspector-close" onClick={() => setRangeNode(null)} aria-label="关闭范围详情">×</button><span className="eyebrow">Selected range</span><h2>{rangeNode.title}</h2><label className="field">Start<input type="date" value={start} onChange={(event) => setStart(event.target.value)} /></label><label className="field">End<input type="date" value={end} onChange={(event) => setEnd(event.target.value)} /></label><label className="field">Deadline<input type="date" value={rangeDeadline} onChange={(event) => setRangeDeadline(event.target.value)} /></label><p className="quiet">Moving or resizing changes planned dates, never estimated effort.</p><button className="primary" onClick={saveRange}>Apply Range</button><hr /><span className="eyebrow">Weekly capacity</span><p>{timeline.warnings.length ? `${timeline.warnings.length} overlap warning${timeline.warnings.length === 1 ? "" : "s"}` : "No overloaded cells in this range."}</p></aside>}
    </div>
  );
}

function ForecastView({ graph, yoncConfig }: { graph: GraphResponse; yoncConfig: YoncConfig | null }) {
  const projects = graph.nodes.filter((node) => ["GOAL", "DELIVERABLE"].includes(node.work_type)).slice(0, 12);
  const nodeColors = useMemo(() => colorsForNodes(graph.nodes, yoncConfig), [graph.nodes, yoncConfig]);
  const max = Math.max(1, ...Object.values(graph.pace.weeks));
  return (
    <div className="forecast-view">
      <section className="forecast-hero"><span className="eyebrow">Observed delivery pace</span><h2>{graph.pace.reliable ? `${graph.pace.median_hours?.toFixed(1)}h / week` : "Building a baseline"}</h2><p>{graph.pace.reliable ? `Based on ${graph.pace.completion_count} valid Done transitions across the last eight completed ISO weeks.` : "At least three completed Actions across two separate weeks are needed before showing a finish date."}</p><div className="pace-bars">{Object.entries(graph.pace.weeks).map(([week, value]) => <div key={week}><i style={{ height: `${Math.max(4, value / max * 100)}%` }} /><span>{week.slice(5)}</span></div>)}</div></section>
      <section className="forecast-list"><span className="eyebrow">Project forecasts</span>{projects.map((node) => <article key={node.id}><div><i style={{ background: nodeColors[node.id] }} /><h3>{node.title}</h3><span>{node.work_type}</span></div><dl><div><dt>Remaining</dt><dd>{node.forecast?.remaining_effort_hours?.toFixed(1) ?? "—"}h</dd></div><div><dt>Likely finish</dt><dd>{fmtDate(node.forecast?.finish_range?.likely)}</dd></div><div><dt>Deadline</dt><dd>{fmtDate(node.deadline)}</dd></div><div><dt>Gap</dt><dd>{node.forecast?.gap_days == null ? "—" : `${node.forecast.gap_days}d`}</dd></div></dl></article>)}</section>
    </div>
  );
}

function TimelineView({ timeline, graph, yoncConfig, selectedId, mode, onMode, onSelect, onRefresh, onError, onRegisterUndo }: {
  timeline: TimelineResponse;
  graph: GraphResponse;
  yoncConfig: YoncConfig | null;
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
  return <div className="timeline-view"><header className="timeline-toolbar"><div className="segmented"><button className={mode === "forecast" ? "active" : ""} onClick={() => onMode("forecast")}>Forecast</button><button className={mode === "capacity" ? "active" : ""} onClick={() => onMode("capacity")}>Capacity Grid</button></div>{mode === "capacity" && <div className="date-navigation"><button onClick={() => navigate(-1)}>← Quarter</button><button onClick={() => navigate(0)}>Today</button><button onClick={() => navigate(1)}>Quarter →</button></div>}</header>{mode === "forecast" ? <ForecastView graph={graph} yoncConfig={yoncConfig} /> : <TimelineGrid timeline={timeline} graph={graph} yoncConfig={yoncConfig} selectedId={selectedId} calendarRef={calendarRef} onSelect={onSelect} onRefresh={onRefresh} onError={onError} onRegisterUndo={onRegisterUndo} />}</div>;
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
  const [pendingAnnotations, setPendingAnnotations] = useState<SplitAnnotation[]>([]);
  const [selectionPopup, setSelectionPopup] = useState<{
    target_temporary_id: string;
    field: "title" | "done_when";
    highlighted_text: string;
    x: number;
    y: number;
  } | null>(null);
  const [activeComposer, setActiveComposer] = useState<{
    target_temporary_id: string;
    field: "title" | "done_when";
    highlighted_text: string;
  } | null>(null);
  const [composerComment, setComposerComment] = useState("");
  const [busy, setBusy] = useState(false);

  const reload = async () => setCurrent(await api.split(current.id));

  const handleProposalSelection = () => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) {
      setSelectionPopup(null);
      return;
    }
    const text = selection.toString().trim();
    if (!text || text.length > 200) {
      setSelectionPopup(null);
      return;
    }
    const anchorNode = selection.anchorNode;
    const parentEl = anchorNode instanceof HTMLElement ? anchorNode : anchorNode?.parentElement;
    const fieldEl = parentEl?.closest("[data-field]") as HTMLElement | null;
    const cardEl = parentEl?.closest("[data-temp-id]") as HTMLElement | null;
    if (!fieldEl || !cardEl) {
      setSelectionPopup(null);
      return;
    }
    const targetId = cardEl.getAttribute("data-temp-id") || "";
    const field = (fieldEl.getAttribute("data-field") || "title") as "title" | "done_when";
    if (!targetId) {
      setSelectionPopup(null);
      return;
    }
    const range = selection.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    setSelectionPopup({
      target_temporary_id: targetId,
      field,
      highlighted_text: text,
      x: rect.left + rect.width / 2,
      y: rect.top - 10,
    });
  };

  const openComposer = () => {
    if (!selectionPopup) return;
    setActiveComposer({
      target_temporary_id: selectionPopup.target_temporary_id,
      field: selectionPopup.field,
      highlighted_text: selectionPopup.highlighted_text,
    });
    setComposerComment("");
    setSelectionPopup(null);
    window.getSelection()?.removeAllRanges();
  };

  const addAnnotation = () => {
    if (!activeComposer || !composerComment.trim()) return;
    setPendingAnnotations((prev) => [
      ...prev,
      {
        target_temporary_id: activeComposer.target_temporary_id,
        field: activeComposer.field,
        highlighted_text: activeComposer.highlighted_text,
        comment: composerComment.trim(),
      },
    ]);
    setActiveComposer(null);
    setComposerComment("");
  };

  const removeAnnotation = (index: number) => {
    setPendingAnnotations((prev) => prev.filter((_, i) => i !== index));
  };

  const send = async () => {
    if (!message.trim() && pendingAnnotations.length === 0) return;
    setBusy(true);
    try {
      await api.splitMessage(current.id, message, pendingAnnotations);
      setMessage("");
      setPendingAnnotations([]);
      await reload();
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  };

  const validate = async () => {
    setBusy(true);
    try {
      const result = await api.validateSplit(current.id);
      window.alert(result.valid ? "提案已通过可执行性与项目图检查。" : "提案尚未通过检查，请继续调整。");
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    if (!window.confirm("确认提交拆分？提交后将创建正式节点和关系。")) return;
    setBusy(true);
    try {
      const result = await api.commitSplit(current.id, graphVersion, current.current_proposal_version);
      onRegisterUndo({ kind: "batch", batchId: result.operation_batch.id });
      await onRefresh();
      onClose();
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  };

  const discard = async () => {
    if (!window.confirm("放弃当前拆分提案？未提交的内容不会写入项目图。")) return;
    try {
      await api.discardSplit(current.id);
      onClose();
    } catch (error) {
      onError(error);
    }
  };

  return (
    <aside className="split-panel" role="dialog" aria-modal="true" aria-label="拆分会话">
      <header><div><span className="eyebrow">拆分会话</span><h2>协作拆分</h2></div><button className="icon-button" onClick={onClose} aria-label="关闭拆分会话">×</button></header>
      <div className="split-context"><span>当前状态</span><b>{current.state}</b><span>提案版本</span><b>v{current.current_proposal_version}</b></div>
      <div className="conversation">
        {current.messages.map((item) => (
          <div key={item.id} className={`message ${item.role}`}>
            <small>{item.role === "user" ? "你" : item.role === "assistant" ? "拆分助手" : "系统"}</small>
            <p>{item.content}</p>
            {item.annotations && item.annotations.length > 0 && (
              <div className="message-annotations">
                <span className="message-annotations-title">划词批注：</span>
                {item.annotations.map((ann, idx) => (
                  <div key={idx} className="message-annotation-item">
                    <span className="quote">“{ann.highlighted_text}”</span>
                    <span className="arrow">→</span>
                    <span className="comment">{ann.comment}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <section className="proposal-tree" onMouseUp={handleProposalSelection}>
        <header>
          <h3>当前提案 v{current.proposal?.version ?? 0}</h3>
          <span>{pendingAnnotations.length > 0 ? `${pendingAnnotations.length} 处待提交批注` : "尚未写入项目图"}</span>
        </header>
        {current.proposal?.nodes.map((node, index) => {
          const nodeAnnotations = pendingAnnotations.filter((a) => a.target_temporary_id === node.temporary_id);
          const isComposingThis = activeComposer?.target_temporary_id === node.temporary_id;
          return (
            <article key={node.temporary_id} data-temp-id={node.temporary_id} className={nodeAnnotations.length > 0 ? "has-annotations" : ""}>
              <i>{index + 1}</i>
              <div>
                <b data-field="title" title="划词选中文字可直接批注">{node.title}</b>
                <p data-field="done_when" title="划词选中文字可直接批注">{node.done_when}</p>
                <small>{node.estimated_effort_minutes} 分钟 · {node.required ? "必需" : "可选"}</small>
                {nodeAnnotations.length > 0 && (
                  <div className="node-annotations-list">
                    {nodeAnnotations.map((ann, aIdx) => (
                      <div key={aIdx} className="annotation-chip">
                        <span className="annotation-chip-quote">“{ann.highlighted_text}”</span>
                        <span className="annotation-chip-comment">{ann.comment}</span>
                        <button type="button" className="annotation-chip-remove" onClick={() => removeAnnotation(pendingAnnotations.indexOf(ann))} title="删除批注">×</button>
                      </div>
                    ))}
                  </div>
                )}
                {isComposingThis && (
                  <div className="inline-annotation-composer">
                    <div className="composer-header">
                      <span>对 <b>“{activeComposer.highlighted_text}”</b> 批注：</span>
                    </div>
                    <input
                      autoFocus
                      value={composerComment}
                      onChange={(e) => setComposerComment(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") { e.preventDefault(); addAnnotation(); }
                        if (e.key === "Escape") setActiveComposer(null);
                      }}
                      placeholder="例如：拆分成两个独立任务、补充完成判定..."
                    />
                    <div className="composer-actions">
                      <button type="button" className="composer-cancel" onClick={() => setActiveComposer(null)}>取消</button>
                      <button type="button" className="composer-submit" disabled={!composerComment.trim()} onClick={addAnnotation}>添加批注</button>
                    </div>
                  </div>
                )}
              </div>
              <span className="proposal-status-check">✓</span>
            </article>
          );
        }) ?? <p className="quiet">告诉我你希望如何拆分，或让我先提出一个版本。</p>}
      </section>
      {selectionPopup && (
        <div
          className="selection-popover"
          style={{ left: selectionPopup.x, top: selectionPopup.y }}
          onMouseDown={(e) => {
            e.preventDefault();
            openComposer();
          }}
        >
          <button type="button" className="popover-comment-btn">💬 批注此词</button>
        </div>
      )}
      <div className="split-compose">
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder={pendingAnnotations.length > 0 ? "已添加划词批注，可直接提交或在此输入补充说明..." : "例如：合并第 1、2 项，把最后一项拆得更具体……（也可在上方划词直接批注）"}
        />
        <button className="primary" disabled={busy || (!message.trim() && pendingAnnotations.length === 0)} onClick={send}>
          {pendingAnnotations.length > 0 ? `发送并按 ${pendingAnnotations.length} 处批注生成新版本` : "发送并生成新版本"}
        </button>
      </div>
      <footer>
        <button onClick={discard}>放弃提案</button>
        <button onClick={validate} disabled={!current.proposal || busy}>检查提案</button>
        <button className="primary" onClick={commit} disabled={!current.proposal || busy}>提交拆分</button>
      </footer>
    </aside>
  );
}

type ConfigTab = "themes" | "modes" | "task_types";

function SettingsPanel({ config, onClose, onSaved, onError }: {
  config: YoncConfig;
  onClose: () => void;
  onSaved: (config: YoncConfig) => void;
  onError: (error: unknown) => void;
}) {
  const [draft, setDraft] = useState<YoncConfig>(() => structuredClone(config));
  const [tab, setTab] = useState<ConfigTab>("themes");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const updateTheme = (index: number, values: Partial<YoncConfig["themes"][number]>) => setDraft((current) => ({ ...current, themes: current.themes.map((item, itemIndex) => itemIndex === index ? { ...item, ...values } : item) }));
  const updateMode = (index: number, values: Partial<YoncConfig["modes"][number]>) => setDraft((current) => ({ ...current, modes: current.modes.map((item, itemIndex) => itemIndex === index ? { ...item, ...values } : item) }));
  const updateTaskType = (index: number, values: Partial<YoncConfig["task_types"][number]>) => setDraft((current) => ({ ...current, task_types: current.task_types.map((item, itemIndex) => itemIndex === index ? { ...item, ...values } : item) }));
  const save = async () => {
    const normalized: YoncConfig = {
      ...draft,
      themes: draft.themes.map((item) => ({ ...item, name: item.name.trim(), sub_themes: item.sub_themes.map((value) => value.trim()).filter(Boolean) })),
      modes: draft.modes.map((item) => ({ ...item, mode_name: item.mode_name.trim(), description: item.description.trim() })),
      task_types: draft.task_types.map((item) => ({ ...item, emoji: item.emoji.trim(), name: item.name.trim(), description: item.description.trim(), tag: item.tag.trim() })),
    };
    if (normalized.themes.some((item) => !item.name) || normalized.modes.some((item) => !item.mode_name) || normalized.task_types.some((item) => !item.name)) {
      setNotice("名称不能为空。");
      return;
    }
    setSaving(true);
    setNotice("");
    try {
      const saved = await api.saveYoncConfig(normalized);
      setDraft(structuredClone(saved));
      onSaved(saved);
      setNotice("已保存到 project_graph.sqlite3");
    } catch (error) { onError(error); } finally { setSaving(false); }
  };
  return (
    <div className="modal-backdrop settings-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="settings-panel" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <header><div><span className="eyebrow">project_graph.sqlite3</span><h2 id="settings-title">Yonc Configuration</h2></div><button className="icon-button" onClick={onClose} aria-label="关闭设置">×</button></header>
        <div className="settings-tabs" role="tablist">
          <button className={tab === "themes" ? "active" : ""} onClick={() => setTab("themes")}>Task Themes <span>{draft.themes.length}</span></button>
          <button className={tab === "modes" ? "active" : ""} onClick={() => setTab("modes")}>Modes <span>{draft.modes.length}</span></button>
          <button className={tab === "task_types" ? "active" : ""} onClick={() => setTab("task_types")}>Task Types <span>{draft.task_types.length}</span></button>
        </div>
        <div className="settings-content">
          {tab === "themes" && <>
            <div className="settings-section-heading"><div><h3>Task Theme with colour</h3><p>Theme colors are used immediately across Canvas, Timeline, and Forecast.</p></div><button onClick={() => setDraft((current) => ({ ...current, themes: [...current.themes, { name: "New Theme", sub_themes: [], color: "#64748b" }] }))}>＋ Add Theme</button></div>
            <div className="config-list">{draft.themes.map((theme, index) => <article className="config-row theme-row" key={`${index}-${theme.name}`}>
              <label className="color-field" title="Theme color"><input type="color" value={theme.color} onChange={(event) => updateTheme(index, { color: event.target.value })} /><span style={{ background: theme.color }} /></label>
              <label><span>Name</span><input value={theme.name} onChange={(event) => updateTheme(index, { name: event.target.value })} /></label>
              <label className="wide"><span>Sub-themes, separated by |</span><input value={theme.sub_themes.join(" | ")} onChange={(event) => updateTheme(index, { sub_themes: event.target.value.split("|") })} /></label>
              <button className="remove-config" onClick={() => setDraft((current) => ({ ...current, themes: current.themes.filter((_, itemIndex) => itemIndex !== index) }))} aria-label={`Remove ${theme.name}`}>×</button>
            </article>)}</div>
          </>}
          {tab === "modes" && <>
            <div className="settings-section-heading"><div><h3>Modes</h3><p>Edit energy level, display badge, color, and guidance.</p></div><button onClick={() => setDraft((current) => ({ ...current, modes: [...current.modes, { mode_name: "New Mode", level: 1, description: "", color: "#64748b" }] }))}>＋ Add Mode</button></div>
            <div className="config-list">{draft.modes.map((mode, index) => <article className="config-row mode-row" key={`${index}-${mode.mode_name}`}>
              <label className="color-field" title="Mode color"><input type="color" value={mode.color} onChange={(event) => updateMode(index, { color: event.target.value })} /><span style={{ background: mode.color }} /></label>
              <label><span>Mode</span><input value={mode.mode_name} onChange={(event) => updateMode(index, { mode_name: event.target.value })} /></label>
              <label className="level-field"><span>Level</span><input type="number" min="0" max="10" step="0.5" value={mode.level} onChange={(event) => updateMode(index, { level: Number(event.target.value) })} /></label>
              <label className="wide"><span>Description</span><input value={mode.description} onChange={(event) => updateMode(index, { description: event.target.value })} /></label>
              <button className="remove-config" onClick={() => setDraft((current) => ({ ...current, modes: current.modes.filter((_, itemIndex) => itemIndex !== index) }))} aria-label={`Remove ${mode.mode_name}`}>×</button>
            </article>)}</div>
          </>}
          {tab === "task_types" && <>
            <div className="settings-section-heading"><div><h3>Task Types</h3><p>Edit the functional categories used by Yonc task classification.</p></div><button onClick={() => setDraft((current) => ({ ...current, task_types: [...current.task_types, { emoji: "", name: "New Type", description: "", tag: "" }] }))}>＋ Add Task Type</button></div>
            <div className="config-list">{draft.task_types.map((taskType, index) => <article className="config-row task-type-row" key={`${index}-${taskType.name}`}>
              <label className="emoji-field"><span>Emoji</span><input value={taskType.emoji} onChange={(event) => updateTaskType(index, { emoji: event.target.value })} /></label>
              <label><span>Name</span><input value={taskType.name} onChange={(event) => updateTaskType(index, { name: event.target.value })} /></label>
              <label><span>Tag</span><input value={taskType.tag} onChange={(event) => updateTaskType(index, { tag: event.target.value })} /></label>
              <label className="wide"><span>Description</span><input value={taskType.description} onChange={(event) => updateTaskType(index, { description: event.target.value })} /></label>
              <button className="remove-config" onClick={() => setDraft((current) => ({ ...current, task_types: current.task_types.filter((_, itemIndex) => itemIndex !== index) }))} aria-label={`Remove ${taskType.name}`}>×</button>
            </article>)}</div>
          </>}
        </div>
        <footer><div><span>{notice}</span><small>Revision {draft.revision} · source: {draft.source}</small></div><button onClick={onClose}>Close</button><button className="primary" disabled={saving} onClick={save}>{saving ? "Saving…" : "Save changes"}</button></footer>
      </section>
    </div>
  );
}

function MobileFallback({ graph, onDone }: { graph: GraphResponse; onDone: (node: GraphNode) => void }) {
  const actions = graph.nodes.filter((node) => node.work_type === "ACTION" && !["DONE", "CANCELLED", "SUPERSEDED"].includes(node.status)).slice(0, 12);
  return <main className="mobile-fallback"><header><span className="eyebrow">Global project file</span><h1>Yonc</h1><p>{graph.health.warning_count} graph warnings · {graph.pace.reliable ? `${graph.pace.median_hours?.toFixed(1)}h/week` : "pace baseline pending"}</p></header><section><h2>Next Actions</h2>{actions.length ? actions.map((node) => <article key={node.id}><div><b>{node.title}</b><span>{fmtDate(node.deadline)} · {formatEffort(node.estimated_effort_minutes)}</span></div><button className="primary" onClick={() => onDone(node)}>Done</button></article>) : <p className="quiet">No open Actions in this project file.</p>}</section></main>;
}

export default function App() {
  const [view, setView] = useState<MainView>("canvas");
  const [timelineMode, setTimelineMode] = useState<TimelineMode>("capacity");
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [yoncConfig, setYoncConfig] = useState<YoncConfig | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
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
      const [nextGraph, nextTimeline, nextConfig] = await Promise.all([api.graph(), api.timeline(TIMELINE_RANGE.start, TIMELINE_RANGE.end), api.yoncConfig()]);
      if (requestId !== latestLoad.current) return;
      setGraph(nextGraph);
      setTimeline(nextTimeline);
      setYoncConfig(nextConfig);
      setSelectedIds((current) => current.filter((id) => nextGraph.nodes.some((node) => node.id === id)));
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
    setSelectedIds([]);
    try { setSplit(await api.startSplit(node.id)); } catch (unknownError) { handleError(unknownError); }
  };
  const selectedId = selectedIds.length === 1 ? selectedIds[0] : null;
  const selected = graph?.nodes.find((node) => node.id === selectedId) ?? null;
  const nodeColors = useMemo(() => graph ? colorsForNodes(graph.nodes, yoncConfig) : {}, [graph, yoncConfig]);
  const mobileDone = (node: GraphNode) => { setSelectedIds([node.id]); setMobileDoneCandidate(node); };
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
        <main className="desktop-content">{view === "canvas" ? <CanvasView graph={graph} yoncConfig={yoncConfig} selectedIds={selectedIds} onSelectionChange={setSelectedIds} onOpenSplit={openSplit} onRegisterUndo={registerUndo} /> : <TimelineView timeline={timeline} graph={graph} yoncConfig={yoncConfig} selectedId={selectedId} mode={timelineMode} onMode={setTimelineMode} onSelect={(id) => setSelectedIds([id])} onRefresh={refresh} onError={handleError} onRegisterUndo={registerUndo} />}</main>
        {view === "canvas" && selected && <NodeInspector node={selected} color={nodeColors[selected.id]} graphVersion={graph.graph_version} onClose={() => setSelectedIds([])} onRefresh={refresh} onOpenSplit={openSplit} onError={handleError} onRegisterUndo={registerUndo} />}
        <MobileFallback graph={graph} onDone={mobileDone} />
      </>}
      {!loading && graph && !graph.nodes.length && <div className="empty-state"><h1>No work in this project file</h1><p>Import existing work or capture a Goal to begin.</p></div>}
      {split && graph && <SplitPanel split={split} graphVersion={graph.graph_version} onClose={() => setSplit(null)} onRefresh={refresh} onError={handleError} onRegisterUndo={registerUndo} />}
      {mobileDoneCandidate && <Modal title="确认完成" onClose={() => setMobileDoneCandidate(null)}><p>确认标记“{mobileDoneCandidate.title}”为完成？完成状态只能由你确认。</p><div className="modal-actions"><button onClick={() => setMobileDoneCandidate(null)}>取消</button><button className="primary" onClick={confirmMobileDone}>标记完成</button></div></Modal>}
      {settingsOpen && yoncConfig && <SettingsPanel config={yoncConfig} onClose={() => setSettingsOpen(false)} onSaved={setYoncConfig} onError={handleError} />}
      {error && <Modal title="操作未完成" onClose={() => setError(null)}><p>{error}</p><div className="modal-actions"><button className="primary" onClick={() => setError(null)}>知道了</button></div></Modal>}
      {undoNotice && <div className="undo-notice" role="status">{undoNotice}</div>}
    </div>
  );
}
