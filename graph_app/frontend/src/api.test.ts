import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { ApiError } from "./api";
import { anchoredScrollPosition, arrangeCanvasFamilies, arrangeCanvasPositions, calculateRangeDuration, calculateRangeEnd, canvasContentBounds, canvasEdgeEndpoints, canvasPositionForNode, canvasSubtreeIds, canvasTimeRange, configuredThemeColor, connectorRoute, healthWarningMessage, isUnclassifiedConstellation, isUnclassifiedNode, logarithmicDateOffset, modeInfoForNode, nodeCardHeight, nodeCardInfo, nodeCardWidth, nodesInSelectionBounds, placeChildrenBeforeDatedParents, projectKeyForNode, scheduledModuleLayout, splitCardTitle, taskTypeEmojisForNode, themeInfoForNode, tidyConstellationPositions, timelinePoolMatches, wideCanvasFamilyLayout, wbsColorFor } from "./App";
import type { GraphNode, YoncConfig } from "./types";

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
  it("selects every Canvas block touched by a marquee", () => {
    const positions = { a: { x: 10, y: 10 }, b: { x: 210, y: 20 }, c: { x: 20, y: 160 } };
    const heights = { a: 66, b: 80, c: 66 };
    expect(nodesInSelectionBounds(positions, heights, { left: 0, top: 0, right: 220, bottom: 90 })).toEqual(["a", "b"]);
    expect(nodesInSelectionBounds(positions, heights, { left: 30, top: 170, right: 60, bottom: 190 })).toEqual(["c"]);
  });

  it("supports Shift multi-selection, marquee selection, and grouped Canvas dragging", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    expect(app).toContain("event.shiftKey");
    expect(app).toContain("shiftHeld");
    expect(app).toContain("Hold Shift to select multiple");
    expect(app).toContain("suppressNodeClick.current = true");
    expect(app).toContain("marqueeDrag.current");
    expect(app).toContain("Drag any selected block to move all");
    expect(app).toContain("for (const id of current.ids)");
    expect(app).toContain("selectedIds.length === 1");
    expect(styles).toContain(".selection-marquee");
    expect(styles).toContain(".canvas-selection-status");
  });

  it("keeps a single-day milestone readable without presenting it as a date range", () => {
    expect(scheduledModuleLayout("2026-08-27", "2026-08-27", 4, 4, 20)).toEqual({ singleDay: true, displayEndWeek: 7 });
    expect(scheduledModuleLayout("2026-08-27", "2026-09-10", 4, 6, 20)).toEqual({ singleDay: false, displayEndWeek: 6 });
    expect(scheduledModuleLayout("2026-12-31", "2026-12-31", 20, 20, 20)).toEqual({ singleDay: true, displayEndWeek: 20 });
  });

  it("searches every timeline title and filters jobs from tasks", () => {
    const nodes = [
      { id: "goal", title: "Solar launch plan", work_type: "GOAL", planned_start: "2026-10-01" },
      { id: "package", title: "Solar hardware package", work_type: "WORK_PACKAGE", planned_start: null },
      { id: "task", title: "Test solar inverter", work_type: "ACTION", planned_start: "2026-10-04" },
      { id: "artifact", title: "Solar reference", work_type: "UNCLASSIFIED", planned_start: null },
    ] as GraphNode[];
    expect(timelinePoolMatches(nodes, "solar", "all").map((node) => node.id)).toEqual(["package", "goal", "artifact", "task"]);
    expect(timelinePoolMatches(nodes, "solar", "jobs").map((node) => node.id)).toEqual(["package", "goal"]);
    expect(timelinePoolMatches(nodes, "solar inverter", "tasks").map((node) => node.id)).toEqual(["task"]);
  });

  it("excludes tasks (ACTION / L4) from timeline module pool", () => {
    const nodes = [
      { id: "l1-goal", title: "Launch Product", work_type: "GOAL", planned_start: null, wbs_level: 1 },
      { id: "l2-deliv", title: "Core Engine", work_type: "DELIVERABLE", planned_start: null, wbs_level: 2 },
      { id: "l3-pkg", title: "API Module", work_type: "WORK_PACKAGE", planned_start: null, wbs_level: 3 },
      { id: "l4-task", title: "Write Tests", work_type: "ACTION", planned_start: null, wbs_level: 4 },
    ] as GraphNode[];
    const schedulable = nodes.filter(
      (node) => node.work_type !== "ACTION" && (node.wbs_level === null || node.wbs_level <= 3)
    );
    const pool = timelinePoolMatches(schedulable, "", "jobs");
    expect(pool.map((n) => n.id)).toEqual(["l3-pkg", "l2-deliv", "l1-goal"]);
    expect(pool.some((n) => n.id === "l4-task")).toBe(false);
  });

  it("sorts tasks in Unscheduled modules by task theme according to config priority", () => {
    const config: YoncConfig = {
      themes: [
        { name: "PhD", color: "#ef4444", sub_themes: ["Research", "Writing"] },
        { name: "Career", color: "#3b82f6", sub_themes: ["Job Search"] },
        { name: "Health", color: "#10b981", sub_themes: [] },
      ],
      modes: [],
      task_types: [],
      source: "test",
      revision: 1,
      updated_at: null,
    };

    const nodes = [
      { id: "health-task", title: "Morning Run", work_type: "ACTION", planned_start: null, tags: { "Task Theme": "Health" }, parent_id: null, wbs_level: 4 },
      { id: "career-pkg", title: "Resume Prep", work_type: "WORK_PACKAGE", planned_start: null, tags: { "Task Theme": "Job Search" }, parent_id: null, wbs_level: 2 },
      { id: "phd-task", title: "Paper Draft", work_type: "ACTION", planned_start: null, tags: { "Task Theme": "Writing" }, parent_id: null, wbs_level: 4 },
      { id: "phd-goal", title: "Thesis Plan", work_type: "GOAL", planned_start: null, tags: { "Task Theme": "PhD" }, parent_id: null, wbs_level: 1 },
      { id: "unthemed-task", title: "Buy Groceries", work_type: "ACTION", planned_start: null, tags: {}, parent_id: null, wbs_level: 4 },
    ] as GraphNode[];

    const result = timelinePoolMatches(nodes, "", "all", config);
    expect(result.map((n) => n.id)).toEqual([
      "phd-goal",
      "phd-task",
      "career-pkg",
      "health-task",
      "unthemed-task",
    ]);
  });

  it("sorts tasks by inheriting ancestor task theme in Unscheduled modules", () => {
    const config: YoncConfig = {
      themes: [
        { name: "PhD", color: "#ef4444", sub_themes: [] },
        { name: "Career", color: "#3b82f6", sub_themes: [] },
      ],
      modes: [],
      task_types: [],
      source: "test",
      revision: 1,
      updated_at: null,
    };

    const parentGoal = { id: "goal-phd", title: "PhD Project", work_type: "GOAL", planned_start: "2026-10-01", tags: { "Task Theme": "PhD" }, parent_id: null, wbs_level: 1 } as GraphNode;
    const childAction = { id: "task-phd-child", title: "Experiment Setup", work_type: "ACTION", planned_start: null, tags: {}, parent_id: "goal-phd", wbs_level: 4 } as GraphNode;
    const careerAction = { id: "task-career", title: "Interview", work_type: "ACTION", planned_start: null, tags: { "Task Theme": "Career" }, parent_id: null, wbs_level: 4 } as GraphNode;

    const allNodesMap = new Map([
      ["goal-phd", parentGoal],
      ["task-phd-child", childAction],
      ["task-career", careerAction],
    ]);

    const unscheduledCandidates = [careerAction, childAction];
    const result = timelinePoolMatches(unscheduledCandidates, "", "all", config, allNodesMap);
    expect(result.map((n) => n.id)).toEqual(["task-phd-child", "task-career"]);
  });

  it("keeps the same Canvas world point directly below the mouse while zooming", () => {
    const before = { left: 1400, top: 620, anchorX: 430, anchorY: 260, zoom: .5 };
    const fixedAxisHeight = 54;
    const after = anchoredScrollPosition(before.left, before.top, before.anchorX, before.anchorY, before.zoom, .9, fixedAxisHeight);
    expect((after.left + before.anchorX) / .9).toBeCloseTo((before.left + before.anchorX) / before.zoom, 8);
    expect((after.top + before.anchorY - fixedAxisHeight) / .9).toBeCloseTo((before.top + before.anchorY - fixedAxisHeight) / before.zoom, 8);
  });

  it("keeps undated descendants to the left of a dated completion parent", () => {
    const nodes = [
      { id: "parent", parent_id: null, planned_start: "2026-11-09", deadline: null },
      { id: "child", parent_id: "parent", planned_start: null, deadline: null },
      { id: "grandchild", parent_id: "child", planned_start: null, deadline: null },
      { id: "dated-child", parent_id: "parent", planned_start: "2026-10-13", deadline: null },
    ];
    const result = placeChildrenBeforeDatedParents(nodes, {
      parent: { x: 3420, y: 0 }, child: { x: 4910, y: 100 }, grandchild: { x: 5200, y: 200 }, "dated-child": { x: 2438, y: 300 },
    });
    expect(result.child.x).toBe(3180);
    expect(result.grandchild.x).toBe(2940);
    expect(result["dated-child"].x).toBe(2438);
  });

  it("moves families as rigid groups and packs unscheduled families after Today", () => {
    const nodes = [
      { id: "scheduled-root", parent_id: null, wbs_level: 1, planned_start: "2026-11-09", deadline: null },
      { id: "scheduled-child", parent_id: "scheduled-root", wbs_level: 2, planned_start: null, deadline: null },
      { id: "loose-root", parent_id: null, wbs_level: 1, planned_start: null, deadline: null },
      { id: "loose-child", parent_id: "loose-root", wbs_level: 2, planned_start: null, deadline: null },
    ];
    const seed = {
      "scheduled-root": { x: 1400, y: 500 }, "scheduled-child": { x: 1180, y: 620 },
      "loose-root": { x: 1900, y: 900 }, "loose-child": { x: 1680, y: 1020 },
    };
    const result = arrangeCanvasFamilies(nodes, seed, {}, 1000);
    expect(result["scheduled-root"].x).toBe(1400);
    expect(result["scheduled-child"].x).toBeLessThan(result["scheduled-root"].x);
    expect(result["loose-root"].x).toBeGreaterThan(result["loose-child"].x);
    expect(Math.min(result["loose-root"].x, result["loose-child"].x)).toBeGreaterThanOrEqual(1120);
    expect(Math.min(result["loose-root"].y, result["loose-child"].y)).toBe(82);
    expect(canvasSubtreeIds(nodes, "loose-root")).toEqual(["loose-root", "loose-child"]);
  });

  it("migrates an older Canvas layout without discarding its saved family shape", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    expect(app).toContain("const CANVAS_LAYOUT_VERSION = 9");
    expect(app).toMatch(/for \(const node of renderNodes\)[\s\S]*stored\[`\$\{node\.id\}:x`\][\s\S]*stored\.__layout_direction_version !== CANVAS_LAYOUT_VERSION/);
  });

  it("reflows a large family into a wide layout with L4 cards in two rows", () => {
    const nodes = [
      { id: "root", parent_id: null, wbs_level: 1, planned_start: null, deadline: null },
      { id: "l2", parent_id: "root", wbs_level: 2, planned_start: null, deadline: null },
      { id: "l3", parent_id: "l2", wbs_level: 3, planned_start: null, deadline: null },
      ...Array.from({ length: 8 }, (_, index) => ({ id: `leaf-${index}`, parent_id: "l3", wbs_level: 4, planned_start: null, deadline: null })),
    ];
    const seed = Object.fromEntries(nodes.map((node, index) => [node.id, { x: 0, y: index * 100 }]));
    const result = wideCanvasFamilyLayout(nodes, seed, {});
    const leafRows = new Set(nodes.slice(3).map((node) => result[node.id].y));
    const bounds = canvasContentBounds(result, {}, Object.fromEntries(nodes.map((node) => [node.id, nodeCardWidth(node)])))!;
    expect(leafRows.size).toBe(2);
    expect(bounds.right - bounds.left).toBeGreaterThan(bounds.bottom - bounds.top);
    expect(nodeCardWidth(nodes.at(-1)!)).toBe(180);
  });

  it("closes the description inspector before opening a split session", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    expect(app).toMatch(/const openSplit = useCallback\(\(node: GraphNode\) => \{\s*setSelectedIds\(\[\]\);\s*setSplitTargetNodeId\(node\.id\);\s*setView\("split"\);/);
  });

  it("keeps useful past and future time around today without crushing distant months", () => {
    expect(canvasTimeRange(new Date("2026-09-08T12:00:00"), [])).toEqual({ start: "2025-03-01", end: "2031-09-01" });
    const august = logarithmicDateOffset("2031-08-01", "2026-09-08");
    const september = logarithmicDateOffset("2031-09-01", "2026-09-08");
    expect(september - august).toBeGreaterThan(50);
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
    expect(canvas).toContain("onSelectionChange");
    expect(canvas).toContain("setManualPositions");
    expect(canvas).toContain('api.saveViewState("canvas"');
    expect(canvas).toContain("state.zoom");
    expect(canvas).toContain("state.pan");
    expect(canvas).toContain("restoredViewport.current");
    expect(canvas).toContain("scheduleViewportSave");
    expect(canvas).toContain("fitAll");
    expect(canvas).toContain("autoArrangeAll");
    expect(canvas).toContain(">Auto Arrange</button>");
    expect(canvas).toContain("setZoomAroundCenter(.75)");
    expect(canvas).toContain(">75%</button>");
    expect(canvas).toContain("setZoomAroundCenter(1)");
    expect(canvas).toContain(">100%</button>");
    expect(canvas).toContain("(canvas.clientWidth - 28) / width");
    expect(canvas).not.toContain("(canvas.clientHeight - 28) / height");
    expect(canvas).toContain("Math.max(horizontalFitZoom()");
    expect(canvas).toContain("manualZoomChosen.current = true");
    expect(canvas).toContain("autoArrangeAll(!manualZoomChosen.current)");
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
    expect(canvas).toContain("todayX={todayX} zoom={zoom}");
    expect(app).toContain("(todayX + logarithmicDateOffset(value, anchor)) * zoom");
    expect(canvas).toContain("height={height * zoom + CANVAS_AXIS_HEIGHT}");
    expect(canvas.slice(canvas.indexOf('className="canvas-stage"'))).not.toContain("<LogarithmicTimeAxis");
    expect(canvas).not.toContain('className="node-port');
    expect(styles).toContain(".minimap-viewport");
    expect(styles).toMatch(/\.canvas-scroll\s*\{[^}]*scroll-behavior:\s*auto;/);
    expect(styles).toContain(".canvas-scroll.panning { scroll-behavior: auto;");
    expect(styles).toContain(".canvas-stage.node-dragging .node-card::before { filter: none;");
    expect(styles).toContain(".canvas-overlay-tools:hover { opacity: 1");
    expect(app).toContain('className="scheduled-module-lane"');
    expect(app).toContain("gridColumn: `${startWeek + 2} / ${displayEndWeek + 3}`");
    expect(styles).toContain(".scheduled-module-lane { display: grid");
  });

  it("routes connectors through the target edge that faces their approach direction", () => {
    const leftToRight = connectorRoute({ x: 0, y: 100 }, 66, { x: 300, y: 100 }, 66);
    expect(leftToRight).toMatchObject({ sourceSide: "right", targetSide: "left", x1: 187, x2: 297 });
    expect(leftToRight.path).toMatch(/H 297$/);

    const rightToLeft = connectorRoute({ x: 300, y: 100 }, 66, { x: 0, y: 100 }, 66);
    expect(rightToLeft).toMatchObject({ sourceSide: "left", targetSide: "right", x1: 297, x2: 187 });
    expect(rightToLeft.path).toMatch(/H 187$/);

    const bottomToTop = connectorRoute({ x: 100, y: 300 }, 66, { x: 100, y: 0 }, 66);
    expect(bottomToTop).toMatchObject({ sourceSide: "top", targetSide: "bottom", y1: 297, y2: 69 });
    expect(bottomToTop.path).toMatch(/V 69$/);

    const topToBottom = connectorRoute({ x: 100, y: 0 }, 66, { x: 100, y: 300 }, 66);
    expect(topToBottom).toMatchObject({ sourceSide: "bottom", targetSide: "top", y1: 69, y2: 297 });
    expect(topToBottom.path).toMatch(/V 297$/);
  });

  it("routes connectors around intervening obstacles to prevent overlaying blocks", () => {
    // Source: x=0..180, y=100..166 (center y=133, right exit at x1=183, y1=133)
    // Target: x=500..700, y=100..166 (center y=133, left enter at x2=497, y2=133)
    // Obstacle block directly in between: x=206..386, y=100..166
    const obstacle = { left: 206, top: 100, right: 386, bottom: 166 };
    const route = connectorRoute(
      { x: 0, y: 100 },
      66,
      { x: 500, y: 100 },
      66,
      180,
      200,
      [obstacle],
      "test-edge",
    );
    expect(route).toMatchObject({ sourceSide: "right", targetSide: "left" });
    // Without obstacle avoidance, path would be straight horizontal: M 183 133 H 497
    // which plows right through the obstacle (206..386 at y=133).
    // With obstacle avoidance, it detours into a corridor (y < 100 or y > 166):
    expect(route.path).not.toBe("M 183 133 H 497");
    expect(route.path).toMatch(/V (8\d|9\d|17\d|18\d)/);
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

  it("fits the Canvas to the actual bounds of every arranged block", () => {
    expect(canvasContentBounds({
      a: { x: 100, y: 80 },
      b: { x: 500, y: 300 },
    }, { a: 66, b: 94 })).toEqual({ left: 100, top: 80, right: 684, bottom: 394 });
    expect(canvasContentBounds({}, {})).toBeNull();
  });

  it("keeps timeline X positions while separating blocks that would overlap", () => {
    const arranged = arrangeCanvasPositions({
      goal: { x: 500, y: 82 },
      deliverable: { x: 510, y: 82 },
      distant: { x: 900, y: 82 },
    }, { goal: 66, deliverable: 79, distant: 66 });
    expect(arranged.goal).toEqual({ x: 500, y: 82 });
    expect(arranged.deliverable).toEqual({ x: 510, y: 166 });
    expect(arranged.distant).toEqual({ x: 900, y: 82 });
  });

  it("lets Timeline dates own horizontal Canvas positions without discarding manual lanes", () => {
    const automatic = { x: 640, y: 120 };
    const manual = { x: 240, y: 360 };
    expect(canvasPositionForNode({ planned_start: "2026-09-04", deadline: null }, automatic, manual)).toEqual({ x: 640, y: 360 });
    expect(canvasPositionForNode({ planned_start: null, deadline: "2026-10-01" }, automatic, manual)).toEqual({ x: 640, y: 360 });
    expect(canvasPositionForNode({ planned_start: null, deadline: null }, automatic, manual)).toEqual({ x: 240, y: 360 });
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
  it("uses the saved Task Theme color and inherits it through the project tree", () => {
    const nodes = [
      { id: "project", parent_id: null, wbs_level: 1, tags: { "Task Theme with colour": "PhDSettle✒ Research | Thesis" } },
      { id: "action", parent_id: "project", wbs_level: 4, tags: {} },
    ] as GraphNode[];
    const config = {
      themes: [{ name: "PhDSettle✒", sub_themes: ["Research", "Thesis"], color: "#dc2626" }],
      modes: [], task_types: [], source: "settings_ui", revision: 2, updated_at: null,
    } as YoncConfig;
    const byId = new Map(nodes.map((node) => [node.id, node]));
    expect(configuredThemeColor(nodes[0], byId, config)).toMatch(/^#[0-9a-f]{6}$/);
    expect(configuredThemeColor(nodes[1], byId, config)).not.toBeNull();
    expect(configuredThemeColor(nodes[1], byId, config)).not.toBe(configuredThemeColor(nodes[0], byId, config));
  });

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
    expect(nodeCardHeight({ ...empty, wbs_level: 4 })).toBe(52);
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    const card = app.slice(app.indexOf("function NodeCard"), app.indexOf("function logarithmicDateOffset"));
    expect(card).not.toContain(': "No date"');
    expect(card).not.toContain("<span>✓</span>");
  });

  it("extracts task type emojis from settings and prepends them before WBS", () => {
    const mockConfig: YoncConfig = {
      themes: [],
      modes: [{ mode_name: "💻Focus", level: 5, description: "", color: "#38bdf8" }],
      task_types: [
        { emoji: "💻", name: "Coding", description: "", tag: "High Cognitive" },
        { emoji: "✍️", name: "DeepWriting", description: "", tag: "High Cognitive" },
        { emoji: "🔬", name: "Research", description: "", tag: "High Cognitive" },
      ],
      source: "test",
      revision: 1,
      updated_at: null,
    };

    const single = { tags: { "Task Type": "💻| Coding" } };
    expect(taskTypeEmojisForNode(single, mockConfig)).toEqual(["💻"]);

    const multi = { tags: { "Task Type": "💻| Coding, ✍️| DeepWriting" } };
    expect(taskTypeEmojisForNode(multi, mockConfig)).toEqual(["💻", "✍️"]);

    // Matches from config even without emoji prefix in tag
    const nameOnly = { tags: { "Task Type": "Research" } };
    expect(taskTypeEmojisForNode(nameOnly, mockConfig)).toEqual(["🔬"]);
  });

  it("extracts mode info and styles the horizontal line edge at top left", () => {
    const mockConfig: YoncConfig = {
      themes: [],
      modes: [{ mode_name: "💻Focus", level: 5, description: "", color: "#db2777" }],
      task_types: [],
      source: "test",
      revision: 1,
      updated_at: null,
    };

    const node = { tags: { Modes: "💻Focus" } };
    const mode = modeInfoForNode(node, mockConfig);
    expect(mode).toEqual({ raw: "💻Focus", name: "💻Focus", color: "#db2777" });

    const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    expect(styles).toContain(".node-mode-text");
    expect(styles).toContain(".node-mode-text.ring-passed");
    expect(styles).toContain(".node-task-emoji");
  });

  it("extracts task theme name and color from settings and styles theme capsule pill before WBS", () => {
    const mockConfig: YoncConfig = {
      themes: [
        { name: "PhDSettle✒", color: "#38bdf8", sub_themes: ["Research", "Thesis"] },
        { name: "鍛造Lab", color: "#a855f7", sub_themes: ["Dev"] },
      ],
      modes: [],
      task_types: [],
      source: "test",
      revision: 1,
      updated_at: null,
    };

    const directNode = { id: "n1", parent_id: null, tags: { "Task Theme with colour": "PhDSettle✒ Research | Review" } };
    expect(themeInfoForNode(directNode, mockConfig)).toEqual({ name: "PhDSettle✒", color: "#38bdf8" });

    const parentNode = { id: "p1", parent_id: null, tags: { "Task Theme with colour": "鍛造Lab Dev" } };
    const childNode = { id: "c1", parent_id: "p1", tags: {} };
    const nodesById = new Map([["p1", parentNode], ["c1", childNode]]);
    expect(themeInfoForNode(childNode, mockConfig, nodesById)).toEqual({ name: "鍛造Lab", color: "#a855f7" });

    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    expect(app).toContain("node-theme-pill");
    expect(styles).toContain(".node-theme-pill");
    expect(styles).toContain(".node-card[data-wbs-level=\"4\"] .node-theme-pill");
  });

  it("supports draggable theme rows with handle and step buttons in Settings", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    expect(app).toContain("theme-drag-handle");
    expect(app).toContain("drag-grip");
    expect(app).toContain("theme-step-buttons");
    expect(app).toContain("moveTheme");
    expect(styles).toContain(".theme-row");
    expect(styles).toContain(".theme-row.dragging");
    expect(styles).toContain(".theme-row.drag-over");
    expect(styles).toContain(".theme-drag-handle");
  });

  it("arranges unscheduled tasks grouped by theme with first 3 themes in columns near Today and subsequent themes in a 2D grid", () => {
    const mockConfig: YoncConfig = {
      themes: [
        { name: "Theme1_PhD", color: "red", sub_themes: [] },
        { name: "Theme2_Lab", color: "purple", sub_themes: [] },
        { name: "Theme3_Week", color: "blue", sub_themes: [] },
        { name: "Theme4_Side", color: "green", sub_themes: [] },
        { name: "Theme5_Self", color: "yellow", sub_themes: [] },
      ],
      modes: [],
      task_types: [],
      source: "test",
      revision: 1,
      updated_at: null,
    };

    const nodes = [
      { id: "t1-a", parent_id: null, wbs_level: 2, planned_start: null, deadline: null, tags: { "Task Theme with colour": "Theme1_PhD" } },
      { id: "t1-b", parent_id: null, wbs_level: 3, planned_start: null, deadline: null, tags: { "Task Theme with colour": "Theme1_PhD" } },
      { id: "t2-a", parent_id: null, wbs_level: 2, planned_start: null, deadline: null, tags: { "Task Theme with colour": "Theme2_Lab" } },
      { id: "t3-a", parent_id: null, wbs_level: 2, planned_start: null, deadline: null, tags: { "Task Theme with colour": "Theme3_Week" } },
      { id: "t4-a", parent_id: null, wbs_level: 3, planned_start: null, deadline: null, tags: { "Task Theme with colour": "Theme4_Side" } },
      { id: "t4-b", parent_id: null, wbs_level: 3, planned_start: null, deadline: null, tags: { "Task Theme with colour": "Theme4_Side" } },
      { id: "t5-a", parent_id: null, wbs_level: 3, planned_start: null, deadline: null, tags: { "Task Theme with colour": "Theme5_Self" } },
    ];
    const seed = Object.fromEntries(nodes.map((n) => [n.id, { x: 500, y: 500 }]));
    const result = arrangeCanvasFamilies(nodes, seed, {}, 1000, 48, mockConfig);

    // Theme 1, 2, 3 should all be stacked in a single vertical column (竖列) starting at todayX + 120 = 1120
    expect(result["t1-a"].x).toBe(1120);
    expect(result["t1-b"].x).toBe(1120);
    expect(result["t1-b"].y).toBeGreaterThan(result["t1-a"].y); // column vertical stack

    // Theme 2 should be in the same vertical column beneath Theme 1
    expect(result["t2-a"].x).toBe(1120);
    expect(result["t2-a"].y).toBeGreaterThan(result["t1-b"].y);

    // Theme 3 should be in the same vertical column beneath Theme 2
    expect(result["t3-a"].x).toBe(1120);
    expect(result["t3-a"].y).toBeGreaterThan(result["t2-a"].y);

    // Theme 4 & 5 (subsequent themes) should be in the right corner area
    expect(result["t4-a"].x).toBeGreaterThanOrEqual(1000 + 1200);
    expect(result["t4-b"].x).toBeGreaterThan(result["t4-a"].x); // 2D grid row
    expect(result["t5-a"].x).toBeGreaterThan(result["t3-a"].x);
  });

  it("preserves relative angles, orientation, and directions within an L1 constellation while tidying overlaps", () => {
    // Construct an L1 family where L1 is at (500, 500),
    // L2 is placed above L1 (500, 300) -> angle -90 deg,
    // L3 is placed to the left of L1 (250, 500) -> angle 180 deg.
    const constellationNodes = [
      { id: "root-l1", parent_id: null, wbs_level: 1, planned_start: null, deadline: null, tags: { "Task Theme with colour": "Theme1_PhD" } },
      { id: "child-l2-top", parent_id: "root-l1", wbs_level: 2, planned_start: null, deadline: null, tags: { "Task Theme with colour": "Theme1_PhD" } },
      { id: "child-l3-left", parent_id: "root-l1", wbs_level: 3, planned_start: null, deadline: null, tags: { "Task Theme with colour": "Theme1_PhD" } },
    ];
    const seed = {
      "root-l1": { x: 500, y: 500 },
      "child-l2-top": { x: 500, y: 300 },
      "child-l3-left": { x: 250, y: 500 },
    };

    const tidied = tidyConstellationPositions(constellationNodes, seed, {});
    // L2 should remain above L1 (smaller Y)
    expect(tidied.positions["child-l2-top"].y).toBeLessThan(tidied.positions["root-l1"].y);
    // L3 should remain to the left of L1 (smaller X)
    expect(tidied.positions["child-l3-left"].x).toBeLessThan(tidied.positions["root-l1"].x);

    // Now verify within arrangeCanvasFamilies
    const mockConfig: YoncConfig = {
      themes: [{ name: "Theme1_PhD", color: "red", sub_themes: [] }],
      modes: [],
      task_types: [],
      source: "test",
      revision: 1,
      updated_at: null,
    };
    const arranged = arrangeCanvasFamilies(constellationNodes, seed, {}, 1000, 48, mockConfig);
    expect(arranged["child-l2-top"].y).toBeLessThan(arranged["root-l1"].y);
    expect(arranged["child-l3-left"].x).toBeLessThan(arranged["root-l1"].x);
  });

  it("preserves viewport zoom, percentage, and scroll position after Auto Arrange instead of reverting to fit", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    expect(app).toContain("preserveViewportAfterArrange");
    expect(app).toContain("autoArrangeAll = (shouldFit = false)");
    expect(app).toContain("canvasRef.current.scrollTo({ left: snap.left, top: snap.top })");
  });

  it("arranges UNCLASSIFIED group tasks starting from bottom centre", () => {
    const mockConfig: YoncConfig = {
      themes: [
        { name: "Theme1_PhD", color: "red", sub_themes: [] },
        { name: "Theme2_Lab", color: "blue", sub_themes: [] },
      ],
      modes: [],
      task_types: [],
      source: "test",
      revision: 1,
      updated_at: null,
    };

    const nodes = [
      // Theme 1 structured task (WBS 2)
      { id: "t1-a", parent_id: null, wbs_level: 2, work_type: "DELIVERABLE", planned_start: null, deadline: null, tags: { "Task Theme with colour": "Theme1_PhD" } },
      // UNCLASSIFIED tasks
      { id: "unclass-1", parent_id: null, wbs_level: null, work_type: "UNCLASSIFIED", planned_start: null, deadline: null, tags: {} },
      { id: "unclass-2", parent_id: null, wbs_level: null, work_type: "UNCLASSIFIED", planned_start: null, deadline: null, tags: {} },
    ];
    const seed = Object.fromEntries(nodes.map((n) => [n.id, { x: 500, y: 500 }]));
    const result = arrangeCanvasFamilies(nodes, seed, {}, 1000, 48, mockConfig);

    // Theme 1 task should be near todayX (1000 + 120 = 1120) with Y at top (82)
    expect(result["t1-a"].x).toBe(1120);
    expect(result["t1-a"].y).toBe(82);

    // UNCLASSIFIED tasks should be arranged at Bottom Centre:
    // Y should start at bottom (e.g. >= 700)
    expect(result["unclass-1"].y).toBeGreaterThanOrEqual(700);
    expect(result["unclass-2"].y).toBeGreaterThanOrEqual(700);

    // X should be centered around the primary area (near todayX / primaryCenterX)
    expect(result["unclass-1"].x).toBeGreaterThanOrEqual(1000);
    expect(result["unclass-2"].x).toBeGreaterThan(result["unclass-1"].x);

    // Helper checks
    expect(isUnclassifiedNode(nodes[1])).toBe(true);
    expect(isUnclassifiedNode(nodes[0])).toBe(false);
    expect(isUnclassifiedConstellation({ members: [nodes[1], nodes[2]] })).toBe(true);
    expect(isUnclassifiedConstellation({ members: [nodes[0]] })).toBe(false);
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

  it("supports scroll-to-view inline editing for execution definitions, deadlines, and done confirmations", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    // Hides Open Split for actions
    expect(app).toContain("!isAction ?");
    expect(app).toContain("Open Split");
    expect(app).toContain("Edit Execution");
    // Scroll-to-view and inline editing for execution definition
    expect(app).toContain("scrollToExecution");
    expect(app).toContain("scrollIntoView");
    expect(app).toContain("saveExecution");
    expect(app).toContain("start_cue: startCue.trim() || null");
    expect(app).toContain("done_when: doneWhen.trim() || null");
    // Scroll-to-view and inline editing for deadline (accessed via detail grid, deleted from bottom bar)
    expect(app).toContain("scrollToDeadline");
    expect(app).toContain("saveDeadline");
    expect(app).not.toContain("<button onClick={scrollToDeadline}>Edit Deadline</button>");
    // Inline description editing
    expect(app).toContain("scrollToDescription");
    expect(app).toContain("saveDescription");
    // Scroll-to-view and inline confirmation for mark done & undo done
    expect(app).toContain("scrollToDone");
    expect(app).toContain("performDone");
    expect(app).toContain("scrollToReopen");
    expect(app).toContain("performReopen");
    expect(app).toContain("Undo Done");
    expect(app).toContain("inline-confirm-box");
    // Timeline range inspector supports deadline
    expect(app).toContain("<label className=\"field\">Deadline");
    expect(app).toContain("setRangeDeadline(event.target.value)");
    // Styles
    expect(styles).toContain(".link-action");
    expect(styles).toContain(".icon-action-btn");
    expect(styles).toContain(".hover-edit-trigger .edit-icon");
    expect(styles).toContain(".execution-edit-box");
    expect(styles).toContain(".description-edit-box");
    expect(styles).toContain(".inline-confirm-box");
    expect(styles).toContain(".inline-edit-field");
    expect(styles).toContain("scroll-behavior: smooth");
  });

  it("calculates range end from start and duration", () => {
    expect(calculateRangeEnd("2026-09-17", 3)).toBe("2026-09-19");
    expect(calculateRangeEnd("2026-09-17", 1)).toBe("2026-09-17");
  });

  it("calculates duration from start and end dates", () => {
    expect(calculateRangeDuration("2026-09-17", "2026-09-19")).toBe(3);
    expect(calculateRangeDuration("2026-09-17", "2026-09-17")).toBe(1);
    expect(calculateRangeDuration("2026-09-19", "2026-09-17")).toBe(1);
  });

  it("renders range triplet inputs and remove from timeline button", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    expect(app).toContain("range-triplet-group");
    expect(app).toContain("duration-field");
    expect(app).toContain("btn-remove-timeline");
    expect(app).toContain("Remove from Timeline");
    expect(styles).toContain(".range-triplet-group");
    expect(styles).toContain(".btn-remove-timeline");
  });

  it("supports Mark Cancel with mandatory reason comment, cascade warning, and red-grey cross styling", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    const apiFile = readFileSync(new URL("./api.ts", import.meta.url), "utf8");

    // api.transition supports cascade
    expect(apiFile).toContain("cascade = true");

    // Inspector buttons
    expect(app).toContain("Mark Cancel");
    expect(app).toContain("btn-mark-cancel");
    expect(app).toContain("Undo Cancel");

    // Mandatory reason comment input & cascade warning in App.tsx
    expect(app).toContain("cancelReasonInputRef");
    expect(app).toContain("cancel-reason-input");
    expect(app).toContain("cancel-confirm-box");
    expect(app).toContain("cancel-cascade-warning");
    expect(app).toContain("status-cancelled-info");
    expect(app).toContain("cancelled-reason-tag");
    expect(app).toContain("请输入取消原因（必填）");

    // NodeCard cancelled visual styling in styles.css
    expect(styles).toContain(".node-card.status-cancelled");
    expect(styles).toContain(".node-card.status-cancelled .node-state::before");
    expect(styles).toContain("content: \"✕\"");
    expect(styles).toContain(".node-card.status-cancelled::after");
    // Cross overlay contains red-grey diagonal lines and crosshatch
    expect(styles).toContain("%23ef4444"); // Red line in SVG
    expect(styles).toContain("%2394a3b8"); // Slate grey line in SVG
    expect(styles).toContain("repeating-linear-gradient(45deg");
    expect(styles).toContain("repeating-linear-gradient(-45deg");
    // Crown only belongs to status-done, not status-cancelled
    expect(styles).not.toContain(".node-card.status-cancelled::after {\n  content: \"\";\n  position: absolute;\n  top: -8px");

    // Inspector styles
    expect(styles).toContain(".btn-mark-cancel");
    expect(styles).toContain(".cancel-confirm-box");
    expect(styles).toContain(".cancel-reason-input");
    expect(styles).toContain(".cancel-cascade-warning");
    expect(styles).toContain(".cancelled-reason-tag");
    expect(styles).toContain(".btn-sm.danger");
  });
});

