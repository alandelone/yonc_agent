import ELK from "elkjs/lib/elk.bundled.js";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "./api";
import { ListView } from "./ListView";
import { DirectionListView } from "./DirectionListView";
import type { Direction, GraphEdge, GraphNode, GraphResponse, ProposalNode, SplitAnnotation, SplitSession, Status, TimelineCell, TimelineResponse, YoncConfig } from "./types";

type MainView = "canvas" | "list" | "timeline" | "split";
type TimelineMode = "forecast" | "capacity" | "directions";
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

export type ThemeableNode = Pick<GraphNode, "id" | "parent_id"> & { tags?: Record<string, unknown> | null };

export function themeInfoForNode(
  node: ThemeableNode,
  config?: YoncConfig | null,
  nodesById?: ReadonlyMap<string, ThemeableNode> | Map<string, ThemeableNode>
): { name: string; color: string } | null {
  if (!config?.themes?.length) return null;
  let current: ThemeableNode | undefined = node;
  const visited = new Set<string>();
  while (current && !visited.has(current.id)) {
    visited.add(current.id);
    const rawTag = current.tags?.["Task Theme with colour"] ?? current.tags?.["Task Theme"] ?? current.tags?.["Theme"] ?? current.tags?.["theme"];
    const tag = Array.isArray(rawTag) ? rawTag.join(" | ") : String(rawTag ?? "").trim();
    if (tag) {
      const theme = [...config.themes].sort((a, b) => b.name.length - a.name.length).find((candidate) => (
        tag === candidate.name ||
        tag.startsWith(`${candidate.name} `) ||
        tag.startsWith(candidate.name) ||
        candidate.sub_themes.some((subTheme) => tag === subTheme || tag.includes(subTheme))
      ));
      if (theme) {
        return { name: theme.name, color: theme.color };
      }
    }
    current = (current.parent_id && nodesById) ? nodesById.get(current.parent_id) : undefined;
  }
  return null;
}

export function configuredThemeColor(node: GraphNode, nodesById: ReadonlyMap<string, GraphNode>, config?: YoncConfig | null) {
  const theme = themeInfoForNode(node, config, nodesById);
  if (!theme) return null;
  return shadeHexColor(theme.color, ({ 1: 1.16, 2: 1.03, 3: .9, 4: .76 } as Record<number, number>)[node.wbs_level ?? 3] ?? .9);
}

export function colorsForNodes(nodes: GraphNode[], config?: YoncConfig | null) {
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  return Object.fromEntries(nodes.map((node) => [node.id, configuredThemeColor(node, nodesById, config) ?? wbsColorFor(projectKeyForNode(node, nodesById), node.wbs_level)]));
}

const timelineWorkTypes = new Set(["GOAL", "DELIVERABLE", "WORK_PACKAGE", "ACTION", "UNCLASSIFIED"]);

