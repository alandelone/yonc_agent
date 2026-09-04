import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { ApiError } from "./api";
import { anchoredScrollPosition, canvasEdgeEndpoints, connectorRoute, healthWarningMessage, nodeCardHeight, nodeCardInfo, projectKeyForNode, scheduledModuleLayout, splitCardTitle, wbsColorFor } from "./App";
import type { GraphNode } from "./types";

describe("Simplified Chinese interaction messages", () => {
  it("maps stable English API codes to Chinese user dialogs", () => {
    expect(new ApiError("GRAPH_VERSION_CONFLICT").message).toContain("项目图已发生变化");
    expect(new ApiError("USER_ONLY_DONE").message).toContain("只能由你确认");
    expect(new ApiError("DEPENDENCY_ORDER_CONFLICT").message).toContain("依赖关系");
  });

  it("uses a safe Chinese fallback for unknown codes", () => {
    expect(new ApiError("FUTURE_CODE").message).toBe("操作未完成，请重试。");
  });
});

describe("Capacity Grid drag allocation preview", () => {
  it("keeps a single-day milestone readable without presenting it as a date range", () => {
    expect(scheduledModuleLayout("2026-08-27", "2026-08-27", 4, 4, 20)).toEqual({ singleDay: true, displayEndWeek: 7 });
    expect(scheduledModuleLayout("2026-08-27", "2026-09-10", 4, 6, 20)).toEqual({ singleDay: false, displayEndWeek: 6 });
    expect(scheduledModuleLayout("2026-12-31", "2026-12-31", 20, 20, 20)).toEqual({ singleDay: true, displayEndWeek: 20 });
  });

  it("keeps the same Canvas world point directly below the mouse while zooming", () => {
    const before = { left: 1400, top: 620, anchorX: 430, anchorY: 260, zoom: .5 };
    const after = anchoredScrollPosition(before.left, before.top, before.anchorX, before.anchorY, before.zoom, .9);
    expect((after.left + before.anchorX) / .9).toBeCloseTo((before.left + before.anchorX) / before.zoom, 8);
    expect((after.top + before.anchorY) / .9).toBeCloseTo((before.top + before.anchorY) / before.zoom, 8);
  });

  it("suppresses the native card ghost and fills the hovered grid cell", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    expect(app).toContain("setDragImage(transparent, 0, 0)");
    expect(app).toContain('dropPreview ? "drop-preview"');
    expect(app).toContain("nodeSpanDays(previewNode, graph)");
    expect(app).toContain("cell.date >= previewStart && cell.date <= previewEnd");
    expect(app).toContain("setPendingPlacement({ nodeId, start: scheduled.planned_start, end: scheduled.planned_end })");
    expect(app).toContain("finally { setPendingPlacement(null); }");
    expect(app).toContain("draggable={Boolean(dragAllocationId)}");
    expect(app).toContain("daysBetween(node.planned_start, cell.date)");
    expect(app).toContain("scheduledMove ? suggestedEnd : null");
    expect(styles).toContain(".day-cell.drag-source");
    expect(styles).toContain(".day-cell.drop-preview::before");
    expect(styles).toMatch(/\.day-cell\.drop-preview::before[^}]*inset:\s*3px/);
  });

  it("uses one global project file with functional left navigation", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    expect(app).toContain("api.graph(), api.timeline(TIMELINE_RANGE.start, TIMELINE_RANGE.end)");
    expect(app).not.toContain("scopeOptions");
    expect(app).not.toContain('className="topbar"');
    expect(app).toContain('aria-label="Canvas"');
    expect(app).toContain('aria-label="Timeline"');
    expect(styles).toContain("grid-template-columns: minmax(0, 1fr)");
    expect(styles).toContain(".side-nav { position: fixed");
    expect(styles).toContain("transform: translateX(calc(-100% + 5px))");
  });

  it("uses one fixed weekly grid with horizontal-only multi-year navigation", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    expect(app).not.toContain('className="scale-control"');
    expect(app).toContain("anchor.getFullYear() + 3");
    expect(app).toContain("calendar.scrollBy({ left: direction * 13 * 49");
    expect(app).toContain("mode={timelineMode}");
    expect(styles).toMatch(/\.calendar-wrap\s*\{[^}]*overflow-x:\s*auto;[^}]*overflow-y:\s*hidden;/);
  });

  it("keeps Canvas schedule read-only and renders logarithmic time and perimeter progress", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    const canvas = app.slice(app.indexOf("function CanvasView"), app.indexOf("function NodeInspector"));
    expect(canvas).not.toContain("api.schedule");
    expect(canvas).toContain("logarithmicDateOffset");
    expect(canvas).toContain("connectorRoute");
    expect(canvas).toContain("onClearSelection");
    expect(canvas).toContain("setManualPositions");
    expect(canvas).toContain('api.saveViewState("canvas"');
    expect(canvas).toContain("fitAll");
    expect(canvas).toContain("(canvas.clientWidth - 28) / width");
    expect(canvas).not.toContain("(canvas.clientHeight - 28) / height");
    expect(canvas).toContain("Math.max(horizontalFitZoom()");
    expect(canvas).toContain("nodeDragFrame");
    expect(canvas).toContain("minimapViewportRef");
    expect(canvas).not.toContain("setNodeDrag");
    expect(canvas).not.toContain("setViewport");
    expect(canvas).toContain('window.addEventListener("wheel", zoomWithMouse');
    expect(canvas).toContain('className="minimap-viewport"');
    expect(canvas).toContain('className="today-line"');
    expect(canvas).toContain("connectorRoute");
    expect(canvas).toContain("data-target-side={route.targetSide}");
    expect(canvas).toContain('markerEnd="url(#arrow)"');
    expect(canvas).not.toContain('markerStart="url(#arrow)"');
    expect(styles).toContain("conic-gradient(from -90deg");
    expect(styles).toContain(".month-tick");
    expect(canvas).toMatch(/canvas-zoom-space[\s\S]*?<LogarithmicTimeAxis[\s\S]*?canvas-stage/);
    expect(canvas).toContain("todayX={todayX * zoom}");
    expect(canvas).toContain("height={height * zoom}");
    expect(canvas.slice(canvas.indexOf('className="canvas-stage"'))).not.toContain("<LogarithmicTimeAxis");
    expect(canvas).not.toContain('className="node-port');
    expect(styles).toContain(".minimap-viewport");
    expect(styles).toContain("scroll-behavior: smooth");
    expect(styles).toContain(".canvas-scroll.panning { scroll-behavior: auto;");
    expect(styles).toContain(".canvas-stage.node-dragging .node-card::before { filter: none;");
    expect(styles).toContain(".canvas-overlay-tools:hover { opacity: 1");
    expect(app).toContain('className="scheduled-module-lane"');
    expect(app).toContain("gridColumn: `${startWeek + 2} / ${displayEndWeek + 3}`");
    expect(styles).toContain(".scheduled-module-lane { display: grid");
  });

  it("routes connectors through the target edge that faces their approach direction", () => {
    const leftToRight = connectorRoute({ x: 0, y: 100 }, 66, { x: 300, y: 100 }, 66);
    expect(leftToRight).toMatchObject({ sourceSide: "right", targetSide: "left", x1: 167, x2: 297 });
    expect(leftToRight.path).toMatch(/H 297$/);

    const rightToLeft = connectorRoute({ x: 300, y: 100 }, 66, { x: 0, y: 100 }, 66);
    expect(rightToLeft).toMatchObject({ sourceSide: "left", targetSide: "right", x1: 297, x2: 167 });
    expect(rightToLeft.path).toMatch(/H 167$/);

    const bottomToTop = connectorRoute({ x: 100, y: 300 }, 66, { x: 100, y: 0 }, 66);
    expect(bottomToTop).toMatchObject({ sourceSide: "top", targetSide: "bottom", y1: 297, y2: 69 });
    expect(bottomToTop.path).toMatch(/V 69$/);

    const topToBottom = connectorRoute({ x: 100, y: 0 }, 66, { x: 100, y: 300 }, 66);
    expect(topToBottom).toMatchObject({ sourceSide: "bottom", targetSide: "top", y1: 69, y2: 297 });
    expect(topToBottom.path).toMatch(/V 297$/);
  });

  it("renders hierarchy execution from L4 children toward the L1 goal", () => {
    expect(canvasEdgeEndpoints({ source_id: "goal-l1", target_id: "action-l4", relation: "contains" })).toEqual({
      sourceId: "action-l4",
      targetId: "goal-l1",
    });
    expect(canvasEdgeEndpoints({ source_id: "task-b", target_id: "task-a", relation: "depends_on" })).toEqual({
      sourceId: "task-b",
      targetId: "task-a",
    });

    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    expect(app).toContain("const endpoints = canvasEdgeEndpoints(edge)");
    expect(app).toContain("__layout_direction_version: CANVAS_LAYOUT_VERSION");
  });

  it("shows inspectors only as floating on-demand panels", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    expect(app).toContain("selected && <NodeInspector");
    expect(app).toContain("rangeNode && <aside");
    expect(app).not.toContain('className="legend"');
    expect(styles).toContain(".floating-inspector { position: fixed");
  });

  it("silently refreshes data after direct manipulation", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    expect(app).toContain("const refresh = useCallback(async () => { await load(); }");
    expect(app).toContain("if (blocking) setLoading(true)");
    expect(app).toContain("await load(true, true)");
    expect(app).toContain("window.setInterval(quietlySync, 30_000)");
    expect(app).toContain('window.addEventListener("focus", quietlySync)');
    expect(app).not.toContain('aria-label="Refresh"');
    expect(app).not.toContain("<Toast");
  });

  it("reverts Canvas layout and committed graph actions with Ctrl or Cmd Z", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
    expect(app).toContain('event.key.toLowerCase() !== "z"');
    expect(app).toContain("event.ctrlKey");
    expect(app).toContain("event.metaKey");
    expect(app).toContain("input, textarea, select, [contenteditable='true']");
    expect(app).toContain('onRegisterUndo({ kind: "local"');
    expect(app).toContain('onRegisterUndo({ kind: "batch"');
    expect(app).toContain("await api.undoBatch(action.batchId, graph.graph_version)");
    expect(api).toContain("/api/v2/operation-batches/${batchId}/undo");
  });
});