describe("Notion Toggle List View (v2-LineV2)", () => {
  it("integrates List view into sidebar right after Canvas and before Timeline", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    expect(app).toContain('type MainView = "canvas" | "list" | "timeline" | "split";');
    expect(app).toContain('<button className={view === "list" ? "active" : ""} onClick={() => setView("list")} aria-label="List"><span>☰</span><small>List</small></button>');
    expect(app).toContain('<ListView graph={graph}');
    // NodeInspector floating sidebar is restricted to Canvas only, not appearing on List view
    expect(app).toContain('{view === "canvas" && selected && <NodeInspector');
  });

  it("exposes notionTasklist in api client and imports NotionTaskItem", () => {
    const apiFile = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
    expect(apiFile).toContain('notionTasklist: () => request<NotionTaskItem[]>("/api/v2/tasklist-state")');
  });

  it("includes comprehensive Notion and sliding search styling in styles.css", () => {
    const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    expect(styles).toContain(".notion-list-view");
    expect(styles).toContain(".notion-compact-header");
    expect(styles).toContain(".notion-sliding-search");
    expect(styles).toContain(".notion-row");
    expect(styles).toContain(".notion-toggle-btn");
    expect(styles).toContain(".notion-checkbox");
    expect(styles).toContain(".notion-indent-line");
    expect(styles).toContain(".notion-drag-handle");
    expect(styles).toContain(".level-title-1");
    expect(styles).toContain(".notion-inline-editor");
    expect(styles).toContain(".tag-options-popover");
    expect(styles).toContain(".notion-badge-theme");
    expect(styles).toContain(".notion-badge-tasktype");
    expect(styles).toContain(".notion-badge-mode");
    expect(styles).toContain(".search-mark");
  });
});