export function timelinePoolMatches(
  nodes: GraphNode[],
  query: string,
  filter: TimelinePoolFilter,
  config?: YoncConfig | null,
  nodesById?: ReadonlyMap<string, ThemeableNode> | Map<string, ThemeableNode> | Record<string, ThemeableNode>
) {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const lookup: ReadonlyMap<string, ThemeableNode> | Map<string, ThemeableNode> =
    nodesById instanceof Map
      ? nodesById
      : nodesById && typeof nodesById === "object"
      ? new Map(Object.entries(nodesById))
      : new Map(nodes.map((n) => [n.id, n]));

  const themeOrder = config?.themes?.length
    ? new Map(config.themes.map((t, idx) => [t.name, idx]))
    : null;

  const nodeThemeIndex = (node: GraphNode): number => {
    if (!themeOrder) return 0;
    const theme = themeInfoForNode(node, config, lookup);
    if (!theme) return 999999;
    return themeOrder.get(theme.name) ?? 999999;
  };

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
      if (terms.length && aRank !== bRank) return aRank - bRank;
      if (themeOrder) {
        const themeDiff = nodeThemeIndex(a) - nodeThemeIndex(b);
        if (themeDiff !== 0) return themeDiff;
        return (a.wbs_level ?? 99) - (b.wbs_level ?? 99) || a.title.localeCompare(b.title);
      }
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

type CanvasFamilyNode = Pick<GraphNode, "id" | "parent_id" | "wbs_level" | "planned_start" | "deadline"> & {
  tags?: Record<string, unknown> | null;
  title?: string;
  work_type?: string;
};

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

export function tidyConstellationPositions(
  members: CanvasFamilyNode[],
  seedPositions: Record<string, Position>,
  nodeHeights: Record<string, number>,
  minGap = 20,
) {
  if (!members.length) return { positions: {}, width: 0, height: 0 };
  const root = members.find((n) => n.wbs_level === 1) ?? members.find((n) => !n.parent_id) ?? members[0];
  const anchorPos = seedPositions[root.id] ?? { x: 0, y: 0 };

  // 1. Initial relative positions relative to anchor
  const positions: Record<string, Position> = {};
  for (const node of members) {
    const pos = seedPositions[node.id];
    if (pos) {
      positions[node.id] = { x: pos.x - anchorPos.x, y: pos.y - anchorPos.y };
    } else {
      const level = node.wbs_level ?? 3;
      positions[node.id] = { x: (level - 1) * 120, y: (level - 1) * 60 };
    }
  }

  // 2. Resolve internal pairwise overlaps along their relative angle / separation vector
  const memberWidths = Object.fromEntries(members.map((n) => [n.id, nodeCardWidth(n)]));
  for (let pass = 0; pass < 6; pass += 1) {
    let moved = false;
    for (let i = 0; i < members.length; i += 1) {
      for (let j = i + 1; j < members.length; j += 1) {
        const a = members[i];
        const b = members[j];
        const posA = positions[a.id];
        const posB = positions[b.id];
        const wA = memberWidths[a.id];
        const hA = nodeHeights[a.id] ?? COMPACT_CARD_H;
        const wB = memberWidths[b.id];
        const hB = nodeHeights[b.id] ?? COMPACT_CARD_H;

        const overlapX = posA.x < posB.x + wB + minGap && posA.x + wA + minGap > posB.x;
        const overlapY = posA.y < posB.y + hB + minGap && posA.y + hA + minGap > posB.y;

        if (overlapX && overlapY) {
          moved = true;
          const centerAx = posA.x + wA / 2;
          const centerAy = posA.y + hA / 2;
          const centerBx = posB.x + wB / 2;
          const centerBy = posB.y + hB / 2;
          let dx = centerBx - centerAx;
          let dy = centerBy - centerAy;

          if (Math.abs(dx) < 0.1 && Math.abs(dy) < 0.1) {
            dx = b.parent_id === a.id ? 20 : -20;
            dy = b.parent_id === a.id ? 20 : -20;
          }

          const angle = Math.atan2(dy, dx);
          const targetDistX = (wA + wB) / 2 + minGap;
          const targetDistY = (hA + hB) / 2 + minGap;
          const pushX = Math.cos(angle) * Math.max(0, targetDistX - Math.abs(dx));
          const pushY = Math.sin(angle) * Math.max(0, targetDistY - Math.abs(dy));

          if (a.id === root.id) {
            positions[b.id] = { x: posB.x + pushX, y: posB.y + pushY };
          } else if (b.id === root.id) {
            positions[a.id] = { x: posA.x - pushX, y: posA.y - pushY };
          } else {
            positions[a.id] = { x: posA.x - pushX * 0.5, y: posA.y - pushY * 0.5 };
            positions[b.id] = { x: posB.x + pushX * 0.5, y: posB.y + pushY * 0.5 };
          }
        }
      }
    }
    if (!moved) break;
  }

  // 3. Normalize to top-left (0, 0)
  const minX = Math.min(...members.map((n) => positions[n.id].x));
  const minY = Math.min(...members.map((n) => positions[n.id].y));
  const normalizedPositions: Record<string, Position> = {};
  for (const n of members) {
    normalizedPositions[n.id] = { x: Math.round(positions[n.id].x - minX), y: Math.round(positions[n.id].y - minY) };
  }
  const maxX = Math.max(...members.map((n) => normalizedPositions[n.id].x + memberWidths[n.id]));
  const maxY = Math.max(...members.map((n) => normalizedPositions[n.id].y + (nodeHeights[n.id] ?? COMPACT_CARD_H)));

  return {
    positions: normalizedPositions,
    width: maxX,
    height: maxY,
  };
}

export function isUnclassifiedNode(node: CanvasFamilyNode): boolean {
  return node.work_type === "UNCLASSIFIED" || (!node.wbs_level && node.work_type !== "GOAL" && node.work_type !== "DELIVERABLE" && node.work_type !== "WORK_PACKAGE" && node.work_type !== "ACTION");
}

export function isUnclassifiedConstellation(c: { members: CanvasFamilyNode[] }): boolean {
  const hasStructuredRoot = c.members.some((node) => node.wbs_level === 1 || node.wbs_level === 2);
  if (hasStructuredRoot) return false;
  return c.members.some(isUnclassifiedNode);
}

export function arrangeCanvasFamilies(
  nodes: CanvasFamilyNode[],
  seedPositions: Record<string, Position>,
  nodeHeights: Record<string, number>,
  todayX: number,
  gap = 48,
  config?: YoncConfig | null,
) {
  const nodesById = new Map<string, CanvasFamilyNode>(nodes.map((node) => [node.id, node]));
  const families = new Map<string, CanvasFamilyNode[]>();
  for (const node of nodes) {
    if (!seedPositions[node.id]) continue;
    const key = projectKeyForNode(node, nodesById as unknown as ReadonlyMap<string, ColorNode>);
    const members = families.get(key) ?? [];
    members.push(node);
    families.set(key, members);
  }

  // Fallback: If no config themes provided, preserve original shelf layout
  if (!config?.themes?.length) {
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

  // --- Theme-based Auto Arrangement when config.themes is present ---
  const scheduledFamilies: Array<{ key: string; members: CanvasFamilyNode[] }> = [];
  const unscheduledNodes: CanvasFamilyNode[] = [];

  for (const [key, members] of families.entries()) {
    const isFamilyScheduled = members.some((node) => Boolean(node.planned_start || node.deadline));
    if (isFamilyScheduled) {
      scheduledFamilies.push({ key, members });
    } else {
      unscheduledNodes.push(...members);
    }
  }

  const arranged: Record<string, Position> = {};
  const placed: Array<{ x: number; y: number; width: number; height: number }> = [];

  // 1. Arrange scheduled families along the timeline as before
  const scheduledItems = scheduledFamilies.map(({ key, members }) => {
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
    return { key, members, bounds, memberPositions };
  }).sort((left, right) => left.bounds.top - right.bounds.top || left.key.localeCompare(right.key));

  for (const item of scheduledItems) {
    let dy = 0;
    for (let pass = 0; pass < nodes.length + 1; pass += 1) {
      let pushDown = 0;
      for (const node of item.members) {
        const position = item.memberPositions[node.id];
        if (!position) continue;
        const x = position.x;
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
      const next = { x: position.x, y: position.y + dy };
      arranged[node.id] = next;
      placed.push({ x: next.x, y: next.y, width: nodeCardWidth(node), height: nodeHeights[node.id] ?? COMPACT_CARD_H });
    }
  }

  // 2. Partition unscheduled nodes into Constellations (preserving intra-group relative geometry and angles)
  interface Constellation {
    themeName: string;
    familyKey: string;
    members: CanvasFamilyNode[];
    tidy: { positions: Record<string, Position>; width: number; height: number };
  }

  const constellationMap = new Map<string, CanvasFamilyNode[]>();
  for (const node of unscheduledNodes) {
    const theme = themeInfoForNode(node, config, nodesById as unknown as Map<string, ThemeableNode>);
    const themeKey = theme ? theme.name : "__unthemed__";
    const familyKey = projectKeyForNode(node, nodesById as unknown as ReadonlyMap<string, ColorNode>);
    const groupKey = `${themeKey}:::${familyKey}`;
    const list = constellationMap.get(groupKey) ?? [];
    list.push(node);
    constellationMap.set(groupKey, list);
  }

  const constellations: Constellation[] = [];
  for (const [groupKey, members] of constellationMap.entries()) {
    const [themeName, familyKey] = groupKey.split(":::");
    const tidy = tidyConstellationPositions(members, seedPositions, nodeHeights);
    constellations.push({ themeName, familyKey, members, tidy });
  }

  const themeOrder = new Map(config.themes.map((t, idx) => [t.name, idx]));
  const unclassifiedConstellations: Constellation[] = [];
  const constellationsByTheme = new Map<string, Constellation[]>();

  for (const c of constellations) {
    if (isUnclassifiedConstellation(c)) {
      unclassifiedConstellations.push(c);
    } else {
      const list = constellationsByTheme.get(c.themeName) ?? [];
      list.push(c);
      constellationsByTheme.set(c.themeName, list);
    }
  }

  const sortedThemeEntries = [...constellationsByTheme.entries()].sort(([nameA], [nameB]) => {
    const orderA = themeOrder.has(nameA) ? themeOrder.get(nameA)! : 999999;
    const orderB = themeOrder.has(nameB) ? themeOrder.get(nameB)! : 999999;
    return orderA - orderB || nameA.localeCompare(nameB);
  });

  const firstThreeThemeEntries: Array<[string, Constellation[]]> = [];
  const subsequentThemeEntries: Array<[string, Constellation[]]> = [];

  for (const entry of sortedThemeEntries) {
    const [themeName] = entry;
    const order = themeOrder.has(themeName) ? themeOrder.get(themeName)! : 999999;
    if (order < 3) {
      firstThreeThemeEntries.push(entry);
    } else {
      subsequentThemeEntries.push(entry);
    }
  }

  // 3. Layout First 3 themes in a single neat vertical column (竖列) along the Today line
  const nearTodayStart = todayX + 120;
  let currentY = 82;
  let maxColWidth = 0;

  for (const [, themeConstellations] of firstThreeThemeEntries) {
    for (const c of themeConstellations) {
      for (const node of c.members) {
        const rel = c.tidy.positions[node.id];
        const posX = nearTodayStart + rel.x;
        const posY = currentY + rel.y;
        const nodeH = nodeHeights[node.id] ?? COMPACT_CARD_H;
        const nodeW = nodeCardWidth(node);
        arranged[node.id] = { x: posX, y: posY };
        placed.push({ x: posX, y: posY, width: nodeW, height: nodeH });
      }
      currentY += c.tidy.height + 28;
      maxColWidth = Math.max(maxColWidth, c.tidy.width);
    }
  }

  const firstThreeMaxX = nearTodayStart + maxColWidth;

  // 4. Layout Subsequent themes (4, 5, 6, 7, 8...) in a 2D row-and-column grid in the far-right corner
  const cornerStartX = Math.max(todayX + 1200, firstThreeMaxX + 120);
  const maxGridWidth = 1400;
  let blockCursorX = cornerStartX;
  let blockCursorY = 82;
  let currentRowMaxH = 0;

  for (const [, themeConstellations] of subsequentThemeEntries) {
    for (const c of themeConstellations) {
      if (blockCursorX > cornerStartX && blockCursorX + c.tidy.width > cornerStartX + maxGridWidth) {
        blockCursorX = cornerStartX;
        blockCursorY += currentRowMaxH + 36;
        currentRowMaxH = 0;
      }
      for (const node of c.members) {
        const rel = c.tidy.positions[node.id];
        const posX = blockCursorX + rel.x;
        const posY = blockCursorY + rel.y;
        const nodeH = nodeHeights[node.id] ?? COMPACT_CARD_H;
        const nodeW = nodeCardWidth(node);
        arranged[node.id] = { x: posX, y: posY };
        placed.push({ x: posX, y: posY, width: nodeW, height: nodeH });
      }
      blockCursorX += c.tidy.width + 36;
      currentRowMaxH = Math.max(currentRowMaxH, c.tidy.height);
    }
  }

  // 5. Layout UNCLASSIFIED group tasks starting from Bottom Centre
  if (unclassifiedConstellations.length > 0) {
    unclassifiedConstellations.sort((a, b) => {
      const orderA = themeOrder.has(a.themeName) ? themeOrder.get(a.themeName)! : 999999;
      const orderB = themeOrder.has(b.themeName) ? themeOrder.get(b.themeName)! : 999999;
      if (orderA !== orderB) return orderA - orderB;
      const titleA = a.members[0]?.title ?? "";
      const titleB = b.members[0]?.title ?? "";
      return titleA.localeCompare(titleB);
    });

    const primaryPlaced = placed.filter((p) => p.x < cornerStartX);
    const primaryBottomY = primaryPlaced.length
      ? Math.max(...primaryPlaced.map((p) => p.y + p.height))
      : 82;
    const bottomCenterStartY = Math.max(primaryBottomY + 80, 700);

    const primaryAreaLeft = todayX;
    const primaryAreaRight = Math.max(todayX + 600, firstThreeMaxX);
    const primaryCenterX = Math.round((primaryAreaLeft + primaryAreaRight) / 2);

    const maxUnclassifiedRowWidth = 1100;
    const singleRowWidth = unclassifiedConstellations.reduce((sum, c) => sum + c.tidy.width + 36, 0) - 36;
    const effectiveWidth = Math.min(singleRowWidth, maxUnclassifiedRowWidth);
    const startX = Math.max(todayX, Math.round(primaryCenterX - effectiveWidth / 2));

    let unclassifiedCursorX = startX;
    let unclassifiedCursorY = bottomCenterStartY;
    let unclassifiedRowMaxH = 0;

    for (const c of unclassifiedConstellations) {
      if (unclassifiedCursorX > startX && unclassifiedCursorX + c.tidy.width > startX + maxUnclassifiedRowWidth) {
        unclassifiedCursorX = startX;
        unclassifiedCursorY += unclassifiedRowMaxH + 36;
        unclassifiedRowMaxH = 0;
      }

      for (let pass = 0; pass < c.members.length + 1; pass += 1) {
        let pushDown = 0;
        for (const node of c.members) {
          const rel = c.tidy.positions[node.id];
          const posX = unclassifiedCursorX + rel.x;
          const posY = unclassifiedCursorY + rel.y;
          const nodeH = nodeHeights[node.id] ?? COMPACT_CARD_H;
          const nodeW = nodeCardWidth(node);
          for (const other of placed) {
            const overlapsX = posX < other.x + other.width + 24 && posX + nodeW + 24 > other.x;
            const overlapsY = posY < other.y + other.height + 24 && posY + nodeH + 24 > other.y;
            if (overlapsX && overlapsY) pushDown = Math.max(pushDown, other.y + other.height + 24 - posY);
          }
        }
        if (pushDown <= 0) break;
        unclassifiedCursorY += pushDown;
      }

      for (const node of c.members) {
        const rel = c.tidy.positions[node.id];
        const posX = unclassifiedCursorX + rel.x;
        const posY = unclassifiedCursorY + rel.y;
        const nodeH = nodeHeights[node.id] ?? COMPACT_CARD_H;
        const nodeW = nodeCardWidth(node);
        arranged[node.id] = { x: posX, y: posY };
        placed.push({ x: posX, y: posY, width: nodeW, height: nodeH });
      }

      unclassifiedCursorX += c.tidy.width + 36;
      unclassifiedRowMaxH = Math.max(unclassifiedRowMaxH, c.tidy.height);
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

export function calculateRangeEnd(start: string, durationDays: number): string {
  if (!start || durationDays < 1) return start;
  return addDays(start, durationDays - 1);
}

export function calculateRangeDuration(start: string, end: string): number {
  if (!start || !end || end < start) return 1;
  return Math.max(1, daysBetween(start, end) + 1);
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
  const hasSignals = node.resource_count > 0;
  return { hasMeta, hasSignals };
}

export function nodeCardHeight(node: Pick<GraphNode, "planned_start" | "deadline" | "estimated_effort_minutes" | "resource_count" | "health"> & { wbs_level?: number | null }) {
  const { hasMeta, hasSignals } = nodeCardInfo(node);
  const baseHeight = node.wbs_level === 1 ? 88 : node.wbs_level === 2 ? 78 : node.wbs_level === 3 ? 72 : (node.wbs_level && node.wbs_level >= 4) ? 52 : COMPACT_CARD_H;
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

function NodeCard({ node, position, height, color, selected, yoncConfig, nodesById, onSelect, onSplit, onPointerDown, registerElement }: {
  node: GraphNode;
  position: Position;
  height: number;
  color: string;
  selected: boolean;
  yoncConfig?: YoncConfig | null;
  nodesById?: ReadonlyMap<string, GraphNode> | Map<string, GraphNode>;
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
  const theme = themeInfoForNode(node, yoncConfig, nodesById);
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
          {theme && (
            <span
              className="node-theme-pill"
              style={{ "--theme-color": theme.color } as React.CSSProperties}
              title={`Theme: ${theme.name}`}
            >
              {theme.name}
            </span>
          )}
          {taskEmojis.length > 0 && (
            <span className="node-task-emoji" title={String(node.tags?.["Task Type"] || "")} aria-hidden="true">
              {taskEmojis.join("")}
            </span>
          )}
          <span className="node-wbs-text">{node.wbs_level ? `L${node.wbs_level}` : "•"} {node.work_type.replace("_", " ")}</span>
        </span>
        <span className="node-state">{node.status}</span>
      </div>
      <h3 className={cardDescription || (node.health?.length ?? 0) > 0 ? "with-description" : undefined}>
        <span className="node-title">{display.title}</span>
        {(cardDescription || (node.health?.length ?? 0) > 0) && (
          <span className="node-desc-row">
            <small className="node-description" title={cardDescription || undefined}>{cardDescription || ""}</small>
            {(node.health?.length ?? 0) > 0 && (
              <span className="warning signal-warning" title={node.health?.map((h) => healthWarningMessage(h, node)).join(" | ") || "Graph health warning"}>
                △ {node.health.length}
              </span>
            )}
          </span>
        )}
      </h3>
      {hasMeta && <div className="node-meta">{node.planned_start && <span>{fmtDate(node.planned_start)}</span>}{node.deadline ? <span className={!node.planned_start ? "meta-end" : undefined}>⚑ {fmtDate(node.deadline)}</span> : effort && <span className={!node.planned_start ? "meta-end" : undefined}>{effort}</span>}</div>}
      {hasSignals && node.resource_count > 0 && <div className="node-signals"><span>{node.resource_count} refs</span></div>}
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
  const nodesById = useMemo(() => new Map(renderNodes.map((node) => [node.id, node])), [renderNodes]);
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
  const preserveViewportAfterArrange = useRef<null | { left: number; top: number; zoom: number }>(null);
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
  const familyAutomaticPositions = useMemo(() => arrangeCanvasFamilies(renderNodes, timelineAwareAutomaticPositions, nodeHeights, todayX, 48, yoncConfig), [renderNodes, timelineAwareAutomaticPositions, nodeHeights, todayX, yoncConfig]);
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


  const edgePaths = useMemo(() => renderEdges.map((edge) => {
    const endpoints = canvasEdgeEndpoints(edge);
    const source = positions[endpoints.sourceId];
    const target = positions[endpoints.targetId];
    if (!source || !target) return null;
    const obstacles = nodeBoxes.filter((box) => box.id !== endpoints.sourceId && box.id !== endpoints.targetId);
    const route = connectorRoute(source, nodeHeights[endpoints.sourceId], target, nodeHeights[endpoints.targetId], nodeWidths[endpoints.sourceId], nodeWidths[endpoints.targetId], obstacles, edge.id);
    return <path ref={(element) => { if (element) edgeRefs.current.set(edge.id, element); else edgeRefs.current.delete(edge.id); }} key={edge.id} data-source={endpoints.sourceId} data-target={endpoints.targetId} data-source-side={route.sourceSide} data-target-side={route.targetSide} className={`edge edge-${edge.relation}`} d={route.path} markerEnd="url(#arrow)" />;
  }), [renderEdges, positions, nodeBoxes, nodeHeights, nodeWidths]);

  const height = Math.max(760, ...Object.entries(positions).map(([id, item]) => item.y + (nodeHeights[id] ?? COMPACT_CARD_H) + 120));
  const width = Math.max(1800, todayX + maxOffset + CANVAS_TIME_END_PADDING, ...Object.entries(positions).map(([id, item]) => item.x + (nodeWidths[id] ?? CARD_W) + CANVAS_TIME_END_PADDING));
  const paintNodeDrag = useCallback((restoreRouting = false) => {
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
    // Obstacle routing can search many candidate paths. Only do it on release;
    // movement uses a cheap connector that still follows both endpoints.
    for (const node of restoreRouting ? renderNodes : []) {
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
      if (nodeDragFrame.current == null) nodeDragFrame.current = window.requestAnimationFrame(() => paintNodeDrag());
    };
    const finish = (event: PointerEvent) => {
      const current = nodeDrag.current;
      if (!current || event.pointerId !== current.pointerId) return;
      if (nodeDragFrame.current != null) {
        window.cancelAnimationFrame(nodeDragFrame.current);
        nodeDragFrame.current = null;
      }
      if (!current.moved) { current.dx = 0; current.dy = 0; }
      paintNodeDrag(true);
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
  const autoArrangeAll = (shouldFit = false) => {
    if (!layoutReady) return;
    const canvas = canvasRef.current;
    if (!shouldFit && canvas) {
      manualZoomChosen.current = true;
      restoringViewport.current = true;
      const snap = {
        left: canvas.scrollLeft,
        top: canvas.scrollTop,
        zoom: zoomTarget.current,
      };
      preserveViewportAfterArrange.current = snap;
      window.requestAnimationFrame(() => {
        if (preserveViewportAfterArrange.current && canvasRef.current) {
          canvasRef.current.scrollTo({ left: snap.left, top: snap.top });
          preserveViewportAfterArrange.current = null;
          restoringViewport.current = false;
        }
      });
    } else {
      preserveViewportAfterArrange.current = null;
    }
    const arranged = arrangeCanvasFamilies(renderNodes, positions, nodeHeights, todayX, 48, yoncConfig);
    fitAfterArrange.current = shouldFit;
    setManualPositions(arranged);
    void persistPositions(arranged).catch(() => undefined);
  };
  useLayoutEffect(() => {
    if (fitAfterArrange.current) {
      fitAfterArrange.current = false;
      fitAll();
      return;
    }
    const preserved = preserveViewportAfterArrange.current;
    if (preserved) {
      preserveViewportAfterArrange.current = null;
      const canvas = canvasRef.current;
      if (canvas) {
        if (Math.abs(preserved.zoom - zoom) > .0001) {
          zoomTarget.current = preserved.zoom;
          pendingZoomAnchor.current = { left: preserved.left, top: preserved.top };
          setZoom(preserved.zoom);
        } else {
          canvas.scrollTo({ left: preserved.left, top: preserved.top });
          updateViewport();
          window.requestAnimationFrame(() => {
            restoringViewport.current = false;
            scheduleViewportSave();
          });
        }
      } else {
        restoringViewport.current = false;
      }
    }
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
            {renderNodes.map((node) => <NodeCard key={node.id} node={node} position={positions[node.id]} height={nodeHeights[node.id]} color={nodeColors[node.id]} selected={selectedIds.includes(node.id)} yoncConfig={yoncConfig} nodesById={nodesById} registerElement={(element) => { if (element) nodeRefs.current.set(node.id, element); else nodeRefs.current.delete(node.id); }} onSelect={() => { if (suppressNodeClick.current) { suppressNodeClick.current = false; return; } onSelectionChange([node.id]); }} onSplit={() => onOpenSplit(node)} onPointerDown={(event) => {
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

function NodeInspector({ node, allNodes = [], color, graphVersion, onClose, onRefresh, onOpenSplit, onError, onRegisterUndo }: {
  node: GraphNode | null;
  allNodes?: GraphNode[];
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
  const [isEditingParent, setIsEditingParent] = useState(false);
  const [parentFilter, setParentFilter] = useState("");
  const [isConfirmingDone, setIsConfirmingDone] = useState(false);
  const [isConfirmingCancel, setIsConfirmingCancel] = useState(false);
  const [isConfirmingReopen, setIsConfirmingReopen] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [deadline, setDeadline] = useState(node?.deadline ?? "");
  const [startCue, setStartCue] = useState(node?.start_cue ?? "");
  const [doneWhen, setDoneWhen] = useState(node?.done_when ?? "");
  const [descriptionText, setDescriptionText] = useState(node?.description ?? "");

  const statusRowRef = useRef<HTMLDivElement | null>(null);
  const cancelReasonInputRef = useRef<HTMLTextAreaElement | null>(null);
  const parentRowRef = useRef<HTMLDivElement | null>(null);
  const parentSearchInputRef = useRef<HTMLInputElement | null>(null);
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
    setIsEditingParent(false);
    setParentFilter("");
    setIsConfirmingDone(false);
    setIsConfirmingCancel(false);
    setIsConfirmingReopen(false);
    setCancelReason("");
    setCancelError(null);
    setDeadline(node?.deadline ?? "");
    setStartCue(node?.start_cue ?? "");
    setDoneWhen(node?.done_when ?? "");
    setDescriptionText(node?.description ?? "");
  }, [node?.id]);

  if (!node) return null;

  const isAction = node.work_type === "ACTION" || (node.wbs_level ?? 0) >= 4;

  const parentNode = useMemo(() => {
    if (!node?.parent_id || !allNodes) return null;
    return allNodes.find((n) => n.id === node.parent_id) || null;
  }, [node?.parent_id, allNodes]);

  const forbiddenParentIds = useMemo(() => {
    if (!node || !allNodes) return new Set<string>();
    return new Set(canvasSubtreeIds(allNodes, node.id));
  }, [node, allNodes]);

  const descendantCount = useMemo(() => {
    if (!node || !allNodes) return 0;
    return Math.max(0, canvasSubtreeIds(allNodes, node.id).length - 1);
  }, [node, allNodes]);

  const candidateParents = useMemo(() => {
    if (!allNodes || !node) return [];
    return allNodes
      .filter((cand) => !forbiddenParentIds.has(cand.id) && cand.wbs_level !== 4 && cand.work_type !== "ACTION")
      .sort((a, b) => {
        const lvlA = a.wbs_level ?? 999;
        const lvlB = b.wbs_level ?? 999;
        if (lvlA !== lvlB) return lvlA - lvlB;
        return a.title.localeCompare(b.title);
      });
  }, [allNodes, node, forbiddenParentIds]);

  const filteredCandidateParents = useMemo(() => {
    const q = parentFilter.trim().toLowerCase();
    if (!q) return candidateParents;
    return candidateParents.filter((cand) => cand.title.toLowerCase().includes(q));
  }, [candidateParents, parentFilter]);

  const handleAssignParent = async (targetParentId: string | null, targetWorkType?: string) => {
    if (!node) return;
    try {
      const result = await api.reparent(node.id, targetParentId, graphVersion, targetWorkType);
      onRegisterUndo({ kind: "batch", batchId: result.operation_batch_id });
      setIsEditingParent(false);
      await onRefresh();
    } catch (error) {
      onError(error);
    }
  };

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

  const performCancel = async () => {
    const trimmed = cancelReason.trim();
    if (!trimmed) {
      setCancelError("请输入取消原因（必填）");
      cancelReasonInputRef.current?.focus();
      return;
    }
    try {
      const result = await api.transition(node.id, "cancel", graphVersion, trimmed, true);
      onRegisterUndo({ kind: "batch", batchId: result.operation_batch_id });
      setIsConfirmingCancel(false);
      setCancelReason("");
      setCancelError(null);
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
    setIsConfirmingCancel(false);
    setIsConfirmingReopen(false);
    setTimeout(() => {
      statusRowRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 40);
  };

  const scrollToCancel = () => {
    setIsConfirmingCancel(true);
    setIsConfirmingDone(false);
    setIsConfirmingReopen(false);
    setCancelReason("");
    setCancelError(null);
    setTimeout(() => {
      statusRowRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      cancelReasonInputRef.current?.focus();
    }, 40);
  };

  const scrollToReopen = () => {
    setIsConfirmingReopen(true);
    setIsConfirmingDone(false);
    setIsConfirmingCancel(false);
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
        <span>Parent / Scope</span>
        <div ref={parentRowRef} className="parent-cell-wrap">
          {isEditingParent ? (
            <div className="inspector-reparent-dropdown">
              <div className="reparent-dropdown-header">
                <span>Assign to L1, L2, or L3</span>
                <button type="button" className="btn-sm" onClick={() => setIsEditingParent(false)}>✕</button>
              </div>
              <input
                ref={parentSearchInputRef}
                type="text"
                className="reparent-search-input"
                placeholder="搜索 L1/L2/L3 父级..."
                value={parentFilter}
                onChange={(e) => setParentFilter(e.target.value)}
                autoFocus
              />
              <div className="reparent-options-list">
                {node.work_type !== "GOAL" && (
                  <button
                    type="button"
                    className="reparent-option-item special-top"
                    onClick={() => handleAssignParent(null, "GOAL")}
                  >
                    <span className="split-tab-badge l1">L1</span>
                    <span className="cand-title">🌟 设为 L1 顶层项目 (Top Project)</span>
                  </button>
                )}
                {filteredCandidateParents.map((cand) => {
                  const candLvl = cand.wbs_level ?? (cand.work_type === "GOAL" ? 1 : cand.work_type === "DELIVERABLE" ? 2 : 3);
                  const nextChildType = candLvl === 1 ? "DELIVERABLE" : candLvl === 2 ? "WORK_PACKAGE" : "ACTION";
                  const nextChildLvl = candLvl + 1;
                  const isCurrentParent = cand.id === node.parent_id;

                  return (
                    <button
                      key={cand.id}
                      type="button"
                      className={`reparent-option-item${isCurrentParent ? " is-active" : ""}`}
                      onClick={() => handleAssignParent(cand.id, nextChildType)}
                      disabled={isCurrentParent}
                    >
                      <span className={`split-tab-badge l${candLvl}`}>L{candLvl}</span>
                      <span className="cand-title" title={cand.title}>{cand.title}</span>
                      <span className="cand-arrow">→ L{nextChildLvl}</span>
                    </button>
                  );
                })}
                {filteredCandidateParents.length === 0 && (
                  <div className="reparent-empty-msg">无匹配的父级选项</div>
                )}
                {node.parent_id && (
                  <button
                    type="button"
                    className="reparent-option-item special-unassign"
                    onClick={() => handleAssignParent(null, "UNCLASSIFIED")}
                  >
                    <span className="split-tab-badge">•</span>
                    <span className="cand-title">✕ 解除归属 (设为未分类 UNCLASSIFIED)</span>
                  </button>
                )}
              </div>
            </div>
          ) : (
            <div
              className="editable-cell hover-edit-trigger parent-cell-display"
              onClick={() => {
                setIsEditingParent(true);
                setTimeout(() => parentSearchInputRef.current?.focus(), 40);
              }}
              title="点击分配或更改父级归属"
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  setIsEditingParent(true);
                  setTimeout(() => parentSearchInputRef.current?.focus(), 40);
                }
              }}
            >
              {node.parent_id && parentNode ? (
                <span className="parent-pill-info">
                  <span className={`split-tab-badge l${parentNode.wbs_level ?? 1}`}>L{parentNode.wbs_level ?? 1}</span>
                  <span className="parent-title-text">{parentNode.title}</span>
                </span>
              ) : node.work_type === "GOAL" ? (
                <span style={{ color: "#f59e0b", fontWeight: 600 }}>🌟 L1 顶层项目</span>
              ) : (
                <span style={{ color: "#94a3b8" }}>• 未分类 (UNCLASSIFIED) · 点击分配</span>
              )}
              <span className="edit-icon" aria-hidden="true">✎</span>
            </div>
          )}
        </div>
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
          ) : node.status === "CANCELLED" ? (
            <div className="status-cancelled-info">
              <b
                className="editable-cell hover-edit-trigger status-cancelled-clickable"
                onClick={scrollToReopen}
                title="已取消 · 点击恢复任务"
                role="button"
                tabIndex={0}
                onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") scrollToReopen(); }}
              >
                <span className="cancelled-badge">✕ {node.status}</span> <span className="edit-icon" aria-hidden="true">↺</span>
              </b>
              {node.status_reason && (
                <div className="cancelled-reason-tag" title={node.status_reason}>
                  原因: {node.status_reason}
                </div>
              )}
            </div>
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
          {isConfirmingCancel && (
            <div className="inline-confirm-box cancel-confirm-box">
              <span>确认取消该任务？请输入取消原因：</span>
              <textarea
                ref={cancelReasonInputRef}
                rows={2}
                className="cancel-reason-input"
                value={cancelReason}
                onChange={(e) => {
                  setCancelReason(e.target.value);
                  if (e.target.value.trim()) setCancelError(null);
                }}
                placeholder="请输入取消原因（必填）..."
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                    performCancel();
                  }
                }}
              />
              {cancelError && <span className="cancel-error-text">{cancelError}</span>}
              {descendantCount > 0 && (
                <div className="cancel-cascade-warning">
                  ⚠️ 该节点下有 {descendantCount} 个子任务，将一并取消。
                </div>
              )}
              <div className="inline-actions">
                <button type="button" className="btn-sm" onClick={() => { setIsConfirmingCancel(false); setCancelError(null); }}>取消</button>
                <button type="button" className="btn-sm danger" onClick={performCancel}>确认取消</button>
              </div>
            </div>
          )}
          {isConfirmingReopen && (
            <div className="inline-confirm-box">
              <span>{node.status === "CANCELLED" ? "确认恢复已取消的任务？" : "确认撤销完成？"}</span>
              {node.status === "CANCELLED" && descendantCount > 0 && (
                <div className="cancel-cascade-warning" style={{ color: "#94a3b8" }}>
                  提示：同时将恢复级联取消的子任务。
                </div>
              )}
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
        {node.status !== "DONE" && node.status !== "CANCELLED" ? (
          <>
            <button className={isAction && node.start_cue && node.done_when ? "primary" : ""} onClick={scrollToDone}>Mark Done</button>
            <button type="button" className="btn-mark-cancel" onClick={scrollToCancel}>Mark Cancel</button>
          </>
        ) : node.status === "DONE" ? (
          <button type="button" onClick={scrollToReopen}>Undo Done</button>
        ) : (
          <button type="button" onClick={scrollToReopen}>Undo Cancel</button>
        )}
      </div>
    </aside>
  );
}

const PRESET_DIRECTION_COLORS = [
  "#38bdf8",
  "#818cf8",
  "#a855f7",
  "#ec4899",
  "#f43f5e",
  "#f59e0b",
  "#10b981",
  "#06b6d4",
];

function FloatingDirectionTag({
  dir,
  timeline,
  weekIndex,
  cellSize,
  onUpdate,
  onDelete,
}: {
  dir: Direction;
  timeline: TimelineResponse;
  weekIndex: Record<string, number>;
  cellSize: number;
  onUpdate: (id: string, patch: Partial<Direction>) => Promise<void>;
  onDelete: (dir: Direction) => Promise<void>;
}) {
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [isEditingNotes, setIsEditingNotes] = useState(false);
  const [title, setTitle] = useState(dir.title);
  const [notes, setNotes] = useState(dir.notes);
  const [isColorOpen, setIsColorOpen] = useState(false);
  const [localOffsetX, setLocalOffsetX] = useState(dir.offset_x || 0);
  const isDraggingRef = useRef(false);
  const dragStartRef = useRef<{ clientX: number; initialOffset: number }>({ clientX: 0, initialOffset: 0 });

  useEffect(() => {
    setTitle(dir.title);
    setNotes(dir.notes);
    setLocalOffsetX(dir.offset_x || 0);
  }, [dir.title, dir.notes, dir.offset_x]);

  const cell = useMemo(
    () => timeline.cells.find((c) => c.date === dir.start_date) || timeline.cells.find((c) => c.date >= dir.start_date),
    [timeline.cells, dir.start_date]
  );
  const startCol = cell ? (weekIndex[`${cell.iso_year}-${cell.iso_week}`] ?? 0) : 0;
  const baseLeft = 56 + startCol * cellSize;
  const leftPos = Math.max(0, baseLeft + localOffsetX);
  const topPos = (dir.lane_index || 0) * 64 + 4;

  const handleDragStart = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    isDraggingRef.current = true;
    dragStartRef.current = { clientX: e.clientX, initialOffset: localOffsetX };

    const handleMouseMove = (moveEvent: MouseEvent) => {
      if (!isDraggingRef.current) return;
      const deltaX = moveEvent.clientX - dragStartRef.current.clientX;
      setLocalOffsetX(dragStartRef.current.initialOffset + deltaX);
    };

    const handleMouseUp = async (upEvent: MouseEvent) => {
      if (!isDraggingRef.current) return;
      isDraggingRef.current = false;
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
      const deltaX = upEvent.clientX - dragStartRef.current.clientX;
      const finalOffset = dragStartRef.current.initialOffset + deltaX;
      setLocalOffsetX(finalOffset);
      await onUpdate(dir.id, { offset_x: finalOffset });
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
  };

  const handleSaveTitle = async () => {
    setIsEditingTitle(false);
    if (title.trim() && title.trim() !== dir.title) {
      await onUpdate(dir.id, { title: title.trim() });
    } else {
      setTitle(dir.title);
    }
  };

  const handleSaveNotes = async () => {
    setIsEditingNotes(false);
    if (notes !== dir.notes) {
      await onUpdate(dir.id, { notes });
    }
  };

  const handleChangeColor = async (newColor: string) => {
    setIsColorOpen(false);
    if (newColor !== dir.color) {
      await onUpdate(dir.id, { color: newColor });
    }
  };

  return (
    <div
      className="floating-direction-tag"
      style={{
        left: `${leftPos}px`,
        top: `${topPos}px`,
        borderLeftColor: dir.color,
      }}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="direction-tag-header">
        <div className="direction-tag-drag-handle" onMouseDown={handleDragStart} title="拖拽左右微调便签位置">
          <span className="direction-tag-color-dot" style={{ backgroundColor: dir.color }} />
          <span style={{ fontSize: 13, cursor: "grab" }}>⠿</span>
        </div>

        {isEditingTitle ? (
          <input
            type="text"
            className="direction-edit-title"
            style={{ padding: "2px 5px", fontSize: 11.5 }}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={handleSaveTitle}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSaveTitle();
              if (e.key === "Escape") {
                setTitle(dir.title);
                setIsEditingTitle(false);
              }
            }}
            autoFocus
          />
        ) : (
          <h4 className="direction-tag-title" onDoubleClick={() => setIsEditingTitle(true)} title="双击修改标题">
            {dir.title}
          </h4>
        )}

        <div className="direction-tag-actions">
          <div style={{ position: "relative" }}>
            <button
              type="button"
              className="btn-icon"
              style={{ width: 18, height: 18, fontSize: 10 }}
              onClick={() => setIsColorOpen(!isColorOpen)}
              title="更改颜色"
            >
              ●
            </button>
            {isColorOpen && (
              <div className="tag-options-popover" style={{ top: "100%", right: 0, minWidth: 120 }}>
                <div className="color-swatches-wrap" style={{ padding: 4 }}>
                  {PRESET_DIRECTION_COLORS.map((col) => (
                    <button
                      key={col}
                      type="button"
                      className={`color-swatch-chip ${dir.color === col ? "active" : ""}`}
                      style={{ backgroundColor: col }}
                      onClick={() => handleChangeColor(col)}
                    />
                  ))}
                  <input
                    type="color"
                    value={dir.color}
                    onChange={(e) => handleChangeColor(e.target.value)}
                    className="custom-color-circle"
                  />
                </div>
              </div>
            )}
          </div>
          <button
            type="button"
            className="btn-icon danger"
            style={{ width: 18, height: 18, fontSize: 11 }}
            onClick={() => onDelete(dir)}
            title="删除此方向"
          >
            ×
          </button>
        </div>
      </div>

      <div className="direction-tag-dates">
        {dir.start_date.slice(5)} ~ {dir.end_date.slice(5)}
      </div>

      {isEditingNotes ? (
        <textarea
          className="direction-edit-notes"
          style={{ marginTop: 4, padding: "3px 6px", fontSize: 10.5 }}
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          onBlur={handleSaveNotes}
          autoFocus
        />
      ) : (
        <div
          className="direction-tag-notes"
          onClick={() => setIsEditingNotes(true)}
          title="点击编辑思考笔记"
        >
          {dir.notes ? dir.notes : <span style={{ color: "#64748b", fontStyle: "italic" }}>+ 添加思考笔记…</span>}
        </div>
      )}

      <div className="direction-pointer-arrow" style={{ borderTopColor: "rgba(13, 22, 35, 0.96)" }} />
    </div>
  );
}

function TimelineGrid({ timeline, graph, yoncConfig, directions = [], selectedId, calendarRef, onSelect, onRefresh, onError, onRegisterUndo }: {
  timeline: TimelineResponse;
  graph: GraphResponse;
  yoncConfig: YoncConfig | null;
  directions?: Direction[];
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
  const nodesByIdMap = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node])), [graph.nodes]);
  const nodeColors = useMemo(() => colorsForNodes(graph.nodes, yoncConfig), [graph.nodes, yoncConfig]);
  const schedulableModules = useMemo(
    () => graph.nodes.filter((node) => node.work_type !== "ACTION" && (node.wbs_level === null || node.wbs_level <= 3) && timelineWorkTypes.has(node.work_type)),
    [graph.nodes]
  );
  const unscheduled = useMemo(
    () => schedulableModules.filter((node) => !node.planned_start),
    [schedulableModules]
  );
  const scheduledModules = useMemo(
    () => schedulableModules.filter((node) => node.planned_start).sort((a, b) => (a.planned_start ?? "").localeCompare(b.planned_start ?? "")),
    [schedulableModules]
  );
  const [searchQuery, setSearchQuery] = useState("");
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [rangeNode, setRangeNode] = useState<GraphNode | null>(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [durationDays, setDurationDays] = useState(1);
  const [rangeDeadline, setRangeDeadline] = useState("");
  const [isDragOverPool, setIsDragOverPool] = useState(false);
  const lastSavedRange = useRef<{ start: string; end: string; durationDays: number; deadline: string }>({
    start: "",
    end: "",
    durationDays: 1,
    deadline: "",
  });
  const saveTimeoutRef = useRef<any>(null);
  const [draggedNodeId, setDraggedNodeId] = useState<string | null>(null);
  const [dragAnchorOffset, setDragAnchorOffset] = useState(0);
  const [dropPreviewDate, setDropPreviewDate] = useState<string | null>(null);
  const [pendingPlacement, setPendingPlacement] = useState<{ nodeId: string; start: string; end: string } | null>(null);

  // Direction Selection & Segments State
  const [isSelectingDirection, setIsSelectingDirection] = useState(false);
  const [directionSelectStart, setDirectionSelectStart] = useState<string | null>(null);
  const [directionSelectEnd, setDirectionSelectEnd] = useState<string | null>(null);
  const [draftModal, setDraftModal] = useState<{ start: string; end: string } | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftNotes, setDraftNotes] = useState("");
  const [draftColor, setDraftColor] = useState("#38bdf8");
  const [isCreatingDraft, setIsCreatingDraft] = useState(false);

  const activeSelectionRange = useMemo(() => {
    if (!isSelectingDirection || !directionSelectStart || !directionSelectEnd) return null;
    const s = directionSelectStart <= directionSelectEnd ? directionSelectStart : directionSelectEnd;
    const e = directionSelectStart <= directionSelectEnd ? directionSelectEnd : directionSelectStart;
    return { start: s, end: e };
  }, [isSelectingDirection, directionSelectStart, directionSelectEnd]);

  useEffect(() => {
    if (!isSelectingDirection) return;
    const handleGlobalMouseUp = () => {
      if (directionSelectStart && directionSelectEnd) {
        const s = directionSelectStart <= directionSelectEnd ? directionSelectStart : directionSelectEnd;
        const e = directionSelectStart <= directionSelectEnd ? directionSelectEnd : directionSelectStart;
        setDraftModal({ start: s, end: e });
        setDraftTitle("");
        setDraftNotes("");
        setDraftColor("#38bdf8");
      }
      setIsSelectingDirection(false);
      setDirectionSelectStart(null);
      setDirectionSelectEnd(null);
    };
    const handleGlobalKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsSelectingDirection(false);
        setDirectionSelectStart(null);
        setDirectionSelectEnd(null);
      }
    };
    window.addEventListener("mouseup", handleGlobalMouseUp);
    window.addEventListener("keydown", handleGlobalKeyDown);
    return () => {
      window.removeEventListener("mouseup", handleGlobalMouseUp);
      window.removeEventListener("keydown", handleGlobalKeyDown);
    };
  }, [isSelectingDirection, directionSelectStart, directionSelectEnd]);

  const maxLane = useMemo(
    () => Math.max(0, ...directions.map((d) => d.lane_index ?? 0)),
    [directions]
  );

  const weekdayOrder = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const directionSegments = useMemo(() => {
    return directions.map((dir) => {
      const matchingCells = timeline.cells.filter((c) => c.date >= dir.start_date && c.date <= dir.end_date);
      if (!matchingCells.length) return { dir, segments: [] };
      const byWeek: Record<string, TimelineCell[]> = {};
      for (const c of matchingCells) {
        const wKey = `${c.iso_year}-${c.iso_week}`;
        if (!byWeek[wKey]) byWeek[wKey] = [];
        byWeek[wKey].push(c);
      }
      const segments = Object.entries(byWeek)
        .map(([wKey, cells]) => {
          const colIdx = weekIndex[wKey];
          const rows = cells.map((c) => weekdayOrder.indexOf(c.weekday) + 2);
          const minRow = Math.min(...rows);
          const maxRow = Math.max(...rows);
          return {
            wKey,
            col: colIdx != null ? colIdx + 2 : null,
            minRow,
            maxRow,
            startDate: cells[0].date,
            endDate: cells[cells.length - 1].date,
          };
        })
        .filter((s) => s.col != null);

      return { dir, segments };
    });
  }, [directions, timeline.cells, weekIndex]);

  const handleConfirmDraft = async () => {
    if (!draftModal) return;
    const title = draftTitle.trim() || "Untitled Direction";
    setIsCreatingDraft(true);
    try {
      const res = await api.createDirection({
        title,
        notes: draftNotes,
        color: draftColor,
        start_date: draftModal.start,
        end_date: draftModal.end,
      });
      if (res.operation_batch) {
        onRegisterUndo({ kind: "batch", batchId: res.operation_batch.id });
      }
      setDraftModal(null);
      await onRefresh();
    } catch (err) {
      onError(err);
    } finally {
      setIsCreatingDraft(false);
    }
  };
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
    const node = byId[nodeId];
    if (node && (node.work_type === "ACTION" || (node.wbs_level !== null && node.wbs_level > 3))) {
      onError(new Error("Tasks (L4 Actions) cannot be assigned in Timeline."));
      return;
    }
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
    if (node && (node.work_type === "ACTION" || (node.wbs_level !== null && node.wbs_level > 3))) {
      clearModuleDrag();
      onError(new Error("Tasks (L4 Actions) cannot be assigned in Timeline."));
      return;
    }
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
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    setRangeNode(node);
    const initialStart = node.planned_start ?? "";
    const initialEnd = node.planned_end ?? node.planned_start ?? "";
    const initialDuration = initialStart && initialEnd ? Math.max(1, daysBetween(initialStart, initialEnd) + 1) : 1;
    const initialDeadline = node.deadline ?? initialEnd ?? "";
    setStart(initialStart);
    setEnd(initialEnd);
    setDurationDays(initialDuration);
    setRangeDeadline(initialDeadline);
    lastSavedRange.current = {
      start: initialStart,
      end: initialEnd,
      durationDays: initialDuration,
      deadline: initialDeadline,
    };
    onSelect(node.id);
  };
  const normalizedSearch = searchQuery.trim();
  const poolNodes = useMemo(() => {
    const candidates = normalizedSearch ? schedulableModules : unscheduled;
    return timelinePoolMatches(candidates, normalizedSearch, "jobs", yoncConfig, nodesByIdMap);
  }, [schedulableModules, normalizedSearch, unscheduled, yoncConfig, nodesByIdMap]);
  const choosePoolNode = (node: GraphNode) => {
    if (node.planned_start) {
      openRange(node);
      window.requestAnimationFrame(() => {
        const cell = calendarRef.current?.querySelector<HTMLElement>(`[data-date="${node.planned_start}"]`);
        if (cell && calendarRef.current) calendarRef.current.scrollTo({ left: Math.max(0, cell.offsetLeft - calendarRef.current.clientWidth / 2 + cell.clientWidth / 2), behavior: "smooth" });
      });
    } else onSelect(node.id);
  };
  const triggerAutoSave = (targetStart: string, targetEnd: string, targetDeadline: string, targetDuration: number) => {
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    if (!targetStart || !targetEnd) return;
    if (targetEnd < targetStart) {
      onError(new Error("End date cannot be earlier than Start date"));
      setStart(lastSavedRange.current.start);
      setEnd(lastSavedRange.current.end);
      setDurationDays(lastSavedRange.current.durationDays);
      setRangeDeadline(lastSavedRange.current.deadline);
      return;
    }
    saveTimeoutRef.current = setTimeout(async () => {
      if (!rangeNode) return;
      try {
        const scheduled = await api.schedule(rangeNode.id, targetStart, targetEnd, graph.graph_version);
        if (scheduled.operation_batch_id) onRegisterUndo({ kind: "batch", batchId: scheduled.operation_batch_id });
        let nextVersion = scheduled.graph_version;
        const targetDeadlineVal = targetDeadline.trim() || null;
        if (targetDeadlineVal !== (rangeNode.deadline ?? null)) {
          const patched = await api.patchNode(rangeNode.id, { deadline: targetDeadlineVal }, nextVersion);
          if (patched.operation_batch_id) onRegisterUndo({ kind: "batch", batchId: patched.operation_batch_id });
        }
        lastSavedRange.current = {
          start: targetStart,
          end: targetEnd,
          durationDays: targetDuration,
          deadline: targetDeadline,
        };
        await onRefresh();
      } catch (error) {
        onError(error);
        setStart(lastSavedRange.current.start);
        setEnd(lastSavedRange.current.end);
        setDurationDays(lastSavedRange.current.durationDays);
        setRangeDeadline(lastSavedRange.current.deadline);
      }
    }, 250);
  };
  const handleStartChange = (newStart: string) => {
    setStart(newStart);
    if (!newStart) return;
    const newEnd = durationDays >= 1 ? addDays(newStart, durationDays - 1) : newStart;
    setEnd(newEnd);
    setRangeDeadline(newEnd);
    triggerAutoSave(newStart, newEnd, newEnd, durationDays);
  };
  const handleDurationChange = (valStr: string) => {
    const parsed = parseInt(valStr, 10);
    const newDuration = isNaN(parsed) || parsed < 1 ? 1 : parsed;
    setDurationDays(newDuration);
    if (start) {
      const newEnd = addDays(start, newDuration - 1);
      setEnd(newEnd);
      setRangeDeadline(newEnd);
      triggerAutoSave(start, newEnd, newEnd, newDuration);
    }
  };
  const handleEndChange = (newEnd: string) => {
    setEnd(newEnd);
    if (!newEnd) return;
    if (start) {
      if (newEnd < start) {
        onError(new Error("End date cannot be earlier than Start date"));
        setStart(lastSavedRange.current.start);
        setEnd(lastSavedRange.current.end);
        setDurationDays(lastSavedRange.current.durationDays);
        setRangeDeadline(lastSavedRange.current.deadline);
        return;
      }
      const newDuration = Math.max(1, daysBetween(start, newEnd) + 1);
      setDurationDays(newDuration);
      setRangeDeadline(newEnd);
      triggerAutoSave(start, newEnd, newEnd, newDuration);
    } else {
      setRangeDeadline(newEnd);
    }
  };
  const handleDeadlineChange = (newDeadline: string) => {
    setRangeDeadline(newDeadline);
    if (start && end) {
      triggerAutoSave(start, end, newDeadline, durationDays);
    }
  };
  const handleRemoveFromTimeline = async () => {
    if (!rangeNode) return;
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    try {
      const scheduled = await api.schedule(rangeNode.id, null, null, graph.graph_version);
      if (scheduled.operation_batch_id) onRegisterUndo({ kind: "batch", batchId: scheduled.operation_batch_id });
      setRangeNode(null);
      await onRefresh();
    } catch (error) {
      onError(error);
    }
  };
  return (
    <div className="timeline-layout">
      <aside
        className={`module-pool ${isDragOverPool ? "accepting-drop" : ""}`}
        onDragOver={(event) => {
          if (draggedNodeId) {
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
          }
        }}
        onDragEnter={(event) => {
          if (draggedNodeId) {
            event.preventDefault();
            setIsDragOverPool(true);
          }
        }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            setIsDragOverPool(false);
          }
        }}
        onDrop={async (event) => {
          event.preventDefault();
          setIsDragOverPool(false);
          const nodeId = event.dataTransfer.getData("text/yonc-node") || draggedNodeId;
          if (!nodeId) return;
          const node = byId[nodeId];
          if (!node || !node.planned_start) return;
          clearModuleDrag();
          try {
            const scheduled = await api.schedule(nodeId, null, null, graph.graph_version);
            if (scheduled.operation_batch_id) onRegisterUndo({ kind: "batch", batchId: scheduled.operation_batch_id });
            if (rangeNode?.id === nodeId) setRangeNode(null);
            await onRefresh();
          } catch (error) {
            onError(error);
          }
        }}
      >
        <div className="module-pool-head">
          <div className="module-pool-header-row">
            <div className="module-pool-title-wrap">
              <h2>Module pool</h2>
              <span className="module-pool-count">
                {normalizedSearch
                  ? `${poolNodes.length} result${poolNodes.length === 1 ? "" : "s"}`
                  : `${poolNodes.length} ${poolNodes.length === 1 ? "module" : "modules"}`}
              </span>
            </div>
            <button
              type="button"
              className="module-search-icon-btn"
              onClick={() => {
                setIsSearchOpen(true);
                setTimeout(() => searchInputRef.current?.focus(), 50);
              }}
              title="Search modules"
              aria-label="Search modules"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
            </button>
            <div className={`module-search-overlay ${isSearchOpen ? "open" : ""}`}>
              <span className="module-search-icon" aria-hidden="true">⌕</span>
              <input
                ref={searchInputRef}
                type="search"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && poolNodes[0]) choosePoolNode(poolNodes[0]);
                  if (event.key === "Escape") {
                    setSearchQuery("");
                    setIsSearchOpen(false);
                  }
                }}
                placeholder="Search modules…"
                aria-label="Search modules"
              />
              <button
                type="button"
                className="module-search-close-btn"
                onClick={() => {
                  setSearchQuery("");
                  setIsSearchOpen(false);
                }}
                aria-label="Close search"
                title="Close search"
              >
                ×
              </button>
            </div>
          </div>
        </div>
        <div className="module-pool-list">
          {poolNodes.length ? poolNodes.map((node) => {
            const lvl = node.wbs_level ? Math.min(Math.max(node.wbs_level, 1), 3) : (node.work_type === "GOAL" ? 1 : node.work_type === "WORK_PACKAGE" ? 3 : 2);
            return (
              <article
                key={node.id}
                className={`${draggedNodeId === node.id || pendingPlacement?.nodeId === node.id ? "dragging " : ""}${selectedId === node.id ? "selected" : ""}`}
                draggable
                aria-label={`Drag ${node.title} to a date`}
                onDragStart={(event) => beginModuleDrag(event, node.id)}
                onDragEnd={clearModuleDrag}
                onClick={() => choosePoolNode(node)}
                title={node.title}
              >
                <i style={{ background: nodeColors[node.id] }} />
                <b title={node.title}>{node.title}</b>
                <span className={`split-tab-badge l${lvl}`}>L{lvl}</span>
              </article>
            );
          }) : <p className="quiet">{normalizedSearch ? `No modules match “${normalizedSearch}”.` : "All modules have scheduled dates."}</p>}
        </div>
      </aside>
      <section
        ref={calendarRef}
        className={`calendar-wrap ${draggedNodeId ? "accepting-drop" : ""}`}
        onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropPreviewDate(null); }}
        onMouseUp={() => {
          if (isSelectingDirection && directionSelectStart && directionSelectEnd) {
            setIsSelectingDirection(false);
            const start = directionSelectStart <= directionSelectEnd ? directionSelectStart : directionSelectEnd;
            const end = directionSelectStart <= directionSelectEnd ? directionSelectEnd : directionSelectStart;
            setDraftModal({ start, end });
            setDraftTitle("");
            setDraftNotes("");
            setDraftColor("#38bdf8");
            setDirectionSelectStart(null);
            setDirectionSelectEnd(null);
          }
        }}
      >
        {/* Direction Floating Tags in Top Strip */}
        <div
          className="direction-lanes-strip"
          style={{
            width: `${56 + weeks.length * cellSize}px`,
            minHeight: directions.length ? `${(maxLane + 1) * 66 + 4}px` : "0px",
            display: directions.length ? "block" : "none",
          }}
        >
          {directions.map((dir) => (
            <FloatingDirectionTag
              key={dir.id}
              dir={dir}
              timeline={timeline}
              weekIndex={weekIndex}
              cellSize={cellSize}
              onUpdate={async (id, patch) => {
                const res = await api.updateDirection(id, patch);
                if (res.operation_batch) onRegisterUndo({ kind: "batch", batchId: res.operation_batch.id });
                await onRefresh();
              }}
              onDelete={async (d) => {
                if (!window.confirm(`确定删除阶段方向「${d.title}」吗？`)) return;
                const res = await api.deleteDirection(d.id);
                if (res.operation_batch) onRegisterUndo({ kind: "batch", batchId: res.operation_batch.id });
                await onRefresh();
              }}
            />
          ))}
        </div>

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

          {/* Direction Capsules (Enclosures) */}
          {directionSegments.map(({ dir, segments }) =>
            segments.map((seg, sIdx) => (
              <div
                key={`${dir.id}-capsule-${sIdx}`}
                className="direction-capsule"
                style={{
                  gridColumn: seg.col!,
                  gridRow: `${seg.minRow} / ${seg.maxRow + 1}`,
                  borderColor: dir.color,
                  backgroundColor: `${dir.color}18`,
                  boxShadow: `0 0 12px ${dir.color}35`,
                }}
                title={`${dir.title} (${dir.start_date} ~ ${dir.end_date})`}
              />
            ))
          )}
          {/* Direction Connecting Bridges */}
          {directionSegments.map(({ dir, segments }) =>
            segments.slice(0, -1).map((seg, idx) => {
              const nextSeg = segments[idx + 1];
              return (
                <div
                  key={`${dir.id}-bridge-${idx}`}
                  className="direction-bridge"
                  style={{
                    gridColumn: `${seg.col!} / ${nextSeg.col! + 1}`,
                    gridRow: `${seg.maxRow} / ${nextSeg.minRow + 1}`,
                    borderBottom: `2px dashed ${dir.color}90`,
                    borderLeft: `2px dashed ${dir.color}90`,
                    borderRadius: "0 0 0 6px",
                    pointerEvents: "none",
                    zIndex: 5,
                  }}
                />
              );
            })
          )}

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
            const isSelectedForDirection = Boolean(
              activeSelectionRange && cell.date >= activeSelectionRange.start && cell.date <= activeSelectionRange.end
            );
            return <button key={cell.date} data-date={cell.date} className={`day-cell ${cell.today ? "today" : ""} ${cell.deadline_node_ids.length ? "deadline" : ""} ${cell.overlap_count > 2 ? "overload" : ""} ${selected ? "range-selected" : ""} ${draggingSource ? "drag-source" : ""} ${dropPreview ? "drop-preview" : ""} ${previewRangeStart ? "drop-preview-start" : ""} ${isSelectedForDirection ? "direction-drag-selected" : ""}`} style={{ gridColumn: weekIndex[key] + 2, gridRow: row, background }} draggable={Boolean(dragAllocationId)} onMouseDown={(event) => { if (event.shiftKey && event.button === 0) { event.preventDefault(); event.stopPropagation(); setIsSelectingDirection(true); setDirectionSelectStart(cell.date); setDirectionSelectEnd(cell.date); } }} onMouseEnter={() => { if (isSelectingDirection) { setDirectionSelectEnd(cell.date); } }} onDragStart={(event) => { if (dragAllocationId) { const node = byId[dragAllocationId]; beginModuleDrag(event, dragAllocationId, node?.planned_start ? daysBetween(node.planned_start, cell.date) : 0); } }} onDragEnd={clearModuleDrag} onDragEnter={(event) => { event.preventDefault(); if (draggedNodeId) setDropPreviewDate(cell.date); }} onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "move"; if (draggedNodeId && dropPreviewDate !== cell.date) setDropPreviewDate(cell.date); }} onDrop={(event) => drop(event, cell)} onClick={() => dragAllocationId && openRange(byId[dragAllocationId])} aria-label={`${cell.date}, ${cell.overlap_count} planned allocation${cell.overlap_count === 1 ? "" : "s"}${dragAllocationId ? ", draggable scheduled range" : ""}${dropPreview ? `, previewing ${previewNode?.title ?? "module"} from ${previewStart} to ${previewEnd}` : ""}`}><span>{new Date(`${cell.date}T12:00:00`).getDate()}</span>{cell.overflow_count > 0 && <b>+{cell.overflow_count}</b>}{cell.deadline_node_ids.length > 0 && <i>⚑</i>}</button>;
          })}

        </div>
        <footer className="scheduled-module-lane" aria-label="Scheduled modules by week" style={{ gridTemplateColumns: `56px repeat(${weeks.length}, ${cellSize}px)`, gridTemplateRows: `repeat(${scheduledLaneCount}, 22px)` }}><span style={{ gridColumn: 1, gridRow: `1 / ${scheduledLaneCount + 1}` }}>Scheduled</span>{scheduledLaneItems.map(({ node, pending, startDate, endDate, startWeek, displayEndWeek, singleDay, lane }) => <button key={node.id} className={`${pending ? "pending " : ""}${singleDay ? "single-day" : "range"}`} style={{ "--module-color": nodeColors[node.id], gridColumn: `${startWeek + 2} / ${displayEndWeek + 3}`, gridRow: lane + 1 } as React.CSSProperties} draggable={!pending} onDragStart={(event) => !pending && beginModuleDrag(event, node.id)} onDragEnd={clearModuleDrag} onClick={() => !pending && openRange(node)} title={`${node.title} — ${singleDay ? startDate : `${startDate} to ${endDate}`}`} aria-label={`${node.title}, scheduled ${singleDay ? `on ${startDate}` : `from ${startDate} to ${endDate}`}`}><span className="scheduled-module-copy">{singleDay && <small>{fmtDate(startDate)}</small>}<b>{node.title}</b></span></button>)}</footer>
      </section>
      {rangeNode && <aside className="range-inspector floating-range">
          <button className="inspector-close" onClick={() => { if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current); setRangeNode(null); }} aria-label="关闭范围详情">×</button>
          <span className="eyebrow">Selected range</span>
          <h2>{rangeNode.title}</h2>
          <div className="range-triplet-group">
            <label className="field">
              Start
              <input type="date" value={start} onChange={(event) => handleStartChange(event.target.value)} />
            </label>
            <label className="field duration-field">
              Days
              <input type="number" min="1" value={durationDays} onChange={(event) => handleDurationChange(event.target.value)} />
            </label>
            <label className="field">
              End
              <input type="date" value={end} onChange={(event) => handleEndChange(event.target.value)} />
            </label>
          </div>
          <label className="field">Deadline
            <input type="date" value={rangeDeadline} onChange={(event) => { setRangeDeadline(event.target.value); handleDeadlineChange(event.target.value); }} />
          </label>
          <p className="quiet">Moving or resizing changes planned dates, never estimated effort.</p>
          <button type="button" className="btn-remove-timeline" onClick={handleRemoveFromTimeline}>Remove from Timeline</button>
          <hr />
          <span className="eyebrow">Weekly capacity</span>
          <p>{timeline.warnings.length ? `${timeline.warnings.length} overlap warning${timeline.warnings.length === 1 ? "" : "s"}` : "No overloaded cells in this range."}</p>
        </aside>}
      {draftModal && (
        <div className="direction-draft-modal-backdrop" onClick={() => setDraftModal(null)}>
          <div className="direction-draft-modal" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h3>设立阶段方向 (New Direction)</h3>
              <button className="inspector-close" onClick={() => setDraftModal(null)}>×</button>
            </div>
            <p className="direction-draft-dates-hint">
              📅 {draftModal.start} 至 {draftModal.end} · {daysBetween(draftModal.start, draftModal.end)} 天
            </p>
            <input
              type="text"
              placeholder="方向主题（例如：论文攻坚、Q4 基础设施升级）…"
              value={draftTitle}
              onChange={(e) => setDraftTitle(e.target.value)}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") handleConfirmDraft();
              }}
            />
            <div className="color-swatches-wrap">
              <span style={{ fontSize: 11, color: "#94a3b8" }}>颜色:</span>
              {PRESET_DIRECTION_COLORS.map((col) => (
                <button
                  key={col}
                  type="button"
                  className={`color-swatch-chip ${draftColor === col ? "active" : ""}`}
                  style={{ backgroundColor: col }}
                  onClick={() => setDraftColor(col)}
                />
              ))}
              <input
                type="color"
                value={draftColor}
                onChange={(e) => setDraftColor(e.target.value)}
                className="custom-color-circle"
              />
            </div>
            <textarea
              placeholder="思考笔记 (Bullet points，可留空，后续随时编辑)…"
              rows={3}
              value={draftNotes}
              onChange={(e) => setDraftNotes(e.target.value)}
            />
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 4 }}>
              <button
                type="button"
                className="btn-sm primary"
                disabled={isCreatingDraft}
                onClick={handleConfirmDraft}
              >
                创建 Direction
              </button>
              <button
                type="button"
                className="btn-sm"
                onClick={() => setDraftModal(null)}
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}
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