describe("Canvas project color system", () => {
  it("keeps one project hue throughout an L1-L4 lineage", () => {
    const nodes = [
      { id: "project", parent_id: null, wbs_level: 1 },
      { id: "deliverable", parent_id: "project", wbs_level: 2 },
      { id: "package", parent_id: "deliverable", wbs_level: 3 },
      { id: "action", parent_id: "package", wbs_level: 4 },
    ] as Pick<GraphNode, "id" | "parent_id" | "wbs_level">[];
    const byId = new Map(nodes.map((node) => [node.id, node]));
    expect(nodes.map((node) => projectKeyForNode(node, byId))).toEqual(["project", "project", "project", "project"]);
  });

  it("keeps each project hue while darkening from L1 through L4", () => {
    const colors = [1, 2, 3, 4].map((level) => wbsColorFor("project", level));
    const channels = colors.map((color) => color.match(/^hsl\((\d+) (\d+)% (\d+)%\)$/)?.slice(1).map(Number));
    expect(new Set(channels.map((channel) => channel?.[0])).size).toBe(1);
    expect(new Set(channels.map((channel) => channel?.[1])).size).toBe(1);
    expect(channels.map((channel) => channel?.[2])).toEqual([52, 42, 32, 22]);
    expect(wbsColorFor("project-a", 1)).not.toBe(wbsColorFor("project-b", 1));
  });

  it("keeps the level-specific gradient coverage without a visible dividing line", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    expect(app).toContain("data-wbs-level={node.wbs_level ?? undefined}");
    expect(styles).toContain('data-wbs-level="1"] { --node-wash: 48%; --node-soft-wash: 31%; --node-gradient-stop: 100%');
    expect(styles).toContain('data-wbs-level="2"] { --node-wash: 60%; --node-soft-wash: 38%; --node-gradient-stop: 80%');
    expect(styles).toContain('data-wbs-level="3"] { --node-wash: 45%; --node-soft-wash: 28%; --node-gradient-stop: 50%');
    expect(styles).toContain('data-wbs-level="4"] { --node-wash: 35%; --node-soft-wash: 21%; --node-gradient-stop: 30%');
    expect(styles).not.toContain("--node-gradient-line");
  });
});