describe("Direction (Phase Annotation Layer)", () => {
  it("exposes direction CRUD endpoints in api client", () => {
    const apiFile = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
    expect(apiFile).toContain('directions: () => request<Direction[]>("/api/v2/directions")');
    expect(apiFile).toContain('createDirection: (payload: DirectionCreatePayload)');
    expect(apiFile).toContain('updateDirection: (directionId: string, payload: DirectionUpdatePayload)');
    expect(apiFile).toContain('deleteDirection: (directionId: string');
  });

  it("integrates Direction sub-mode into Timeline toolbar and App state", () => {
    const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
    expect(app).toContain('type TimelineMode = "forecast" | "capacity" | "directions";');
    expect(app).toContain('const [directions, setDirections] = useState<Direction[]>([]);');
    expect(app).toContain('<button className={mode === "directions" ? "active" : ""} onClick={() => onMode("directions")}>Direction List</button>');
    expect(app).toContain('directions={directions}');
    expect(app).toContain('className="direction-lanes-strip"');
    expect(app).toContain('className="direction-capsule"');
    expect(app).toContain('className="direction-bridge"');
    expect(app).toContain('FloatingDirectionTag');
  });

  it("places the [+ 新建 Direction] button at the bottom below the last item in DirectionListView", () => {
    const listFile = readFileSync(new URL("./DirectionListView.tsx", import.meta.url), "utf8");
    expect(listFile).toContain("btn-add-direction-bottom");
    expect(listFile).toContain("direction-list-footer");
    // Ensure footer with add button appears after mapped months
    const monthsIndex = listFile.indexOf("monthKeys.map");
    const footerIndex = listFile.indexOf("direction-list-footer");
    expect(monthsIndex).toBeGreaterThan(-1);
    expect(footerIndex).toBeGreaterThan(monthsIndex);
  });

  it("defines comprehensive styles for capsules, bridges, tags, and bottom button in styles.css", () => {
    const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    expect(styles).toContain(".direction-drag-selected");
    expect(styles).toContain(".direction-capsule");
    expect(styles).toContain(".direction-bridge");
    expect(styles).toContain(".direction-lanes-strip");
    expect(styles).toContain(".floating-direction-tag");
    expect(styles).toContain(".direction-pointer-arrow");
    expect(styles).toContain(".direction-draft-modal");
    expect(styles).toContain(".direction-list-view");
    expect(styles).toContain(".btn-add-direction-bottom");
  });
});