function TimelineView({ timeline, graph, yoncConfig, directions = [], selectedId, mode, onMode, onSelect, onRefresh, onError, onRegisterUndo }: {
  timeline: TimelineResponse;
  graph: GraphResponse;
  yoncConfig: YoncConfig | null;
  directions?: Direction[];
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

  const handleLocateDirection = (dir: Direction) => {
    onMode("capacity");
    window.requestAnimationFrame(() => {
      const calendar = calendarRef.current;
      if (!calendar) return;
      const targetCell = calendar.querySelector<HTMLElement>(`[data-date="${dir.start_date}"]`);
      if (targetCell) {
        calendar.scrollTo({
          left: Math.max(0, targetCell.offsetLeft - calendar.clientWidth / 2 + targetCell.clientWidth / 2),
          behavior: "smooth",
        });
      }
    });
  };

  return (
    <div className="timeline-view">
      <header className="timeline-toolbar">
        <div className="segmented">
          <button className={mode === "forecast" ? "active" : ""} onClick={() => onMode("forecast")}>Forecast</button>
          <button className={mode === "capacity" ? "active" : ""} onClick={() => onMode("capacity")}>Capacity Grid</button>
          <button className={mode === "directions" ? "active" : ""} onClick={() => onMode("directions")}>Direction List</button>
        </div>
        {mode === "capacity" && (
          <div className="date-navigation">
            <button onClick={() => navigate(-1)}>← Quarter</button>
            <button onClick={() => navigate(0)}>Today</button>
            <button onClick={() => navigate(1)}>Quarter →</button>
          </div>
        )}
      </header>
      {mode === "forecast" ? (
        <ForecastView graph={graph} yoncConfig={yoncConfig} />
      ) : mode === "directions" ? (
        <DirectionListView
          directions={directions}
          yoncConfig={yoncConfig}
          onLocateInGrid={handleLocateDirection}
          onRefresh={onRefresh}
          onError={onError}
          onRegisterUndo={onRegisterUndo}
        />
      ) : (
        <TimelineGrid
          timeline={timeline}
          graph={graph}
          yoncConfig={yoncConfig}
          directions={directions}
          selectedId={selectedId}
          calendarRef={calendarRef}
          onSelect={onSelect}
          onRefresh={onRefresh}
          onError={onError}
          onRegisterUndo={onRegisterUndo}
        />
      )}
    </div>
  );
}

interface SplitTabState {
  id: string;
  nodeId: string | null;
  session: SplitSession | null;
  cards: ProposalNode[];
  parentMode: string;
  parentTaskType: string;
  stagedAnnotation: {
    targetTemporaryId: string;
    term: string;
    comment: string;
    field: "title" | "done_when";
  } | null;
  draftMessage: string;
  isSearching: boolean;
  searchQuery: string;
  isLoading?: boolean;
  isGenerating?: boolean;
  isValidated?: boolean;
}

function createTab(nodeId: string | null = null, defaultMode = "💻Focus", defaultTaskType = "Coding"): SplitTabState {
  return {
    id: `tab-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    nodeId,
    session: null,
    cards: [],
    parentMode: defaultMode,
    parentTaskType: defaultTaskType,
    stagedAnnotation: null,
    draftMessage: "",
    isSearching: false,
    searchQuery: "",
    isLoading: nodeId !== null,
    isGenerating: false,
    isValidated: false,
  };
}

function SplitWorkspace({
  graph,
  yoncConfig,
  splitTargetNodeId,
  onClearSplitTarget,
  onRefresh,
  onError,
  onRegisterUndo,
}: {
  graph: GraphResponse;
  yoncConfig: YoncConfig | null;
  splitTargetNodeId: string | null;
  onClearSplitTarget: () => void;
  onRefresh: () => Promise<void>;
  onError: (error: unknown) => void;
  onRegisterUndo: (action: UndoAction) => void;
}) {
  const validTaskTypes = (yoncConfig?.task_types || []).filter((t) => t.name !== "Unknown TYPE");
  const defaultMode = yoncConfig?.modes?.[0]?.mode_name ?? "💻Focus";
  const defaultType = validTaskTypes[0]?.name ?? "Coding";

  // Multi-Tab isolation state - starts completely empty with NO task preloaded!
  const [tabs, setTabs] = useState<SplitTabState[]>(() => {
    return [createTab(null, defaultMode, defaultType)];
  });
  const [activeTabId, setActiveTabId] = useState<string>(() => tabs[0]?.id || "default-tab");
  const [isChatCollapsed, setIsChatCollapsed] = useState<boolean>(false);
  const [commitStatus, setCommitStatus] = useState<"idle" | "saving" | "saved" | "error">("saved");
  const [saveToast, setSaveToast] = useState<string | null>(null);
  const commitTimerRef = useRef<number | null>(null);

  // Word highlight popover state
  const [selectionPopover, setSelectionPopover] = useState<{
    targetTemporaryId: string;
    field: "title" | "done_when";
    term: string;
    x: number;
    y: number;
  } | null>(null);

  // STT recording state
  const [isRecording, setIsRecording] = useState(false);
  const recognitionRef = useRef<any>(null);
  const promptInputRef = useRef<HTMLInputElement | null>(null);
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const searchBoxRef = useRef<HTMLDivElement | null>(null);

  const nodesById = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph.nodes]);

  // Click outside and Escape key to dismiss search box & dropdown
  useEffect(() => {
    const hasSearchingTab = tabs.some((t) => t.isSearching);
    if (!hasSearchingTab) return;

    const handlePointerDown = (e: MouseEvent | TouchEvent) => {
      if (searchBoxRef.current && !searchBoxRef.current.contains(e.target as Node)) {
        setTabs((prev) =>
          prev.map((t) => (t.isSearching ? { ...t, isSearching: false } : t))
        );
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setTabs((prev) =>
          prev.map((t) => (t.isSearching ? { ...t, isSearching: false } : t))
        );
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [tabs]);

  const activeTab = useMemo(() => tabs.find((t) => t.id === activeTabId) || tabs[0], [tabs, activeTabId]);
  const activeTabRef = useRef(activeTab);
  activeTabRef.current = activeTab;
  const activeTabNodeId = activeTab?.nodeId ?? null;
  const hasActiveSession = Boolean(activeTab?.session);

  // Undo & Redo stacks per tab
  const splitUndoStackRef = useRef<{ [tabId: string]: ProposalNode[][] }>({});
  const splitRedoStackRef = useRef<{ [tabId: string]: ProposalNode[][] }>({});
  const lastTypingTimeRef = useRef<number>(0);
  const lastEditedCardRef = useRef<{ tempId: string; field: string } | null>(null);

  const recordCardSnapshot = useCallback((cardsToSave?: ProposalNode[]) => {
    const curTab = activeTabRef.current;
    if (!curTab) return;
    const tabId = curTab.id;
    if (!splitUndoStackRef.current[tabId]) {
      splitUndoStackRef.current[tabId] = [];
    }
    const cards = cardsToSave ?? curTab.cards;
    const snapshot: ProposalNode[] = JSON.parse(JSON.stringify(cards));
    splitUndoStackRef.current[tabId].push(snapshot);
    if (splitUndoStackRef.current[tabId].length > 50) {
      splitUndoStackRef.current[tabId].shift();
    }
    splitRedoStackRef.current[tabId] = [];
  }, []);

  const recordTypingSnapshot = useCallback((tempId: string, field: string) => {
    const now = Date.now();
    const isDifferentTarget =
      !lastEditedCardRef.current ||
      lastEditedCardRef.current.tempId !== tempId ||
      lastEditedCardRef.current.field !== field;
    const isTimeGap = now - lastTypingTimeRef.current > 1200;

    if (isDifferentTarget || isTimeGap) {
      recordCardSnapshot();
      lastEditedCardRef.current = { tempId, field };
    }
    lastTypingTimeRef.current = now;
  }, [recordCardSnapshot]);

  // If a splitTargetNodeId was triggered from Canvas/Inspector, switch or create tab
  useEffect(() => {
    if (!splitTargetNodeId) return;
    setTabs((prev) => {
      const existing = prev.find((t) => t.nodeId === splitTargetNodeId);
      if (existing) {
        setActiveTabId(existing.id);
        return prev;
      }
      const targetNode = graph.nodes.find((n) => n.id === splitTargetNodeId);
      const modeTag = targetNode?.tags?.["Modes"] || targetNode?.tags?.["Mode"];
      const mVal = Array.isArray(modeTag) ? modeTag[0] : (typeof modeTag === "string" ? modeTag : defaultMode);
      const typeTag = targetNode?.tags?.["Task Type"];
      const tVal = Array.isArray(typeTag) ? typeTag[0] : (typeof typeTag === "string" ? typeTag : defaultType);
      const newTab = createTab(splitTargetNodeId, mVal, tVal);
      setActiveTabId(newTab.id);
      // Clean up any initial empty search tab that was never used
      const cleaned = prev.filter((t) => t.nodeId !== null);
      return [...cleaned, newTab];
    });
    onClearSplitTarget();
  }, [splitTargetNodeId, graph.nodes, defaultMode, defaultType, onClearSplitTarget]);

  // Load backend session for active tab ONLY when a task is selected
  useEffect(() => {
    if (!activeTabNodeId || hasActiveSession) return;
    let cancelled = false;

    setTabs((prev) =>
      prev.map((t) => (t.id === activeTab.id && !t.isLoading ? { ...t, isLoading: true } : t))
    );

    (async () => {
      try {
        const openSessions = await api.listSplitSessions({ parent_node_id: activeTabNodeId, state: "open" });
        const session = openSessions.length > 0 ? openSessions[0] : await api.startSplit(activeTabNodeId);
        if (cancelled) return;
        const existingChildren = graph.nodes.filter((n) => n.parent_id === activeTabNodeId);
        const targetNode = graph.nodes.find((n) => n.id === activeTabNodeId);
        const targetLvl = targetNode?.wbs_level ?? (targetNode?.work_type === "GOAL" ? 1 : targetNode?.work_type === "DELIVERABLE" ? 2 : targetNode?.work_type === "WORK_PACKAGE" ? 3 : 1);
        const fallbackChildWorkType = targetLvl === 1 ? "DELIVERABLE" : targetLvl === 2 ? "WORK_PACKAGE" : "ACTION";
        let initialCards: ProposalNode[] = [];
        if (session.proposal?.nodes && session.proposal.nodes.length > 0) {
          initialCards = session.proposal.nodes;
        } else if (existingChildren.length > 0) {
          const validTypes = (yoncConfig?.task_types || []).filter((t) => t.name !== "Unknown TYPE");
          const defaultFallbackType = validTypes[0]?.name || "Coding";
          const preferredType =
            activeTab.parentTaskType && activeTab.parentTaskType !== "Unknown TYPE"
              ? activeTab.parentTaskType
              : defaultFallbackType;

          initialCards = existingChildren.map((c) => {
            const modeTag = c.tags?.["Modes"] || c.tags?.["Mode"];
            const mVal = Array.isArray(modeTag) ? modeTag[0] : (typeof modeTag === "string" ? modeTag : activeTab.parentMode);
            const typeTag = c.tags?.["Task Type"] || c.tags?.["task_type"];
            const rawTVal = Array.isArray(typeTag) ? typeTag[0] : (typeof typeTag === "string" ? typeTag : preferredType);
            const tVal = rawTVal && rawTVal !== "Unknown TYPE" ? rawTVal : preferredType;
            return {
              temporary_id: c.id,
              title: c.title,
              work_type: c.work_type || fallbackChildWorkType,
              start_cue: c.start_cue || "前置输入准备完毕",
              done_when: c.done_when || (c.title ? `Done: 完成“${c.title}”并交付明确成果。` : "Done: 明确可检查的完成判定。"),
              estimated_effort_minutes: c.estimated_effort_minutes ?? 45,
              required: c.required ?? true,
              tags: { Modes: [mVal], "Task Type": [tVal] },
              status: c.status || "TODO",
            };
          });
        } else {
          initialCards = [
            {
              temporary_id: `temp-${Date.now()}-1`,
              title: "定义核心任务与架构分解",
              work_type: fallbackChildWorkType,
              start_cue: "前置输入准备完毕",
              done_when: "Done: 输出通过单测的代码与设计规格。",
              estimated_effort_minutes: 45,
              required: true,
              tags: { Modes: [activeTab.parentMode], "Task Type": [activeTab.parentTaskType] },
              status: "TODO",
            },
            {
              temporary_id: `temp-${Date.now()}-2`,
              title: "实现核心功能与集成验证",
              work_type: fallbackChildWorkType,
              start_cue: "核心架构定义完成",
              done_when: "Done: 通过自动化端到端测试。",
              estimated_effort_minutes: 60,
              required: true,
              tags: { Modes: [activeTab.parentMode], "Task Type": [activeTab.parentTaskType] },
              status: "TODO",
            },
          ];
        }

        let activeSession = session;
        if ((!session.proposal || !session.proposal.nodes?.length) && initialCards.length > 0) {
          try {
            const updated = await api.updateSplitProposal(session.id, initialCards);
            activeSession = {
              ...session,
              proposal: updated.proposal,
              current_proposal_version: updated.proposal?.version ?? session.current_proposal_version,
            };
          } catch (e) {
            console.warn("Could not immediately sync initial proposal to backend:", e);
          }
        }

        setTabs((prev) =>
          prev.map((t) => (t.id === activeTab.id ? { ...t, session: activeSession, cards: initialCards, isLoading: false } : t))
        );
      } catch (err) {
        if (!cancelled) {
          setTabs((prev) => prev.map((t) => (t.id === activeTab.id ? { ...t, isLoading: false } : t)));
        }
        console.error("Failed to load split session:", err);
        onError(err);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [activeTabNodeId, hasActiveSession, activeTab?.id, activeTab?.parentMode, activeTab?.parentTaskType, onError]);

  // Auto-scroll chat history when messages change
  useEffect(() => {
    if (chatScrollRef.current) {
      chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
    }
  }, [activeTab?.session?.messages]);

  // Active target node
  const activeNode = useMemo(() => {
    if (!activeTab?.nodeId) return null;
    return graph.nodes.find((n) => n.id === activeTab.nodeId) || null;
  }, [graph.nodes, activeTab?.nodeId]);

  // Strict Candidate Filtering: Exclude L4 actions (wbs_level === 4 or work_type === "ACTION")
  // Sorted by WBS level ascending (L1 -> L2 -> L3), then by title
  const candidateBlocks = useMemo(() => {
    return graph.nodes
      .filter((node) => node.wbs_level !== 4 && node.work_type !== "ACTION")
      .sort((a, b) => {
        const lvlA = a.wbs_level ?? 999;
        const lvlB = b.wbs_level ?? 999;
        if (lvlA !== lvlB) return lvlA - lvlB;
        return a.title.localeCompare(b.title);
      });
  }, [graph.nodes]);

  const filteredCandidates = useMemo(() => {
    const q = activeTab?.searchQuery?.toLowerCase().trim() || "";
    if (!q) return candidateBlocks;
    return candidateBlocks.filter((b) => {
      if (b.title.toLowerCase().includes(q)) return true;
      if (b.description && b.description.toLowerCase().includes(q)) return true;
      const theme = themeInfoForNode(b, yoncConfig, nodesById);
      if (theme && theme.name.toLowerCase().includes(q)) return true;
      return false;
    });
  }, [candidateBlocks, activeTab?.searchQuery, yoncConfig, nodesById]);

  // Tab management
  const handleSelectTab = (tabId: string) => {
    setActiveTabId(tabId);
    setSelectionPopover(null);
  };

  const handleCloseTab = (tabIdToClose: string) => {
    if (tabs.length <= 1) {
      const resetTab = createTab(null, defaultMode, defaultType);
      setTabs([resetTab]);
      setActiveTabId(resetTab.id);
      return;
    }
    const nextTabs = tabs.filter((t) => t.id !== tabIdToClose);
    setTabs(nextTabs);
    if (activeTabId === tabIdToClose) {
      setActiveTabId(nextTabs[nextTabs.length - 1].id);
    }
  };

  const handleNewTab = () => {
    const newTab = { ...createTab(null, defaultMode, defaultType), isSearching: true };
    setTabs((prev) => [...prev, newTab]);
    setActiveTabId(newTab.id);
  };

  const handleSelectBlock = (node: GraphNode) => {
    const modeTag = node.tags?.["Modes"] || node.tags?.["Mode"];
    const mVal = Array.isArray(modeTag) ? modeTag[0] : (typeof modeTag === "string" ? modeTag : defaultMode);
    const typeTag = node.tags?.["Task Type"];
    const tVal = Array.isArray(typeTag) ? typeTag[0] : (typeof typeTag === "string" ? typeTag : defaultType);

    setTabs((prev) =>
      prev.map((t) =>
        t.id === activeTab.id
          ? {
              ...t,
              nodeId: node.id,
              session: null,
              cards: [],
              parentMode: mVal,
              parentTaskType: tVal,
              isSearching: false,
              searchQuery: "",
              isLoading: true,
              isGenerating: false,
              isValidated: false,
            }
          : t
      )
    );
  };

  // Card text selection for word highlight annotation
  const handleProposalSelection = () => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) {
      setSelectionPopover(null);
      return;
    }
    const text = sel.toString().trim();
    if (!text || text.length < 2 || text.length > 80) {
      setSelectionPopover(null);
      return;
    }
    const anchor = sel.anchorNode;
    const parent = anchor instanceof HTMLElement ? anchor : anchor?.parentElement;
    const cardEl = parent?.closest("[data-temp-id]") as HTMLElement | null;
    const fieldEl = parent?.closest("[data-field]") as HTMLElement | null;
    if (!cardEl) {
      setSelectionPopover(null);
      return;
    }
    const tempId = cardEl.getAttribute("data-temp-id") || "";
    const field = (fieldEl?.getAttribute("data-field") || "title") as "title" | "done_when";
    const range = sel.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    setSelectionPopover({
      targetTemporaryId: tempId,
      field,
      term: text,
      x: rect.left + rect.width / 2,
      y: rect.top - 8,
    });
  };

  const handleOpenAnnotationComposer = () => {
    if (!selectionPopover) return;
    const term = selectionPopover.term;
    const comment = window.prompt(`对高亮词 “${term}” 输入批注指令：\n(指令将暂存夹入下方输入框，按 Send 一并提交执行)`);
    if (comment && comment.trim()) {
      setTabs((prev) =>
        prev.map((t) =>
          t.id === activeTab.id
            ? {
                ...t,
                stagedAnnotation: {
                  targetTemporaryId: selectionPopover.targetTemporaryId,
                  term,
                  comment: comment.trim(),
                  field: selectionPopover.field,
                },
              }
            : t
        )
      );
      window.getSelection()?.removeAllRanges();
      setSelectionPopover(null);
      promptInputRef.current?.focus();
    }
  };

  const handleClearStagedAnnotation = () => {
    setTabs((prev) =>
      prev.map((t) => (t.id === activeTab.id ? { ...t, stagedAnnotation: null } : t))
    );
  };

  // Voice STT Toggle
  const toggleSTT = () => {
    if (isRecording) {
      if (recognitionRef.current) {
        try { recognitionRef.current.stop(); } catch {}
      }
      setIsRecording(false);
      return;
    }
    const SpeechRec = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (SpeechRec) {
      try {
        const rec = new SpeechRec();
        rec.lang = "zh-CN";
        rec.continuous = false;
        rec.interimResults = false;
        rec.onresult = (evt: any) => {
          const transcript = evt.results?.[0]?.[0]?.transcript || "";
          if (transcript) {
            setIsChatCollapsed(false);
            setTabs((prev) =>
              prev.map((t) => (t.id === activeTab.id ? { ...t, draftMessage: transcript } : t))
            );
          }
          setIsRecording(false);
        };
        rec.onerror = () => setIsRecording(false);
        rec.onend = () => setIsRecording(false);
        recognitionRef.current = rec;
        rec.start();
        setIsRecording(true);
        return;
      } catch {}
    }
    // Simulation fallback
    setIsRecording(true);
    window.setTimeout(() => {
      setIsRecording(false);
      setIsChatCollapsed(false);
      setTabs((prev) =>
        prev.map((t) =>
          t.id === activeTab.id
            ? {
                ...t,
                draftMessage: t.draftMessage ? `${t.draftMessage}，并将模式设为Focus` : "按上述批注拆分，并将模式设为Focus",
              }
            : t
        )
      );
    }, 2000);
  };

  // Send Hermes Prompt
  const handleSendPrompt = async () => {
    if (!activeTab.session) return;
    const userText = activeTab.draftMessage.trim();
    const staged = activeTab.stagedAnnotation;
    if (!userText && !staged) return;

    setIsChatCollapsed(false);

    let combinedContent = userText;
    const annotations: SplitAnnotation[] = [];
    if (staged) {
      annotations.push({
        target_temporary_id: staged.targetTemporaryId,
        field: staged.field,
        highlighted_text: staged.term,
        comment: staged.comment,
      });
      combinedContent = `【批注命令】“${staged.term}” → ${staged.comment}${userText ? `；补充要求：${userText}` : ""}`;
    }

    // Immediately clear staged chip & input ("全部不见了") and set isGenerating
    setTabs((prev) =>
      prev.map((t) => (t.id === activeTab.id ? { ...t, draftMessage: "", stagedAnnotation: null, isGenerating: true, isValidated: false } : t))
    );

    try {
      await api.splitMessage(activeTab.session.id, combinedContent, annotations);
      const updated = await api.split(activeTab.session.id);
      const newCards = updated.proposal?.nodes?.length ? updated.proposal.nodes : activeTab.cards;
      recordCardSnapshot();
      setTabs((prev) =>
        prev.map((t) =>
          t.id === activeTab.id
            ? {
                ...t,
                session: updated,
                cards: newCards,
                isGenerating: false,
              }
            : t
        )
      );
      scheduleAutoCommit(newCards, 100);
    } catch (err) {
      setTabs((prev) =>
        prev.map((t) => (t.id === activeTab.id ? { ...t, isGenerating: false } : t))
      );
      onError(err);
    }
  };

  // Validate / Commit / Discard
  const handleValidate = async () => {
    if (!activeTab.session) return;
    try {
      const updated = await api.updateSplitProposal(activeTab.session.id, activeTab.cards);
      setTabs((prev) =>
        prev.map((t) =>
          t.id === activeTab.id && t.session
            ? {
                ...t,
                session: {
                  ...t.session,
                  proposal: updated.proposal,
                  current_proposal_version: updated.proposal?.version ?? t.session.current_proposal_version,
                },
              }
            : t
        )
      );
      const res = await api.validateSplit(activeTab.session.id);
      if (res.valid) {
        setTabs((prev) =>
          prev.map((t) => (t.id === activeTab.id ? { ...t, isValidated: true } : t))
        );
        window.alert("检查通过：提案具备明确完成条件，且项目图无循环依赖。");
      } else {
        setTabs((prev) =>
          prev.map((t) => (t.id === activeTab.id ? { ...t, isValidated: false } : t))
        );
        const errorMsgs = res.errors?.map((e: any) => e.message_key || e.code).join(", ") || "";
        window.alert(`提案尚未通过检查（${errorMsgs}），请继续调整完成条件或依赖关系。`);
      }
    } catch (err) {
      onError(err);
    }
  };

  // Auto-Commit Engine: commits every change automatically to split proposal and formal graph
  const performAutoCommit = useCallback(
    async (cardsToCommit?: ProposalNode[]) => {
      const curTab = activeTabRef.current;
      if (!curTab?.session || !curTab?.nodeId) return;
      const cards = cardsToCommit || curTab.cards;
      if (!cards || cards.length === 0) return;

      setCommitStatus("saving");
      try {
        const updated = await api.updateSplitProposal(curTab.session.id, cards);
        const versionToCommit = updated.proposal?.version ?? curTab.session.current_proposal_version ?? 1;
        const res = await api.commitSplit(curTab.session.id, graph.graph_version, versionToCommit);

        // If newly generated temporary IDs were mapped to real IDs, update local cards
        if (res.temporary_id_map && Object.keys(res.temporary_id_map).length > 0) {
          const map = res.temporary_id_map;
          setTabs((prev) =>
            prev.map((t) => {
              if (t.id !== curTab.id) return t;
              return {
                ...t,
                cards: t.cards.map((c) => {
                  const realId = map[c.temporary_id];
                  return realId ? { ...c, temporary_id: realId } : c;
                }),
              };
            })
          );
        }

        // Quietly sync version state
        setTabs((prev) =>
          prev.map((t) =>
            t.id === curTab.id && t.session
              ? {
                  ...t,
                  session: {
                    ...t.session,
                    proposal: updated.proposal,
                    current_proposal_version: updated.proposal?.version ?? t.session.current_proposal_version,
                  },
                }
              : t
          )
        );

        onRegisterUndo({ kind: "batch", batchId: res.operation_batch.id });
        await onRefresh();
        setCommitStatus("saved");
      } catch (err) {
        console.error("Auto-commit failed:", err);
        setCommitStatus("error");
      }
    },
    [graph.graph_version, onRefresh, onRegisterUndo]
  );

  const scheduleAutoCommit = useCallback(
    (updatedCards?: ProposalNode[], delayMs = 700) => {
      setCommitStatus("saving");
      if (commitTimerRef.current) {
        window.clearTimeout(commitTimerRef.current);
      }
      commitTimerRef.current = window.setTimeout(() => {
        performAutoCommit(updatedCards);
      }, delayMs);
    },
    [performAutoCommit]
  );

  useEffect(() => {
    return () => {
      if (commitTimerRef.current) {
        window.clearTimeout(commitTimerRef.current);
      }
    };
  }, []);

  const performSplitUndo = useCallback(() => {
    const curTab = activeTabRef.current;
    if (!curTab) return false;
    const tabId = curTab.id;
    const stack = splitUndoStackRef.current[tabId];
    if (!stack || stack.length === 0) {
      return false;
    }
    const prevCards = stack.pop();
    if (!prevCards) return false;

    if (!splitRedoStackRef.current[tabId]) {
      splitRedoStackRef.current[tabId] = [];
    }
    splitRedoStackRef.current[tabId].push(JSON.parse(JSON.stringify(curTab.cards)));

    lastEditedCardRef.current = null;

    setTabs((prev) =>
      prev.map((t) => (t.id === tabId ? { ...t, cards: prevCards } : t))
    );
    scheduleAutoCommit(prevCards, 100);
    setSaveToast("已撤销 (Ctrl+Z)");
    const timer = window.setTimeout(() => setSaveToast(null), 1500);
    return true;
  }, [scheduleAutoCommit]);

  const performSplitRedo = useCallback(() => {
    const curTab = activeTabRef.current;
    if (!curTab) return false;
    const tabId = curTab.id;
    const stack = splitRedoStackRef.current[tabId];
    if (!stack || stack.length === 0) {
      return false;
    }
    const nextCards = stack.pop();
    if (!nextCards) return false;

    if (!splitUndoStackRef.current[tabId]) {
      splitUndoStackRef.current[tabId] = [];
    }
    splitUndoStackRef.current[tabId].push(JSON.parse(JSON.stringify(curTab.cards)));

    lastEditedCardRef.current = null;

    setTabs((prev) =>
      prev.map((t) => (t.id === tabId ? { ...t, cards: nextCards } : t))
    );
    scheduleAutoCommit(nextCards, 100);
    setSaveToast("已重做 (Ctrl+Y)");
    const timer = window.setTimeout(() => setSaveToast(null), 1500);
    return true;
  }, [scheduleAutoCommit]);

  // Global shortcuts in Split Workspace: Ctrl+S (save), Ctrl+Z (undo), Ctrl+Y (redo)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl+S / Cmd+S: Immediate commit
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        performAutoCommit();
        setSaveToast("已提交 (Ctrl+S)");
        const timer = window.setTimeout(() => setSaveToast(null), 1500);
        return () => window.clearTimeout(timer);
      }

      // Ctrl+Z / Cmd+Z (without Shift): Undo
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey) {
        const curTab = activeTabRef.current;
        if (curTab && splitUndoStackRef.current[curTab.id]?.length > 0) {
          e.preventDefault();
          e.stopPropagation();
          performSplitUndo();
        }
      }

      // Ctrl+Y / Cmd+Shift+Z / Ctrl+Shift+Z: Redo
      if (
        ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") ||
        ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "z")
      ) {
        const curTab = activeTabRef.current;
        if (curTab && splitRedoStackRef.current[curTab.id]?.length > 0) {
          e.preventDefault();
          e.stopPropagation();
          performSplitRedo();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [performAutoCommit, performSplitUndo, performSplitRedo]);

  const handleDiscard = async () => {
    if (!activeTab.session) return;
    if (!window.confirm("放弃当前拆分提案？")) return;
    try {
      await api.discardSplit(activeTab.session.id);
      handleCloseTab(activeTab.id);
    } catch (err) {
      onError(err);
    }
  };

  // Card Mutations with debounced/immediate Auto-Commit and Undo Snapshots
  const updateCardTitle = (tempId: string, title: string) => {
    recordTypingSnapshot(tempId, "title");
    const updatedCards = activeTab.cards.map((c) => (c.temporary_id === tempId ? { ...c, title } : c));
    setTabs((prev) =>
      prev.map((t) => (t.id === activeTab.id ? { ...t, cards: updatedCards } : t))
    );
    scheduleAutoCommit(updatedCards, 800);
  };

  const updateCardDesc = (tempId: string, done_when: string) => {
    recordTypingSnapshot(tempId, "done_when");
    const updatedCards = activeTab.cards.map((c) => (c.temporary_id === tempId ? { ...c, done_when } : c));
    setTabs((prev) =>
      prev.map((t) => (t.id === activeTab.id ? { ...t, cards: updatedCards } : t))
    );
    scheduleAutoCommit(updatedCards, 800);
  };

  const updateCardEffort = (tempId: string, estimated_effort_minutes: number) => {
    recordCardSnapshot();
    const updatedCards = activeTab.cards.map((c) =>
      c.temporary_id === tempId ? { ...c, estimated_effort_minutes } : c
    );
    setTabs((prev) =>
      prev.map((t) => (t.id === activeTab.id ? { ...t, cards: updatedCards } : t))
    );
    scheduleAutoCommit(updatedCards, 500);
  };

  const updateCardMode = (tempId: string, modeName: string) => {
    recordCardSnapshot();
    const updatedCards = activeTab.cards.map((c) =>
      c.temporary_id === tempId ? { ...c, tags: { ...(c.tags || {}), Modes: [modeName] } } : c
    );
    setTabs((prev) =>
      prev.map((t) => (t.id === activeTab.id ? { ...t, cards: updatedCards } : t))
    );
    scheduleAutoCommit(updatedCards, 100);
  };

  const updateCardTaskType = (tempId: string, typeName: string) => {
    recordCardSnapshot();
    const updatedCards = activeTab.cards.map((c) =>
      c.temporary_id === tempId ? { ...c, tags: { ...(c.tags || {}), "Task Type": [typeName] } } : c
    );
    setTabs((prev) =>
      prev.map((t) => (t.id === activeTab.id ? { ...t, cards: updatedCards } : t))
    );
    scheduleAutoCommit(updatedCards, 100);
  };

  const handleMoveCard = (index: number, direction: -1 | 1) => {
    const targetIdx = index + direction;
    if (targetIdx < 0 || targetIdx >= activeTab.cards.length) return;
    recordCardSnapshot();
    const newCards = [...activeTab.cards];
    const [removed] = newCards.splice(index, 1);
    newCards.splice(targetIdx, 0, removed);
    setTabs((prev) =>
      prev.map((t) => (t.id === activeTab.id ? { ...t, cards: newCards } : t))
    );
    scheduleAutoCommit(newCards, 100);
  };

  const handleDuplicateCard = (tempId: string) => {
    const idx = activeTab.cards.findIndex((c) => c.temporary_id === tempId);
    if (idx === -1) return;
    recordCardSnapshot();
    const targetCard = activeTab.cards[idx];
    const clone: ProposalNode = {
      ...targetCard,
      temporary_id: `temp-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      title: targetCard.title ? `${targetCard.title} (副本)` : "新子任务",
      status: targetCard.status || "TODO",
    };
    const newCards = [...activeTab.cards];
    newCards.splice(idx + 1, 0, clone);
    setTabs((prev) =>
      prev.map((t) => (t.id === activeTab.id ? { ...t, cards: newCards } : t))
    );
    scheduleAutoCommit(newCards, 100);
  };

  const handleDeleteCard = (tempId: string) => {
    recordCardSnapshot();
    const newCards = activeTab.cards.filter((c) => c.temporary_id !== tempId);
    setTabs((prev) =>
      prev.map((t) => (t.id === activeTab.id ? { ...t, cards: newCards } : t))
    );
    scheduleAutoCommit(newCards, 100);
  };

  const handleToggleCardDone = async (cardTempId: string) => {
    const targetCard = activeTab.cards.find((c) => c.temporary_id === cardTempId);
    if (!targetCard) return;
    recordCardSnapshot();
    const existingNode = nodesById.get(cardTempId);
    const currentlyDone = targetCard.status === "DONE" || existingNode?.status === "DONE";
    const nextStatus: Status = currentlyDone ? "TODO" : "DONE";

    const updatedCards = activeTab.cards.map((c) =>
      c.temporary_id === cardTempId ? { ...c, status: nextStatus } : c
    );
    setTabs((prev) =>
      prev.map((t) => (t.id === activeTab.id ? { ...t, cards: updatedCards } : t))
    );

    if (existingNode) {
      try {
        await api.transition(existingNode.id, currentlyDone ? "reopen" : "done", graph.graph_version);
        onRefresh();
      } catch (err) {
        console.warn("Could not transition existing node status:", err);
      }
    }
    scheduleAutoCommit(updatedCards, 100);
  };

  const handleAddGhostCard = () => {
    recordCardSnapshot();
    const validTypes = (yoncConfig?.task_types || []).filter((t) => t.name !== "Unknown TYPE");
    const defaultFallbackType = validTypes[0]?.name || "Coding";
    const defaultType =
      activeTab.parentTaskType && activeTab.parentTaskType !== "Unknown TYPE"
        ? activeTab.parentTaskType
        : defaultFallbackType;

    const parentLvl = activeNode?.wbs_level ?? (activeNode?.work_type === "GOAL" ? 1 : activeNode?.work_type === "DELIVERABLE" ? 2 : activeNode?.work_type === "WORK_PACKAGE" ? 3 : 1);
    const childWorkType = parentLvl === 1 ? "DELIVERABLE" : parentLvl === 2 ? "WORK_PACKAGE" : "ACTION";

    const newCard: ProposalNode = {
      temporary_id: `temp-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      title: "",
      work_type: childWorkType,
      start_cue: "前置条件满足",
      done_when: "",
      estimated_effort_minutes: 45,
      required: true,
      status: "TODO",
      tags: {
        Modes: [activeTab.parentMode],
        "Task Type": [defaultType],
      },
    };
    const newCards = [...activeTab.cards, newCard];
    setTabs((prev) =>
      prev.map((t) =>
        t.id === activeTab.id ? { ...t, cards: newCards } : t
      )
    );
    scheduleAutoCommit(newCards, 100);
  };

  // Helper for tab level badge class
  const getBadgeClass = (level: number | null) => {
    if (level === 1) return "l1";
    if (level === 2) return "l2";
    if (level === 4) return "l4";
    return "l3";
  };

  const allActionable = activeTab.cards.length > 0 && activeTab.cards.every((c) => !!c.done_when?.trim());
  const totalSubtasksMinutes = activeTab.cards.reduce((acc, c) => acc + (c.estimated_effort_minutes || 0), 0);
  const parentEffortMinutes = activeNode?.estimated_effort_minutes || 0;
  const effectiveEffortMinutes = parentEffortMinutes > 0 ? parentEffortMinutes : totalSubtasksMinutes;

  return (
    <div className="split-workspace" onMouseUp={handleProposalSelection}>
      {/* 1. TOP TAB STRIP WITH INLINE FILTER */}
      <div className="split-tabs-bar">
        {tabs.map((tab, idx) => {
          const tabNode = tab.nodeId ? graph.nodes.find((n) => n.id === tab.nodeId) : null;
          const isActive = tab.id === activeTab.id;

          if (tab.isSearching) {
            return (
              <div key={tab.id} ref={searchBoxRef} className="split-tab-search-box">
                <span>🔍</span>
                <input
                  autoFocus
                  type="text"
                  placeholder="Filter block to split (L1-L3 or theme)..."
                  value={tab.searchQuery}
                  onChange={(e) => {
                    const val = e.target.value;
                    setTabs((prev) =>
                      prev.map((t) => (t.id === tab.id ? { ...t, searchQuery: val } : t))
                    );
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") {
                      setTabs((prev) =>
                        prev.map((t) => (t.id === tab.id ? { ...t, isSearching: false } : t))
                      );
                    }
                  }}
                />
                <button
                  type="button"
                  className="split-tab-close"
                  onClick={(e) => {
                    e.stopPropagation();
                    setTabs((prev) =>
                      prev.map((t) => (t.id === tab.id ? { ...t, isSearching: false } : t))
                    );
                  }}
                  title="取消搜索"
                >
                  ×
                </button>

                {/* Dropdown with L4 strictly excluded */}
                <div className="split-tab-dropdown">
                  <div className="split-dropdown-header">
                    <span>Select Block to Split:</span>
                    <span style={{ color: "#f59e0b", fontWeight: "bold" }}>L4 Actions Excluded</span>
                  </div>
                  <div className="split-dropdown-list">
                    {filteredCandidates.map((cand) => {
                      const lvl = cand.wbs_level ?? 2;
                      const candTheme = themeInfoForNode(cand, yoncConfig, nodesById);
                      return (
                        <div
                          key={cand.id}
                          className="split-dropdown-item"
                          onClick={() => handleSelectBlock(cand)}
                        >
                          <div className="split-dropdown-item-header">
                            <span className={`split-tab-badge ${getBadgeClass(lvl)}`}>L{lvl}</span>
                            {candTheme && (
                              <span
                                className="node-theme-pill"
                                style={{ "--theme-color": candTheme.color } as React.CSSProperties}
                                title={`Theme: ${candTheme.name}`}
                              >
                                {candTheme.name}
                              </span>
                            )}
                            <span className="split-dropdown-item-title" title={cand.title}>
                              {cand.title}
                            </span>
                          </div>
                          {cand.description && (
                            <div className="split-dropdown-item-desc" title={cand.description}>
                              :: {cand.description}
                            </div>
                          )}
                        </div>
                      );
                    })}
                    {filteredCandidates.length === 0 && (
                      <div style={{ padding: "12px", textAlign: "center", color: "#64748b", fontSize: "11px" }}>
                        无匹配的 L1-L3 节点
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          }

          const lvl = tabNode?.wbs_level ?? 2;
          const isTabActionable = tab.cards.length > 0 && tab.cards.every((c) => !!c.done_when?.trim());

          return (
            <div
              key={tab.id}
              className={`split-tab-item ${isActive ? "active" : ""}`}
              onClick={() => {
                handleSelectTab(tab.id);
                if (!tab.nodeId) {
                  setTabs((prev) => prev.map((t) => (t.id === tab.id ? { ...t, isSearching: true } : t)));
                }
              }}
              title={
                !tab.nodeId
                  ? "未选择任务，点击选择"
                  : tab.isLoading
                  ? "正在从数据库恢复拆分会话..."
                  : tab.isGenerating
                  ? "Hermes 正在生成拆分提案..."
                  : tab.isValidated
                  ? "提案已通过校验，可直接提交"
                  : isTabActionable
                  ? `拆分已恢复就绪 · Actionable 100% (${tab.cards.length}项子任务)`
                  : `草稿编辑中 (${tab.cards.length}项子任务，待完善完成标准)`
              }
            >
              <span className={`split-tab-badge ${tabNode ? getBadgeClass(lvl) : "l2"}`}>
                {tabNode ? `L${lvl}` : "选择"}
              </span>
              <span className="split-tab-title" title={tabNode ? `${tabNode.title}${tabNode.description ? ` (${tabNode.description})` : ""}` : `Tab ${idx + 1}`}>
                {tabNode ? tabNode.title : `Tab ${idx + 1} (点击选择任务)`}
              </span>
              {tabNode && (() => {
                const t = themeInfoForNode(tabNode, yoncConfig, nodesById);
                return t ? (
                  <span
                    className="split-tab-theme-dot"
                    style={{
                      width: "6px",
                      height: "6px",
                      borderRadius: "50%",
                      backgroundColor: t.color,
                      flexShrink: 0,
                    }}
                    title={`Theme: ${t.name}`}
                  />
                ) : null;
              })()}

              {/* Status Symbol on Tab */}
              {tab.nodeId && (
                <div className="split-tab-status-wrap">
                  {tab.isLoading ? (
                    <span className="split-tab-status status-loading" title="正在恢复会话...">
                      🔄
                    </span>
                  ) : tab.isGenerating ? (
                    <span className="split-tab-status status-generating" title="Hermes 正在生成...">
                      ⚡
                    </span>
                  ) : tab.isValidated ? (
                    <span className="split-tab-status status-validated" title="已通过校验">
                      🛡️✓
                    </span>
                  ) : isTabActionable ? (
                    <span className="split-tab-status status-ready" title="已就绪 · Actionable 100%">
                      🟢
                    </span>
                  ) : (
                    <span className="split-tab-status status-draft" title="草稿编辑中">
                      📝
                    </span>
                  )}

                  {!tab.isLoading && tab.cards.length > 0 && (
                    <span className="split-tab-count">
                      {tab.cards.length}项
                    </span>
                  )}
                </div>
              )}

              <button
                type="button"
                className="split-tab-close"
                onClick={(e) => {
                  e.stopPropagation();
                  handleCloseTab(tab.id);
                }}
                title="关闭标签页"
              >
                ×
              </button>
            </div>
          );
        })}

        <button type="button" className="split-new-tab-btn" onClick={handleNewTab} title="新建拆分标签页">
          <span className="plus">+</span>
          <span>New Tab</span>
        </button>
      </div>

      {/* 2. ACTIVE TASK ATTRIBUTES BAR */}
      <div className="split-active-bar">
        <div className="split-active-title">
          <div className="split-active-row-content">
            {activeNode && (
              <span className={`split-tab-badge ${getBadgeClass(activeNode.wbs_level ?? 1)}`}>
                L{activeNode.wbs_level ?? 1}
              </span>
            )}
            {activeNode && (() => {
              const theme = themeInfoForNode(activeNode, yoncConfig, nodesById);
              return theme ? (
                <span
                  className="node-theme-pill"
                  style={{
                    "--theme-color": theme.color,
                    fontSize: "11px",
                    padding: "2px 8px",
                    maxWidth: "180px",
                    borderRadius: "6px",
                  } as React.CSSProperties}
                  title={`Theme: ${theme.name}`}
                >
                  {theme.name}
                </span>
              ) : null;
            })()}
            <h2 className="split-active-h2">
              <span>{activeNode?.title || (activeTab.nodeId ? "加载中..." : "未选择拆分目标任务（请在上方选择）")}</span>
            </h2>
            {activeNode?.description && (
              <span
                className="split-active-desc-text"
                title={activeNode.description}
              >
                :: {activeNode.description}
              </span>
            )}
          </div>

          {!activeNode && !activeTab.nodeId && (
            <button
              type="button"
              className="split-select-target-btn"
              onClick={() => {
                setTabs((prev) =>
                  prev.map((t) => (t.id === activeTab.id ? { ...t, isSearching: true } : t))
                );
              }}
              style={{
                background: "#1e1438",
                border: "1px solid #7c3aed",
                color: "#c084fc",
                borderRadius: "6px",
                padding: "2px 10px",
                fontSize: "11px",
                cursor: "pointer",
                fontWeight: 600,
              }}
            >
              点击选择拆分任务
            </button>
          )}
        </div>

        {activeNode && (
          <div className="split-active-right">
            <span className="split-proposal-tag count-tag">
              {activeTab.cards.length} 项子任务
            </span>
            <span style={{ fontSize: "11px", color: "#94a3b8" }}>
              · Est: {effectiveEffortMinutes > 0 ? `${(effectiveEffortMinutes / 60).toFixed(1)}h` : "待估算"}
            </span>
          </div>
        )}
      </div>

      {/* 3. MIDDLE SCROLLABLE PROPOSAL TREE + GHOST CARD */}
      <div className="split-proposal-scroll">
        <div className="split-proposal-header">
          <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
            <h3>Proposal Decomposition Tree</h3>
            {activeTab.nodeId && totalSubtasksMinutes > 0 && (
              <span className="split-proposal-tag effort-tag" title="子任务总预估工时">
                ⏱️ 总计 {(totalSubtasksMinutes / 60).toFixed(1)}h
              </span>
            )}
          </div>
          <span className="hint">
            {activeTab.nodeId
              ? ""
              : "（请先在上方标签栏选择需要拆分的任务）"}
          </span>
        </div>

        {activeTab.nodeId ? (
          <div className="split-cards-container">
            {activeTab.cards.map((card, index) => {
              const validTypes = (yoncConfig?.task_types || []).filter((t) => t.name !== "Unknown TYPE");
              const defaultFallbackTypeName = validTypes[0]?.name || "Coding";
              const preferredParentType =
                activeTab.parentTaskType && activeTab.parentTaskType !== "Unknown TYPE"
                  ? activeTab.parentTaskType
                  : defaultFallbackTypeName;

              const cardMode =
                (card.tags?.["Modes"] as string[])?.[0] ||
                (card.tags?.["Mode"] as string) ||
                activeTab.parentMode;

              const rawTaskType =
                (card.tags?.["Task Type"] as string[])?.[0] ||
                (card.tags?.["Task Type"] as string) ||
                preferredParentType;

              const cardTaskType = rawTaskType === "Unknown TYPE" ? preferredParentType : rawTaskType;
              const cardLvl =
                card.work_type === "GOAL"
                  ? 1
                  : card.work_type === "DELIVERABLE"
                  ? 2
                  : card.work_type === "WORK_PACKAGE"
                  ? 3
                  : card.work_type === "ACTION"
                  ? 4
                  : Math.min(4, (activeNode?.wbs_level ?? 1) + 1);

              const existingNode = nodesById.get(card.temporary_id);
              const isCardDone = card.status === "DONE" || existingNode?.status === "DONE";

              return (
                <div
                  key={card.temporary_id}
                  data-temp-id={card.temporary_id}
                  className={`split-subtask-card ${isCardDone ? "is-done" : ""}`}
                >
                  {/* ROW 1: Index + Title Input + Actionable Status + Quick Actions */}
                  <div className="split-card-row-1">
                    <div className="split-card-title-wrap">
                      <button
                        type="button"
                        className={`split-card-number ${isCardDone ? "is-done" : ""}`}
                        onClick={() => handleToggleCardDone(card.temporary_id)}
                        title={isCardDone ? "子任务已完成（点击切换为未完成）" : "点击标记为已完成"}
                      >
                        {isCardDone ? "✓" : index + 1}
                      </button>
                      <span className={`split-tab-badge ${getBadgeClass(cardLvl)}`}>L{cardLvl}</span>
                      <input
                        data-field="title"
                        className="split-card-title-input"
                        value={card.title}
                        onChange={(e) => updateCardTitle(card.temporary_id, e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !e.shiftKey) {
                            e.preventDefault();
                            handleAddGhostCard();
                          }
                        }}
                        title="高亮选中文字可直接批注，按回车可快速新建下一项"
                        placeholder="子任务标题..."
                      />
                    </div>

                    <div className="split-card-row1-actions">
                      {/* Reorder Up / Down */}
                      <button
                        type="button"
                        disabled={index === 0}
                        onClick={() => handleMoveCard(index, -1)}
                        className="split-card-icon-btn"
                        title="上移此任务"
                      >
                        ▲
                      </button>
                      <button
                        type="button"
                        disabled={index === activeTab.cards.length - 1}
                        onClick={() => handleMoveCard(index, 1)}
                        className="split-card-icon-btn"
                        title="下移此任务"
                      >
                        ▼
                      </button>

                      {/* Duplicate Card */}
                      <button
                        type="button"
                        onClick={() => handleDuplicateCard(card.temporary_id)}
                        className="split-card-icon-btn"
                        title="复制此项为新子任务"
                      >
                        ⧉
                      </button>

                      {/* Actionable / Completed Status Pill */}
                      {isCardDone ? (
                        <span
                          className="split-card-actionable-pill done"
                          onClick={() => handleToggleCardDone(card.temporary_id)}
                          style={{ cursor: "pointer" }}
                          title="子任务已达成并验收完成（点击可重新打开）"
                        >
                          ✓ Completed
                        </span>
                      ) : card.done_when?.trim() ? (
                        <span className="split-card-actionable-pill" title="已具备明确完成判定标准">
                          ✓ Actionable
                        </span>
                      ) : (
                        <span className="split-card-actionable-pill incomplete" title="缺少明确可检查的完成标准">
                          ! Incomplete
                        </span>
                      )}

                      {/* Delete Button */}
                      <button
                        type="button"
                        onClick={() => handleDeleteCard(card.temporary_id)}
                        className="split-card-del-btn"
                        title="删除此项任务"
                      >
                        🗑
                      </button>
                    </div>
                  </div>

                  {/* ROW 2: Done: Condition + Inline Time + Mode Select + Task Type Select */}
                  <div className="split-card-row-2">
                    <div className="split-card-done-wrap">
                      <span className="split-card-done-prefix">Done:</span>
                      <input
                        data-field="done_when"
                        className="split-card-desc-input"
                        value={card.done_when}
                        onChange={(e) => updateCardDesc(card.temporary_id, e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !e.shiftKey) {
                            e.preventDefault();
                            handleAddGhostCard();
                          }
                        }}
                        title="高亮选中文字可直接批注，按回车可快速新建下一项"
                        placeholder="明确可检查的完成判定与交付物说明..."
                      />
                    </div>

                    <div className="split-card-meta-wrap">
                      {/* Inline Time / Effort */}
                      <div className="split-card-time-wrap" title="预估工时（分钟）">
                        <span className="split-card-time-icon">⏱️</span>
                        <input
                          type="number"
                          min={5}
                          step={5}
                          value={card.estimated_effort_minutes ?? 45}
                          onChange={(e) => updateCardEffort(card.temporary_id, parseInt(e.target.value) || 0)}
                          className="split-card-time-input"
                        />
                        <span className="split-card-time-unit">m</span>
                      </div>

                      {/* Mode Select */}
                      <select
                        className="split-card-select"
                        value={cardMode}
                        onChange={(e) => updateCardMode(card.temporary_id, e.target.value)}
                        title="基于 Settings 的 Mode 选项"
                      >
                        {yoncConfig?.modes.map((m) => (
                          <option key={m.mode_name} value={m.mode_name}>
                            {m.mode_name}
                          </option>
                        ))}
                      </select>

                      {/* Task Type Select */}
                      <select
                        className="split-card-select"
                        value={cardTaskType}
                        onChange={(e) => updateCardTaskType(card.temporary_id, e.target.value)}
                        title="基于 Settings 的 Task Type 选项"
                      >
                        {yoncConfig?.task_types.map((t) => (
                          <option key={t.name} value={t.name}>
                            {t.emoji} {t.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {/* Chopped Tick Mark Watermark at Right (右侧印章盖戳水印) */}
                  {isCardDone && (
                    <div
                      className="split-card-chopped-stamp"
                      onClick={() => handleToggleCardDone(card.temporary_id)}
                      title="子任务已完成（点击可切换完成状态）"
                    >
                      <div className="stamp-seal">
                        <span className="stamp-tick">✔</span>
                        <span className="stamp-text">DONE</span>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}

            {/* Compact Ghost Card */}
            <div className="split-ghost-card" onClick={handleAddGhostCard} title="添加新子任务卡片（也可直接在上方卡片按 Enter）">
              <span className="split-ghost-plus">+</span>
              <span>+ Add Subtask Card (Click or press Enter)</span>
            </div>
          </div>
        ) : (
          <div className="split-empty-guide">
            <div className="split-empty-icon">⑂</div>
            <h3>选择需要拆分的目标任务</h3>
            <p>请点击上方标签栏或在下方列表中直接选择需要拆分的 L1-L3 任务块（严格排除 L4 Action）：</p>

            <div className="split-guide-picker">
              <div className="split-guide-search">
                <span>🔍</span>
                <input
                  type="text"
                  placeholder="快速搜索过滤任务名称 (L1-L3)..."
                  value={activeTab.searchQuery}
                  onChange={(e) => {
                    const val = e.target.value;
                    setTabs((prev) =>
                      prev.map((t) => (t.id === activeTab.id ? { ...t, searchQuery: val } : t))
                    );
                  }}
                />
              </div>

              <div className="split-guide-list">
                {filteredCandidates.map((cand) => {
                  const lvl = cand.wbs_level ?? 2;
                  const candTheme = themeInfoForNode(cand, yoncConfig, nodesById);
                  return (
                    <div
                      key={cand.id}
                      className="split-guide-item"
                      onClick={() => handleSelectBlock(cand)}
                    >
                      <div className="split-guide-item-main">
                        <div className="split-guide-item-header">
                          <span className={`split-tab-badge ${getBadgeClass(lvl)}`}>L{lvl}</span>
                          {candTheme && (
                            <span
                              className="node-theme-pill"
                              style={{ "--theme-color": candTheme.color } as React.CSSProperties}
                              title={`Theme: ${candTheme.name}`}
                            >
                              {candTheme.name}
                            </span>
                          )}
                          <span className="split-guide-item-title" title={cand.title}>
                            {cand.title}
                          </span>
                        </div>
                        {cand.description && (
                          <div className="split-guide-item-desc" title={cand.description}>
                            :: {cand.description}
                          </div>
                        )}
                      </div>
                      <span className="split-guide-item-action">进入拆分 →</span>
                    </div>
                  );
                })}
                {filteredCandidates.length === 0 && (
                  <div style={{ padding: "20px", textAlign: "center", color: "#64748b", fontSize: "12px" }}>
                    无匹配的 L1-L3 任务节点
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 4. WORD HIGHLIGHT POPOVER */}
      {selectionPopover && (
        <div
          className="selection-popover"
          style={{ left: selectionPopover.x, top: selectionPopover.y }}
          onMouseDown={(e) => {
            e.preventDefault();
            handleOpenAnnotationComposer();
          }}
        >
          <button type="button" className="popover-comment-btn">
            💬 批注此词
          </button>
        </div>
      )}

      {/* 5. FIXED BOTTOM DOCK (卡在下面, NOT STICKY) */}
      <div className="split-bottom-dock">
        {/* 5.1 Fixed Conversation History (~130px) */}
        <div className="split-chat-history-box">
          <div className="split-chat-history-header">
            <div
              className="split-chat-title-clickable"
              onClick={() => setIsChatCollapsed((v) => !v)}
              title={isChatCollapsed ? "点击展开对话历史 (▲)" : "点击折叠对话历史 (▼)"}
            >
              <span className="chat-title-main">
                <span>💬</span> Conversation History
                <span className="chat-toggle-emoji">
                  {isChatCollapsed ? "▲ 展开" : "▼ 折叠"}
                </span>
              </span>
              <span style={{ fontSize: "10px", padding: "1px 6px", background: "rgba(38, 22, 68, 0.8)", color: "#e9d5ff", border: "1px solid #5b2a9d", borderRadius: "4px" }}>
                Tab {tabs.indexOf(activeTab) + 1} ({activeNode?.title || (activeTab.nodeId ? "加载中..." : "未选择任务")}) · Isolated
              </span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <span style={{ fontSize: "10px", color: "#64748b" }}>Hermes Agent Reasoning Thread</span>
            </div>
          </div>

          {!isChatCollapsed && (
            <div ref={chatScrollRef} className="split-chat-history-scroll">
              {activeTab.session?.messages?.map((msg) => (
                <div key={msg.id} className={`split-chat-msg ${msg.role}`}>
                  <span style={{ fontSize: "12px", marginTop: "2px" }}>
                    {msg.role === "user" ? "👤" : "🤖"}
                  </span>
                  <div className="split-chat-bubble">
                    {msg.role === "assistant" && (
                      <span style={{ display: "block", fontSize: "10px", color: "#c084fc", fontWeight: "bold", marginBottom: "2px" }}>
                        Hermes Split Agent:
                      </span>
                    )}
                    <span>{msg.content}</span>
                  </div>
                </div>
              )) ?? (
                <div style={{ color: "#64748b", fontSize: "11px", padding: "8px 0" }}>
                  {activeTab.nodeId
                    ? "告诉我你希望如何拆分该任务，或按麦克风语音输入 Hermes 指令。"
                    : "请先在上方标签栏选择一个需要拆分的任务（L1-L3），随后即可在此与 Hermes 协作拆分。"}
                </div>
              )}
            </div>
          )}
        </div>

        {/* 5.2 Bottom Input Bar */}
        <div className="split-input-bar">
          {/* Middle: Staged Annotation Chip ("夹在里面") + Prompt Input + Borderless Mic Emoji */}
          <div className="split-prompt-box">
            {activeTab.stagedAnnotation && (
              <div className="split-staged-chip">
                <span style={{ color: "#c084fc", fontWeight: "bold" }}>📌 待提交命令:</span>
                <span style={{ maxWidth: "220px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  “{activeTab.stagedAnnotation.term}” → {activeTab.stagedAnnotation.comment}
                </span>
                <button
                  type="button"
                  className="split-staged-chip-remove"
                  onClick={handleClearStagedAnnotation}
                  title="移除此批注"
                >
                  ×
                </button>
              </div>
            )}

            <input
              ref={promptInputRef}
              type="text"
              disabled={!activeTab.nodeId}
              className="split-prompt-input"
              value={activeTab.draftMessage}
              onChange={(e) => {
                const val = e.target.value;
                setTabs((prev) =>
                  prev.map((t) => (t.id === activeTab.id ? { ...t, draftMessage: val } : t))
                );
                if (isChatCollapsed) {
                  setIsChatCollapsed(false);
                }
              }}
              onFocus={() => {
                if (isChatCollapsed) {
                  setIsChatCollapsed(false);
                }
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSendPrompt();
              }}
              placeholder={activeTab.nodeId ? "Speak to Hermes or type instructions (e.g. '按上述批注拆分，并将模式设为Focus')..." : "请先在上方标签栏选择需要拆分的任务..."}
            />

            {/* Borderless Gray Mic Emoji Button at end of input bar (like Antigravity) */}
            <button
              type="button"
              disabled={!activeTab.nodeId}
              className={`split-mic-borderless-btn ${isRecording ? "recording" : ""}`}
              onClick={toggleSTT}
              title={
                !activeTab.nodeId
                  ? "请先在上方选择任务"
                  : isRecording
                  ? "正在语音识别 (点击停止)"
                  : "点击开始语音输入 (STT)"
              }
            >
              <span className="split-mic-emoji">🎙️</span>
              {isRecording && <span className="split-mic-pulse-ring" />}
            </button>
          </div>

          {/* Send Button on the Right of Input */}
          <button
            type="button"
            disabled={!activeTab.nodeId}
            className="split-send-btn"
            onClick={handleSendPrompt}
            title={activeTab.nodeId ? "发送指令并生成新提案" : "请先选择任务"}
            style={{ opacity: activeTab.nodeId ? 1 : 0.45, cursor: activeTab.nodeId ? "pointer" : "not-allowed" }}
          >
            <span>Send</span>
            <span>➤</span>
          </button>

          {/* Far Right Actions: Discard, Validate (Ctrl+S replaces button) */}
          <div className="split-actions-right">
            {saveToast && (
              <span style={{ fontSize: "11px", color: "#34d399", fontWeight: 600, display: "inline-flex", alignItems: "center", gap: "4px" }}>
                ✓ {saveToast}
              </span>
            )}
            <button
              type="button"
              disabled={!activeTab.nodeId}
              onClick={handleDiscard}
              style={{ padding: "6px 12px", background: "transparent", border: "none", color: activeTab.nodeId ? "#94a3b8" : "#475569", cursor: activeTab.nodeId ? "pointer" : "not-allowed", fontSize: "11px" }}
              title="放弃当前拆分提案"
            >
              Discard
            </button>
            <button
              type="button"
              disabled={!activeTab.nodeId}
              onClick={handleValidate}
              style={{ padding: "6px 12px", background: "#121c29", border: "1px solid #27384d", borderRadius: "8px", color: activeTab.nodeId ? "#cbd5e1" : "#475569", cursor: activeTab.nodeId ? "pointer" : "not-allowed", fontSize: "11px" }}
              title="检查提案可执行性与项目图依赖 (按 Ctrl+S 可手动立即提交)"
            >
              Validate
            </button>
          </div>
        </div>
      </div>
    </div>
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
  const [dragThemeIndex, setDragThemeIndex] = useState<number | null>(null);
  const [dragOverThemeIndex, setDragOverThemeIndex] = useState<number | null>(null);
  const moveTheme = (fromIndex: number, toIndex: number) => {
    if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0 || fromIndex >= draft.themes.length || toIndex >= draft.themes.length) return;
    setDraft((current) => {
      const next = [...current.themes];
      const [moved] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, moved);
      return { ...current, themes: next };
    });
  };
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
            <div className="settings-section-heading"><div><h3>Task Theme with colour</h3><p>Theme colors are used immediately across Canvas, Timeline, and Forecast. Drag or use arrows to adjust priority order.</p></div><button onClick={() => setDraft((current) => ({ ...current, themes: [...current.themes, { name: "New Theme", sub_themes: [], color: "#64748b" }] }))}>＋ Add Theme</button></div>
            <div className="config-list">{draft.themes.map((theme, index) => <article
              className={`config-row theme-row${dragThemeIndex === index ? " dragging" : ""}${dragOverThemeIndex === index ? " drag-over" : ""}`}
              key={`${theme.name}-${index}`}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData("text/plain", String(index));
                e.dataTransfer.effectAllowed = "move";
                setDragThemeIndex(index);
              }}
              onDragOver={(e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
                if (dragOverThemeIndex !== index) setDragOverThemeIndex(index);
              }}
              onDragLeave={() => {
                if (dragOverThemeIndex === index) setDragOverThemeIndex(null);
              }}
              onDrop={(e) => {
                e.preventDefault();
                if (dragThemeIndex != null && dragThemeIndex !== index) {
                  moveTheme(dragThemeIndex, index);
                }
                setDragThemeIndex(null);
                setDragOverThemeIndex(null);
              }}
              onDragEnd={() => {
                setDragThemeIndex(null);
                setDragOverThemeIndex(null);
              }}
            >
              <div className="theme-drag-handle" title="拖拽调整顺位 / Drag to reorder" aria-label="Drag to reorder">
                <span className="drag-grip">⋮⋮</span>
                <div className="theme-step-buttons">
                  <button type="button" className="theme-step-btn" disabled={index === 0} onClick={(e) => { e.stopPropagation(); moveTheme(index, index - 1); }} title="上移 / Move up" aria-label="Move up">▲</button>
                  <button type="button" className="theme-step-btn" disabled={index === draft.themes.length - 1} onClick={(e) => { e.stopPropagation(); moveTheme(index, index + 1); }} title="下移 / Move down" aria-label="Move down">▼</button>
                </div>
              </div>
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
  const [directions, setDirections] = useState<Direction[]>([]);
  const [yoncConfig, setYoncConfig] = useState<YoncConfig | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [splitTargetNodeId, setSplitTargetNodeId] = useState<string | null>(null);
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
      const [nextGraph, nextTimeline, nextConfig, nextDirections] = await Promise.all([
        api.graph(), api.timeline(TIMELINE_RANGE.start, TIMELINE_RANGE.end),
        api.yoncConfig(),
        api.directions().catch(() => [] as Direction[]),
      ]);
      if (requestId !== latestLoad.current) return;
      setGraph(nextGraph);
      setTimeline(nextTimeline);
      setYoncConfig(nextConfig);
      setDirections(nextDirections);
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
  const openSplit = useCallback((node: GraphNode) => {
    setSelectedIds([]);
    setSplitTargetNodeId(node.id);
    setView("split");
  }, []);
  const selectedId = selectedIds.length === 1 ? selectedIds[0] : null;
  const selected = graph?.nodes.find((node) => node.id === selectedId) ?? null;

  const handleNavSplit = useCallback(() => {
    if (selectedId && graph) {
      const selectedNode = graph.nodes.find((n) => n.id === selectedId);
      if (selectedNode) {
        const splittableTarget =
          selectedNode.wbs_level !== 4 && selectedNode.work_type !== "ACTION"
            ? selectedNode
            : selectedNode.parent_id
            ? graph.nodes.find((n) => n.id === selectedNode.parent_id && n.wbs_level !== 4 && n.work_type !== "ACTION")
            : null;

        if (splittableTarget) {
          setSplitTargetNodeId(splittableTarget.id);
        }
      }
    }
    setView("split");
  }, [selectedId, graph]);

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
      <nav className="side-nav" aria-label="Primary">
        <a className="brand" href="/v2/" aria-label="Yonc home">Y</a>
        <button className={view === "canvas" ? "active" : ""} onClick={() => setView("canvas")} aria-label="Canvas"><span>▦</span><small>Canvas</small></button>
        <button className={view === "list" ? "active" : ""} onClick={() => setView("list")} aria-label="List"><span>☰</span><small>List</small></button>
        <button className={view === "timeline" ? "active" : ""} onClick={() => setView("timeline")} aria-label="Timeline"><span>◫</span><small>Timeline</small></button>
        <button className={view === "split" ? "active nav-split" : "nav-split"} onClick={handleNavSplit} aria-label="Split"><span>⑂</span><small>Split</small></button>
        <button className="nav-settings" onClick={() => setSettingsOpen(true)} aria-label="Settings"><span>⚙</span><small>Settings</small></button>
        <a className="legacy-link" href="/legacy" title="Open legacy UI">v1</a>
      </nav>
      {loading && <div className="loading-state"><div /><div /><div /><p>Loading project graph…</p></div>}
      {!loading && graph && timeline && <>
        <main className="desktop-content">
          {view === "canvas" ? (
            <CanvasView graph={graph} yoncConfig={yoncConfig} selectedIds={selectedIds} onSelectionChange={setSelectedIds} onOpenSplit={openSplit} onRegisterUndo={registerUndo} />
          ) : view === "list" ? (
            <ListView graph={graph} yoncConfig={yoncConfig} selectedIds={selectedIds} onSelectionChange={setSelectedIds} onOpenSplit={openSplit} onRefresh={refresh} onError={handleError} onRegisterUndo={registerUndo} />
          ) : view === "timeline" ? (
            <TimelineView timeline={timeline} graph={graph} yoncConfig={yoncConfig} directions={directions} selectedId={selectedId} mode={timelineMode} onMode={setTimelineMode} onSelect={(id) => setSelectedIds([id])} onRefresh={refresh} onError={handleError} onRegisterUndo={registerUndo} />
          ) : null}
          <div style={{ display: view === "split" ? "contents" : "none" }}>
            <SplitWorkspace
              graph={graph}
              yoncConfig={yoncConfig}
              splitTargetNodeId={splitTargetNodeId}
              onClearSplitTarget={() => setSplitTargetNodeId(null)}
              onRefresh={refresh}
              onError={handleError}
              onRegisterUndo={registerUndo}
            />
          </div>
        </main>
        {view === "canvas" && selected && <NodeInspector node={selected} allNodes={graph.nodes} color={nodeColors[selected.id]} graphVersion={graph.graph_version} onClose={() => setSelectedIds([])} onRefresh={refresh} onOpenSplit={openSplit} onError={handleError} onRegisterUndo={registerUndo} />}
        <MobileFallback graph={graph} onDone={mobileDone} />
      </>}
      {!loading && graph && !graph.nodes.length && <div className="empty-state"><h1>No work in this project file</h1><p>Import existing work or capture a Goal to begin.</p></div>}
      {mobileDoneCandidate && <Modal title="确认完成" onClose={() => setMobileDoneCandidate(null)}><p>确认标记“{mobileDoneCandidate.title}”为完成？完成状态只能由你确认。</p><div className="modal-actions"><button onClick={() => setMobileDoneCandidate(null)}>取消</button><button className="primary" onClick={confirmMobileDone}>标记完成</button></div></Modal>}
      {settingsOpen && yoncConfig && <SettingsPanel config={yoncConfig} onClose={() => setSettingsOpen(false)} onSaved={setYoncConfig} onError={handleError} />}
      {error && <Modal title="操作未完成" onClose={() => setError(null)}><p>{error}</p><div className="modal-actions"><button className="primary" onClick={() => setError(null)}>知道了</button></div></Modal>}
      {undoNotice && <div className="undo-notice" role="status">{undoNotice}</div>}
    </div>
  );
}