describe("Canvas card title hierarchy", () => {
  it("keeps the title and separates the inline description at the first spaced colon", () => {
    expect(splitCardTitle("🤖💬🔜硬件 BOM 采购清单 : OGPV原型组装最终清单（组件、传感器、通信硬件）")).toEqual({
      title: "🤖💬🔜硬件 BOM 采购清单",
      description: "OGPV原型组装最终清单（组件、传感器、通信硬件）",
    });
    expect(splitCardTitle("A title without description")).toEqual({ title: "A title without description", description: null });
  });

  it("styles the description like compact metadata", () => {
    const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    expect(styles).toContain(".node-description { color: #a8b4c4; font-size: 8.5px; font-weight: 400");
    expect(styles).toContain(".node-meta { margin-top: 2px; color: #a8b4c4");
  });

  it("hides empty placeholders and only allocates height for real information", () => {
    const empty = { planned_start: null, deadline: null, estimated_effort_minutes: null, resource_count: 0, health: [] };
    const meta = { ...empty, planned_start: "2026-08-31" };
    const signals = { ...empty, resource_count: 2 };
    expect(nodeCardInfo(empty)).toEqual({ hasMeta: false, hasSignals: false });
    expect(nodeCardHeight(empty)).toBe(66);
    expect(nodeCardHeight(meta)).toBe(79);
    expect(nodeCardHeight(signals)).toBe(81);
    expect(nodeCardHeight({ ...empty, planned_start: "2026-08-31", resource_count: 2 })).toBe(94);
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    const card = app.slice(app.indexOf("function NodeCard"), app.indexOf("function logarithmicDateOffset"));
    expect(card).not.toContain(': "No date"');
    expect(card).not.toContain("<span>✓</span>");
  });
});

describe("Inspector health warnings", () => {
  it("explains which execution fields are missing", () => {
    const node = { start_cue: null, done_when: null } as GraphNode;
    expect(healthWarningMessage({ code: "ACTIONABILITY_INCOMPLETE" }, node)).toBe("Missing start cue and done-when condition.");
  });

  it("renders node health warnings in the floating inspector", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    expect(app).toContain('className="health-warnings"');
    expect(app).toContain("node.health.map");
    expect(styles).toContain(".health-warnings .section-heading");
  });
});
