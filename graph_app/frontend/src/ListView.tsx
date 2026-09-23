import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { GraphNode, GraphResponse, YoncConfig } from "./types";
import { themeInfoForNode } from "./App";

export type UndoAction = { kind: "local"; undo: () => Promise<void> | void } | { kind: "batch"; batchId: string };

const TASK_TYPE_OPTIONS = [
  "💻 Coding",
  "🔬 Research",
  "📖 Reading",
  "✍️ DeepWriting",
  "🤔 Thinking",
  "🔍 Search",
  "🔨 HandyWork",
  "🗺️ Planning",
  "🧩 Structuring",
  "📥 Admin",
  "🔁 Repetitive",
];

const MODE_OPTIONS = [
  "💻Focus",
  "Read",
  "🧠Deep",
  "小Do📱",
  "🧟Zombie",
  "Handy🤘🏻",
  "🧘Jail",
];

interface TreeNode {
  node: GraphNode;
  depth: number;
  children: TreeNode[];
}

function HighlightedText({ text, query, isCurrent }: { text: string; query: string; isCurrent?: boolean }) {
  if (!query || !query.trim() || !text) {
    return <span>{text}</span>;
  }
  const q = query.trim().toLowerCase();
  const lower = text.toLowerCase();
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let index = lower.indexOf(q);

  while (index !== -1) {
    if (index > lastIndex) {
      parts.push(text.slice(lastIndex, index));
    }
    parts.push(
      <mark key={index} className={`search-mark ${isCurrent ? "current-match" : ""}`}>
        {text.slice(index, index + q.length)}
      </mark>
    );
    lastIndex = index + q.length;
    index = lower.indexOf(q, lastIndex);
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return <span>{parts}</span>;
}

const EXPANDED_STORAGE_KEY = "yonc_list_expanded_ids_v2";

export interface SubthemeInfo {
  subtheme: string;
  themeName: string;
  color: string;
}

export function resolveSubthemeInfo(
  node: GraphNode,
  config?: YoncConfig | null,
  nodesById?: ReadonlyMap<string, GraphNode> | Map<string, GraphNode>
): SubthemeInfo | null {
  if (!config?.themes?.length) return null;

  // 1. Check explicit tags on the node itself
  const explicitTags = [
    node.tags?.["theme_display_label"],
    node.tags?.["subtheme"],
    node.tags?.["Subtheme"],
    node.tags?.["Sub-theme"],
    node.tags?.["colour_subtheme"],
  ];
  for (const tagVal of explicitTags) {
    if (typeof tagVal === "string" && tagVal.trim()) {
      const val = tagVal.trim();
      for (const t of config.themes) {
        if (t.sub_themes.some((s) => s.toLowerCase() === val.toLowerCase())) {
          const matchedSub = t.sub_themes.find((s) => s.toLowerCase() === val.toLowerCase()) || val;
          return { subtheme: matchedSub, themeName: t.name, color: t.color };
        }
        if (t.name.toLowerCase() === val.toLowerCase()) {
          return { subtheme: t.name, themeName: t.name, color: t.color };
        }
      }
      return { subtheme: val, themeName: val, color: "#64748b" };
    }
  }

  // 2. Check title against sub_themes of each theme (including walking up parent nodes)
  let current: GraphNode | undefined = node;
  const visited = new Set<string>();
  while (current && !visited.has(current.id)) {
    visited.add(current.id);
    const title = current.title || "";

    for (const t of config.themes) {
      const sortedSubs = [...t.sub_themes].sort((a, b) => b.length - a.length);
      for (const sub of sortedSubs) {
        if (!sub) continue;
        const escaped = sub.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const regex = new RegExp(`(?:\\b|[\\W_])${escaped}(?:\\b|[\\W_])`, "i");
        if (regex.test(title) || title.toLowerCase().includes(sub.toLowerCase())) {
          return { subtheme: sub, themeName: t.name, color: t.color };
        }
      }
    }

    current = current.parent_id && nodesById ? nodesById.get(current.parent_id) : undefined;
  }

  // 3. Check "Task Theme with colour" or "Theme" tag for subthemes or theme name
  current = node;
  visited.clear();
  while (current && !visited.has(current.id)) {
    visited.add(current.id);
    const rawTag = current.tags?.["Task Theme with colour"] ?? current.tags?.["Task Theme"] ?? current.tags?.["Theme"] ?? current.tags?.["theme"];
    const tag = Array.isArray(rawTag) ? rawTag.join(" | ") : String(rawTag ?? "").trim();
    if (tag) {
      for (const t of config.themes) {
        for (const sub of t.sub_themes) {
          if (sub && tag.toLowerCase().includes(sub.toLowerCase())) {
            return { subtheme: sub, themeName: t.name, color: t.color };
          }
        }
        if (tag.includes(t.name)) {
          return { subtheme: t.name, themeName: t.name, color: t.color };
        }
      }
    }
    current = current.parent_id && nodesById ? nodesById.get(current.parent_id) : undefined;
  }

  return null;
}

export function parseNodeContent(title: string, description: string | null | undefined): {
  cleanTitle: string;
  cleanDesc: string;
  isCompleted100: boolean;
  extractedEffort: string | null;
} {
  const isCompleted100 = /💯\s*✅/.test(title);
  let extractedEffort: string | null = null;

  // Extract effort like *0.0h* or *2.5h*
  const effortMatch = title.match(/\*(\d+(?:\.\d+)?h)\*/i);
  if (effortMatch) {
    extractedEffort = effortMatch[1];
  }

  // Remove 💯✅ and *X.Xh* from the title text
  let workingTitle = title
    .replace(/💯\s*✅/g, "")
    .replace(/\*\d+(?:\.\d+)?h\*/gi, "")
    .trim();

  let cleanTitle = workingTitle;
  let cleanDesc = (description || "").trim();

  // If no explicit description is present, look for description indicators inside title
  if (!cleanDesc) {
    if (workingTitle.includes("\n")) {
      const lines = workingTitle.split("\n");
      cleanTitle = lines[0].trim();
      cleanDesc = lines.slice(1).join("\n").trim();
    } else {
      const splitPatterns = [
        /(.*?)\s+(实际\s*Deadline\s*[:：].*)$/i,
        /(.*?)\s+(Deadline\s*[:：].*)$/i,
        /(.*?)\s+(详情见.*)$/i,
      ];
      for (const pattern of splitPatterns) {
        const match = workingTitle.match(pattern);
        if (match && match[1]?.trim() && match[2]?.trim()) {
          cleanTitle = match[1].trim();
          cleanDesc = match[2].trim();
          break;
        }
      }
    }
  }

  return {
    cleanTitle: cleanTitle || workingTitle || "Untitled task",
    cleanDesc,
    isCompleted100,
    extractedEffort,
  };
}

export function nodeHasTimeline(node: GraphNode): boolean {
  if (Boolean(node.deadline || node.planned_start || node.planned_end)) {
    return true;
  }
  if (Boolean(node.tags?.["timeliner_settle_date"] || node.tags?.["Deadline"] || node.tags?.["deadline"])) {
    return true;
  }
  const title = (node.title || "").toLowerCase();
  const desc = (node.description || "").toLowerCase();
  if (
    /deadline\s*[:：]/.test(title) ||
    /截止\s*[:：]/.test(title) ||
    /\d{1,2}\/\d{1,2}\s*完结/.test(title) ||
    /deadline\s*[:：]/.test(desc) ||
    /截止\s*[:：]/.test(desc)
  ) {
    return true;
  }
  return false;
}

export function treeHasTimeline(treeItem: TreeNode): boolean {
  if (nodeHasTimeline(treeItem.node)) return true;
  return treeItem.children.some((child) => treeHasTimeline(child));
}


export function ListView({
  graph,
  yoncConfig,
  selectedIds,
  onSelectionChange,
  onOpenSplit,
  onRefresh,
  onError,
  onRegisterUndo,
}: {
  graph: GraphResponse;
  yoncConfig: YoncConfig | null;
  selectedIds: string[];
  onSelectionChange: (ids: string[]) => void;
  onOpenSplit: (node: GraphNode) => void;
  onRefresh: () => Promise<void>;
  onError: (error: unknown) => void;
  onRegisterUndo: (action: UndoAction) => void;
}) {
  const hasUserSavedExpandRef = useRef<boolean>(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => {
    try {
      const saved = localStorage.getItem(EXPANDED_STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) {
          hasUserSavedExpandRef.current = true;
          return new Set(parsed);
        }
      }
    } catch {}
    return new Set();
  });
  const [customOrder, setCustomOrder] = useState<string[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [currentMatchIndex, setCurrentMatchIndex] = useState(0);
  const [showSuggestions, setShowSuggestions] = useState(false);

  // Inline editing state
  const [editingNodeId, setEditingNodeId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [isSavingEdit, setIsSavingEdit] = useState(false);

  // Editor refs for tracking live input and click-outside auto-save
  const editorContainerRef = useRef<HTMLDivElement>(null);
  const editTitleRef = useRef(editTitle);
  const editDescRef = useRef(editDesc);
  const editingNodeIdRef = useRef(editingNodeId);

  useEffect(() => {
    editTitleRef.current = editTitle;
  }, [editTitle]);

  useEffect(() => {
    editDescRef.current = editDesc;
  }, [editDesc]);

  useEffect(() => {
    editingNodeIdRef.current = editingNodeId;
  }, [editingNodeId]);

  // Popover menus state
  const [activeMenu, setActiveMenu] = useState<{ nodeId: string; type: "taskType" | "mode" } | null>(null);

  // Drag and drop state
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);

  const searchInputRef = useRef<HTMLInputElement>(null);
  const rowRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  // Index nodes by ID
  const nodesById = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph.nodes]);

  // Persist expanded states to localStorage & view-state
  const persistExpanded = useCallback((next: Set<string>) => {
    try {
      localStorage.setItem(EXPANDED_STORAGE_KEY, JSON.stringify(Array.from(next)));
    } catch {}
    api.saveViewState("list", { expanded_ids: Array.from(next) }).catch(() => {});
  }, []);

  // Load custom order and expand state from view-state
  useEffect(() => {
    let cancelled = false;
    api
      .viewState("list")
      .then((state) => {
        if (cancelled) return;
        if (Array.isArray(state?.order)) {
          setCustomOrder(state.order as string[]);
        }
        if (Array.isArray(state?.expanded_ids)) {
          if (!hasUserSavedExpandRef.current) {
            const serverSet = new Set(state.expanded_ids as string[]);
            setExpandedIds(serverSet);
            hasUserSavedExpandRef.current = true;
            try {
              localStorage.setItem(EXPANDED_STORAGE_KEY, JSON.stringify(Array.from(serverSet)));
            } catch {}
          }
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // Build the hierarchical tree from SQL graph nodes
  const treeRoots = useMemo(() => {
    const childrenByParent = new Map<string, GraphNode[]>();
    const roots: GraphNode[] = [];

    // Order map
    const orderIndex = new Map(customOrder.map((id, idx) => [id, idx]));

    const sortFn = (a: GraphNode, b: GraphNode) => {
      const aIdx = orderIndex.get(a.id) ?? 999999;
      const bIdx = orderIndex.get(b.id) ?? 999999;
      if (aIdx !== bIdx) return aIdx - bIdx;
      return (a.wbs_level ?? 99) - (b.wbs_level ?? 99);
    };

    for (const node of graph.nodes) {
      if (!node.parent_id || !nodesById.has(node.parent_id)) {
        roots.push(node);
      } else {
        const existing = childrenByParent.get(node.parent_id) || [];
        existing.push(node);
        childrenByParent.set(node.parent_id, existing);
      }
    }

    roots.sort(sortFn);

    const buildTree = (node: GraphNode, depth: number): TreeNode => {
      const children = (childrenByParent.get(node.id) || []).sort(sortFn).map((child) => buildTree(child, depth + 1));
      return { node, depth, children };
    };

    return roots.map((root) => buildTree(root, 0));
  }, [graph.nodes, nodesById, customOrder]);

  // Default expand root nodes ONLY if user has NEVER saved an expanded state before
  useEffect(() => {
    if (hasUserSavedExpandRef.current) return;
    setExpandedIds((prev) => {
      if (prev.size > 0) return prev;
      const initial = new Set<string>();
      for (const root of treeRoots) {
        initial.add(root.node.id);
        for (const child of root.children) {
          initial.add(child.node.id);
        }
      }
      return initial;
    });
  }, [treeRoots]);

  // Toggle expand/collapse of a node
  const toggleExpand = useCallback(
    (nodeId: string) => {
      hasUserSavedExpandRef.current = true;
      setExpandedIds((prev) => {
        const next = new Set(prev);
        if (next.has(nodeId)) next.delete(nodeId);
        else next.add(nodeId);
        persistExpanded(next);
        return next;
      });
    },
    [persistExpanded]
  );

  // Close search and cancel all highlights
  const handleCloseSearch = useCallback(() => {
    setSearchOpen(false);
    setSearchQuery("");
    setShowSuggestions(false);
    setCurrentMatchIndex(0);
  }, []);

  // Search suggestions: extract words & titles matching query
  const suggestions = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q || q.length < 1) return [];

    const candidates = new Set<string>();

    for (const node of graph.nodes) {
      if (node.title.toLowerCase().includes(q)) {
        candidates.add(node.title.trim());
      }
      const themeTag = node.tags?.["Task Theme with colour"] || node.tags?.["Task Theme"];
      if (typeof themeTag === "string" && themeTag.toLowerCase().includes(q)) {
        candidates.add(themeTag.split(/[|:;]/)[0].trim());
      }
      const taskType = node.tags?.["Task Type"];
      if (typeof taskType === "string" && taskType.toLowerCase().includes(q)) {
        candidates.add(taskType.trim());
      }
      const mode = node.tags?.["Modes"] || node.tags?.["Mode"];
      if (typeof mode === "string" && mode.toLowerCase().includes(q)) {
        candidates.add(mode.trim());
      }
      if (candidates.size >= 8) break;
    }

    return Array.from(candidates).slice(0, 6);
  }, [graph.nodes, searchQuery]);

  // All matching node IDs
  const matchingNodeIds = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return [];

    const matches: string[] = [];
    for (const node of graph.nodes) {
      const titleMatch = node.title.toLowerCase().includes(q);
      const descMatch = node.description ? node.description.toLowerCase().includes(q) : false;
      const tagMatch = Object.values(node.tags || {}).some((v) => String(v).toLowerCase().includes(q));

      if (titleMatch || descMatch || tagMatch) {
        matches.push(node.id);
      }
    }
    return matches;
  }, [graph.nodes, searchQuery]);

  // Auto-expand ancestors when search is active
  useEffect(() => {
    if (!searchQuery.trim() || matchingNodeIds.length === 0) return;

    setExpandedIds((prev) => {
      const next = new Set(prev);
      for (const matchId of matchingNodeIds) {
        let cur = nodesById.get(matchId);
        while (cur && cur.parent_id) {
          next.add(cur.parent_id);
          cur = nodesById.get(cur.parent_id);
        }
      }
      return next;
    });
    setCurrentMatchIndex(0);
  }, [matchingNodeIds, nodesById, searchQuery]);

  // Scroll to current match
  const scrollToMatch = useCallback(
    (index: number) => {
      if (matchingNodeIds.length === 0) return;
      const targetId = matchingNodeIds[index];
      if (!targetId) return;

      let cur = nodesById.get(targetId);
      const ancestorsToExpand: string[] = [];
      while (cur && cur.parent_id) {
        ancestorsToExpand.push(cur.parent_id);
        cur = nodesById.get(cur.parent_id);
      }

      if (ancestorsToExpand.length > 0) {
        setExpandedIds((prev) => {
          const next = new Set(prev);
          ancestorsToExpand.forEach((id) => next.add(id));
          return next;
        });
      }

      setTimeout(() => {
        const el = rowRefs.current.get(targetId);
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }, 60);
    },
    [matchingNodeIds, nodesById]
  );

  const handleNextMatch = useCallback(() => {
    if (matchingNodeIds.length === 0) return;
    const nextIdx = (currentMatchIndex + 1) % matchingNodeIds.length;
    setCurrentMatchIndex(nextIdx);
    scrollToMatch(nextIdx);
  }, [currentMatchIndex, matchingNodeIds.length, scrollToMatch]);

  const handlePrevMatch = useCallback(() => {
    if (matchingNodeIds.length === 0) return;
    const prevIdx = (currentMatchIndex - 1 + matchingNodeIds.length) % matchingNodeIds.length;
    setCurrentMatchIndex(prevIdx);
    scrollToMatch(prevIdx);
  }, [currentMatchIndex, matchingNodeIds.length, scrollToMatch]);

  // Keyboard shortcut Ctrl+F / Cmd+F
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
        e.preventDefault();
        setSearchOpen(true);
        setTimeout(() => searchInputRef.current?.focus(), 100);
      }
      if (e.key === "Escape") {
        if (activeMenu) {
          setActiveMenu(null);
        } else if (editingNodeId) {
          setEditingNodeId(null);
        } else if (searchOpen) {
          handleCloseSearch();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [searchOpen, activeMenu, editingNodeId, handleCloseSearch]);

  // Theme order lookup map
  const themeOrderMap = useMemo(() => {
    const map = new Map<string, number>();
    if (yoncConfig?.themes) {
      yoncConfig.themes.forEach((t, idx) => {
        map.set(t.name.toLowerCase(), idx);
        t.sub_themes.forEach((s) => {
          if (!map.has(s.toLowerCase())) {
            map.set(s.toLowerCase(), idx);
          }
        });
      });
    }
    return map;
  }, [yoncConfig?.themes]);

  const getTreeThemeRank = useCallback(
    (item: TreeNode): number => {
      const subInfo = resolveSubthemeInfo(item.node, yoncConfig, nodesById);
      if (subInfo) {
        const byTheme = themeOrderMap.get(subInfo.themeName.toLowerCase());
        if (byTheme !== undefined) return byTheme;
        const bySub = themeOrderMap.get(subInfo.subtheme.toLowerCase());
        if (bySub !== undefined) return bySub;
      }
      return 999999;
    },
    [nodesById, themeOrderMap, yoncConfig]
  );

  // Split tree roots into Scheduled (with timeline) and Unscheduled (without timeline), sorted by Theme
  const { scheduledRoots, unscheduledRoots } = useMemo(() => {
    const orderIndex = new Map(customOrder.map((id, idx) => [id, idx]));

    const sortSection = (items: TreeNode[], isScheduled: boolean) => {
      return [...items].sort((a, b) => {
        // 1. Theme rank according to config.themes
        const themeA = getTreeThemeRank(a);
        const themeB = getTreeThemeRank(b);
        if (themeA !== themeB) return themeA - themeB;

        // 2. Earliest deadline if scheduled
        if (isScheduled) {
          const getEarliest = (tn: TreeNode): string => {
            let best = tn.node.deadline || tn.node.planned_end || "";
            for (const c of tn.children) {
              const cBest = getEarliest(c);
              if (cBest && (!best || cBest < best)) best = cBest;
            }
            return best;
          };
          const dA = getEarliest(a);
          const dB = getEarliest(b);
          if (dA && dB && dA !== dB) return dA.localeCompare(dB);
          if (dA && !dB) return -1;
          if (!dA && dB) return 1;
        }

        // 3. Custom order or WBS level
        const aIdx = orderIndex.get(a.node.id) ?? 999999;
        const bIdx = orderIndex.get(b.node.id) ?? 999999;
        if (aIdx !== bIdx) return aIdx - bIdx;
        return (a.node.wbs_level ?? 99) - (b.node.wbs_level ?? 99);
      });
    };

    const scheduled: TreeNode[] = [];
    const unscheduled: TreeNode[] = [];

    for (const root of treeRoots) {
      if (treeHasTimeline(root)) {
        scheduled.push(root);
      } else {
        unscheduled.push(root);
      }
    }

    return {
      scheduledRoots: sortSection(scheduled, true),
      unscheduledRoots: sortSection(unscheduled, false),
    };
  }, [treeRoots, customOrder, getTreeThemeRank]);

  // Flatten both sections according to expandedIds
  const { scheduledRows, unscheduledRows } = useMemo(() => {
    const flatten = (roots: TreeNode[]) => {
      const rows: Array<{ node: GraphNode; depth: number; hasChildren: boolean }> = [];
      const traverse = (item: TreeNode) => {
        const hasChildren = item.children.length > 0;
        rows.push({ node: item.node, depth: item.depth, hasChildren });
        if (hasChildren && expandedIds.has(item.node.id)) {
          for (const child of item.children) {
            traverse(child);
          }
        }
      };
      for (const r of roots) {
        traverse(r);
      }
      return rows;
    };

    return {
      scheduledRows: flatten(scheduledRoots),
      unscheduledRows: flatten(unscheduledRoots),
    };
  }, [scheduledRoots, unscheduledRoots, expandedIds]);

  const visibleRows = useMemo(
    () => [...scheduledRows, ...unscheduledRows],
    [scheduledRows, unscheduledRows]
  );

  // Handle Checkbox click
  const handleCheckboxClick = useCallback(
    async (node: GraphNode, e: React.MouseEvent) => {
      e.stopPropagation();
      const isDone = node.status === "DONE";
      const nextAction = isDone ? "reopen" : "done";

      try {
        const result = await api.transition(node.id, nextAction, graph.graph_version);
        onRegisterUndo({ kind: "batch", batchId: result.operation_batch_id });
        await onRefresh();
      } catch (err) {
        onError(err);
      }
    },
    [graph.graph_version, onRefresh, onError, onRegisterUndo]
  );

  // Start double-click inline edit
  const startEdit = useCallback((node: GraphNode, e: React.MouseEvent) => {
    e.stopPropagation();
    const parsed = parseNodeContent(node.title, node.description);
    setEditingNodeId(node.id);
    setEditTitle(parsed.cleanTitle);
    setEditDesc(parsed.cleanDesc);
  }, []);

  // Save inline edit
  const saveEdit = useCallback(
    async (nodeId: string) => {
      const titleToSave = editTitleRef.current.trim();
      if (!titleToSave) return;
      setIsSavingEdit(true);
      try {
        const result = await api.patchNode(
          nodeId,
          { title: titleToSave, description: editDescRef.current.trim() || null },
          graph.graph_version
        );
        onRegisterUndo({ kind: "batch", batchId: result.operation_batch_id });
        setEditingNodeId(null);
        await onRefresh();
      } catch (err) {
        onError(err);
      } finally {
        setIsSavingEdit(false);
      }
    },
    [graph.graph_version, onRefresh, onError, onRegisterUndo]
  );

  // Click-outside auto-save effect
  useEffect(() => {
    if (!editingNodeId) return;

    const handlePointerDownOutside = (e: MouseEvent | TouchEvent) => {
      if (editorContainerRef.current && !editorContainerRef.current.contains(e.target as Node)) {
        const currentNodeId = editingNodeIdRef.current;
        if (currentNodeId && editTitleRef.current.trim() && !isSavingEdit) {
          saveEdit(currentNodeId);
        }
      }
    };

    document.addEventListener("mousedown", handlePointerDownOutside);
    document.addEventListener("touchstart", handlePointerDownOutside);
    return () => {
      document.removeEventListener("mousedown", handlePointerDownOutside);
      document.removeEventListener("touchstart", handlePointerDownOutside);
    };
  }, [editingNodeId, isSavingEdit, saveEdit]);

  // Change Task Type via popup menu
  const selectTaskType = useCallback(
    async (node: GraphNode, option: string | null) => {
      setActiveMenu(null);
      const nextTags = { ...(node.tags || {}) };
      if (!option) {
        delete nextTags["Task Type"];
      } else {
        nextTags["Task Type"] = option;
      }
      try {
        const result = await api.patchNode(node.id, { tags: nextTags }, graph.graph_version);
        onRegisterUndo({ kind: "batch", batchId: result.operation_batch_id });
        await onRefresh();
      } catch (err) {
        onError(err);
      }
    },
    [graph.graph_version, onRefresh, onError, onRegisterUndo]
  );

  // Change Mode via popup menu
  const selectMode = useCallback(
    async (node: GraphNode, option: string | null) => {
      setActiveMenu(null);
      const nextTags = { ...(node.tags || {}) };
      if (!option) {
        delete nextTags["Modes"];
        delete nextTags["Mode"];
      } else {
        nextTags["Modes"] = option;
      }
      try {
        const result = await api.patchNode(node.id, { tags: nextTags }, graph.graph_version);
        onRegisterUndo({ kind: "batch", batchId: result.operation_batch_id });
        await onRefresh();
      } catch (err) {
        onError(err);
      }
    },
    [graph.graph_version, onRefresh, onError, onRegisterUndo]
  );

  // Drag and Drop reordering
  const handleDragStart = useCallback((nodeId: string, e: React.DragEvent) => {
    e.dataTransfer.setData("text/plain", nodeId);
    e.dataTransfer.effectAllowed = "move";
    setDraggingId(nodeId);
  }, []);

  const handleDragOver = useCallback(
    (targetId: string, e: React.DragEvent) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      if (dragOverId !== targetId) {
        setDragOverId(targetId);
      }
    },
    [dragOverId]
  );

  const handleDrop = useCallback(
    (targetId: string, e: React.DragEvent) => {
      e.preventDefault();
      const sourceId = e.dataTransfer.getData("text/plain") || draggingId;
      setDraggingId(null);
      setDragOverId(null);

      if (!sourceId || sourceId === targetId) return;

      const currentOrderList = customOrder.length > 0 ? [...customOrder] : graph.nodes.map((n) => n.id);
      const fromIdx = currentOrderList.indexOf(sourceId);
      const toIdx = currentOrderList.indexOf(targetId);

      if (fromIdx !== -1 && toIdx !== -1) {
        currentOrderList.splice(fromIdx, 1);
        currentOrderList.splice(toIdx, 0, sourceId);
        setCustomOrder(currentOrderList);
        api.saveViewState("list", { order: currentOrderList }).catch(() => {});
      }
    },
    [customOrder, draggingId, graph.nodes]
  );

  // Formatted date helper
  const renderDate = (dateStr: string | null) => {
    if (!dateStr) return null;
    try {
      const d = new Date(`${dateStr}T12:00:00`);
      return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    } catch {
      return dateStr;
    }
  };

  // Formatted effort helper
  const renderEffort = (minutes: number | null) => {
    if (!minutes || minutes <= 0) return null;
    return minutes >= 60 ? `${(minutes / 60).toFixed(1)}h` : `${minutes}m`;
  };

  // Clean Task Type formatting
  const cleanTaskType = (raw: unknown) => {
    if (!raw || typeof raw !== "string") return null;
    return raw
      .split(",")
      .map((part) => part.replace(/\|\s*/, " ").trim())
      .join(" · ");
  };

  const currentMatchNodeId = matchingNodeIds[currentMatchIndex] || null;

  return (
    <div className="notion-list-view" onClick={() => setActiveMenu(null)}>
      {/* Sleek Minimal Top Navigation Bar */}
      <header className="notion-compact-header">
        <div className="notion-compact-left">
          <span className="notion-compact-title">Task List</span>
          <span className="notion-compact-count">({graph.nodes.length})</span>
        </div>

        <div className="notion-compact-right">
          {/* Graphical Search Icon Button */}
          <button
            className={`notion-search-graphic-btn ${searchOpen ? "active" : ""}`}
            onClick={() => {
              if (searchOpen) {
                handleCloseSearch();
              } else {
                setSearchOpen(true);
                setTimeout(() => searchInputRef.current?.focus(), 100);
              }
            }}
            title="Search & highlight (Ctrl+F)"
            aria-label="Search"
          >
            <svg viewBox="0 0 24 24" className="search-svg-icon" fill="none" stroke="currentColor" strokeWidth="2.2">
              <circle cx="11" cy="11" r="7" />
              <line x1="16.5" y1="16.5" x2="21" y2="21" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      </header>

      {/* Sliding Search Bar from Right to Left */}
      <div className={`notion-sliding-search ${searchOpen ? "open" : ""}`}>
        <div className="sliding-search-inner">
          <div className="sliding-search-input-wrap">
            <svg viewBox="0 0 24 24" className="search-input-svg" fill="none" stroke="currentColor" strokeWidth="2.2">
              <circle cx="11" cy="11" r="7" />
              <line x1="16.5" y1="16.5" x2="21" y2="21" strokeLinecap="round" />
            </svg>
            <input
              ref={searchInputRef}
              type="text"
              className="sliding-search-input"
              placeholder="Type keyword to highlight…"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setShowSuggestions(true);
              }}
              onFocus={() => setShowSuggestions(true)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  if (e.shiftKey) handlePrevMatch();
                  else handleNextMatch();
                  setShowSuggestions(false);
                }
              }}
            />
            {searchQuery && (
              <button
                className="sliding-search-clear"
                onClick={() => {
                  setSearchQuery("");
                  setShowSuggestions(false);
                }}
              >
                ✕
              </button>
            )}

            {/* Fast Suggestion Dropdown */}
            {showSuggestions && suggestions.length > 0 && (
              <div className="sliding-suggestions-dropdown">
                {suggestions.map((sugg, idx) => (
                  <div
                    key={idx}
                    className="sliding-suggestion-item"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      setSearchQuery(sugg);
                      setShowSuggestions(false);
                    }}
                  >
                    <span className="sugg-icon">↳</span>
                    <span className="sugg-text">{sugg}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Matches Navigation */}
          {searchQuery && (
            <div className="sliding-search-nav">
              <span className="sliding-search-count">
                {matchingNodeIds.length > 0 ? `${currentMatchIndex + 1} of ${matchingNodeIds.length}` : "0 matches"}
              </span>
              <button
                className="sliding-nav-btn"
                onClick={handlePrevMatch}
                disabled={matchingNodeIds.length === 0}
                title="Previous match (Shift+Enter)"
              >
                ↑
              </button>
              <button
                className="sliding-nav-btn"
                onClick={handleNextMatch}
                disabled={matchingNodeIds.length === 0}
                title="Next match (Enter)"
              >
                ↓
              </button>
            </div>
          )}

          {/* Close Search Drawer (Cancels highlight) */}
          <button className="sliding-close-btn" onClick={handleCloseSearch} title="Close search (Esc)">
            ✕
          </button>
        </div>
      </div>

      {/* Main Task List Tree */}
      <main className="notion-tree-container">
        <div className="notion-tree-list" role="tree">
          {/* 1. Scheduled Tasks Section (With Timeline) */}
          {scheduledRows.length > 0 && (
            <div className="notion-list-section scheduled-section">
              <div className="notion-list-section-header scheduled-header">
                <span className="section-header-icon">⏱</span>
                <span className="section-header-title">Scheduled · With Timeline</span>
                <span className="section-header-count">
                  ({scheduledRoots.length} {scheduledRoots.length === 1 ? "theme" : "themes"} · {scheduledRows.length} tasks)
                </span>
              </div>
              {scheduledRows.map(({ node, depth, hasChildren }) => {
                const isExpanded = expandedIds.has(node.id);
                const isDone = node.status === "DONE";
                const isAction = node.work_type === "ACTION" || node.wbs_level === 4;
                const isCurrentMatch = node.id === currentMatchNodeId;
                const isEditing = editingNodeId === node.id;
                const wbs = node.wbs_level || (depth === 0 ? 1 : depth === 1 ? 2 : depth === 2 ? 3 : 4);

                const parsed = parseNodeContent(node.title, node.description);
                const isCompleted100 = isDone || parsed.isCompleted100 || (node.progress && node.progress.ratio === 1);

                const subthemeInfo = resolveSubthemeInfo(node, yoncConfig, nodesById);
                const rawTaskType = node.tags?.["Task Type"];
                const formattedTaskType = cleanTaskType(rawTaskType);
                const rawMode = node.tags?.["Modes"] || node.tags?.["Mode"];
                const deadline = node.deadline;
                const effort = node.estimated_effort_minutes;
                const displayEffort = effort ? renderEffort(effort) : parsed.extractedEffort ? parsed.extractedEffort : null;

                return (
                  <div
                    key={node.id}
                    ref={(el) => {
                      if (el) rowRefs.current.set(node.id, el);
                      else rowRefs.current.delete(node.id);
                    }}
                    className={`notion-row level-${wbs} depth-${depth} ${isCompleted100 ? "is-done is-grayed-row" : ""} ${isCurrentMatch ? "is-active-match" : ""} ${draggingId === node.id ? "is-dragging" : ""} ${dragOverId === node.id ? "is-drag-over" : ""}`}
                    style={{ paddingLeft: `${depth * 22 + 10}px` }}
                    onClick={() => {
                      if (!isEditing && hasChildren) {
                        toggleExpand(node.id);
                      }
                    }}
                    onDragOver={(e) => handleDragOver(node.id, e)}
                    onDrop={(e) => handleDrop(node.id, e)}
                    role="treeitem"
                    aria-expanded={hasChildren ? isExpanded : undefined}
                  >
                    {depth > 0 && (
                      <div className="notion-indent-line" style={{ left: `${(depth - 1) * 22 + 18}px` }} />
                    )}

                    <div
                      className="notion-drag-handle"
                      draggable
                      onDragStart={(e) => handleDragStart(node.id, e)}
                      onClick={(e) => e.stopPropagation()}
                      title="Drag to reorder"
                    >
                      ⠿
                    </div>

                    <div className="notion-toggle-cell">
                      {hasChildren ? (
                        <button
                          className={`notion-toggle-btn level-toggle-${wbs} ${isExpanded ? "expanded" : ""}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleExpand(node.id);
                          }}
                          aria-label={isExpanded ? "Collapse" : "Expand"}
                        >
                          <svg viewBox="0 0 100 100" className="notion-toggle-svg">
                            <polygon points="25,15 80,50 25,85" />
                          </svg>
                        </button>
                      ) : (
                        <span className="notion-toggle-spacer" />
                      )}
                    </div>

                    <div className="notion-control-cell">
                      {isAction ? (
                        <button
                          type="button"
                          className={`notion-checkbox ${isDone ? "checked" : ""}`}
                          onClick={(e) => handleCheckboxClick(node, e)}
                          title={isDone ? "Mark as TODO" : "Mark as DONE"}
                          aria-checked={isDone}
                        >
                          {isDone && (
                            <svg viewBox="0 0 16 16" className="notion-check-svg">
                              <path
                                d="M13.485 3.515a1 1 0 0 1 0 1.414l-7 7a1 1 0 0 1-1.414 0l-3-3a1 1 0 1 1 1.414-1.414L6 10.086l6.293-6.293a1 1 0 0 1 1.414 0z"
                                fill="currentColor"
                              />
                            </svg>
                          )}
                        </button>
                      ) : null}
                    </div>

                    <div className="notion-content-cell" onDoubleClick={(e) => startEdit(node, e)}>
                      {isEditing ? (
                        <div
                          ref={editorContainerRef}
                          className="notion-inline-editor"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <div className="inline-edit-field">
                            <span className="inline-field-label">Title</span>
                            <input
                              type="text"
                              className="inline-edit-title"
                              value={editTitle}
                              onChange={(e) => setEditTitle(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") saveEdit(node.id);
                                if (e.key === "Escape") setEditingNodeId(null);
                              }}
                              autoFocus
                              placeholder="Task title (Title column)…"
                            />
                          </div>
                          <div className="inline-edit-field">
                            <span className="inline-field-label">Description</span>
                            <textarea
                              className="inline-edit-desc"
                              rows={2}
                              value={editDesc}
                              onChange={(e) => setEditDesc(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) saveEdit(node.id);
                                if (e.key === "Escape") setEditingNodeId(null);
                              }}
                              placeholder="Description or notes (Description column)…"
                            />
                          </div>
                          <div className="inline-edit-actions">
                            <button
                              type="button"
                              className="inline-btn-cancel"
                              onClick={(e) => {
                                e.stopPropagation();
                                setEditingNodeId(null);
                              }}
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              className="inline-btn-save"
                              onClick={(e) => {
                                e.stopPropagation();
                                saveEdit(node.id);
                              }}
                              disabled={isSavingEdit}
                            >
                              {isSavingEdit ? "Saving…" : "Save"}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <div className={`notion-title-text level-title-${wbs}`} title="Double-click to edit">
                            <HighlightedText text={parsed.cleanTitle} query={searchQuery} isCurrent={isCurrentMatch} />
                          </div>
                          {parsed.cleanDesc ? (
                            <div className="notion-desc-preview" title="Double-click to edit">
                              <HighlightedText text={parsed.cleanDesc} query={searchQuery} isCurrent={isCurrentMatch} />
                            </div>
                          ) : null}
                        </>
                      )}
                    </div>

                    <div className="notion-badges-cell" onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        className="notion-row-split-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpenSplit(node);
                        }}
                        title={`Split "${parsed.cleanTitle}" into subtasks (⑂ Split)`}
                      >
                        <span className="split-icon">⑂</span>
                        <span className="split-label">Split</span>
                      </button>

                      <div className="tag-dropdown-wrap">
                        {formattedTaskType ? (
                          <span
                            className="notion-badge notion-badge-tasktype interactive"
                            onClick={() =>
                              setActiveMenu(
                                activeMenu?.nodeId === node.id && activeMenu?.type === "taskType"
                                  ? null
                                  : { nodeId: node.id, type: "taskType" }
                              )
                            }
                            title="Click to change Task Type"
                          >
                            <HighlightedText text={formattedTaskType} query={searchQuery} />
                          </span>
                        ) : (
                          <span
                            className="notion-badge-add interactive"
                            onClick={() => setActiveMenu({ nodeId: node.id, type: "taskType" })}
                            title="Add Task Type"
                          >
                            + Type
                          </span>
                        )}

                        {activeMenu?.nodeId === node.id && activeMenu?.type === "taskType" && (
                          <div className="tag-options-popover">
                            <div className="popover-title">Select Task Type</div>
                            {TASK_TYPE_OPTIONS.map((opt) => (
                              <div
                                key={opt}
                                className={`popover-item ${formattedTaskType === opt.replace(/\|\s*/, " ") ? "selected" : ""}`}
                                onClick={() => selectTaskType(node, opt)}
                              >
                                {opt}
                              </div>
                            ))}
                            {formattedTaskType && (
                              <div className="popover-item clear-item" onClick={() => selectTaskType(node, null)}>
                                ✕ Clear Type
                              </div>
                            )}
                          </div>
                        )}
                      </div>

                      <div className="tag-dropdown-wrap">
                        {rawMode ? (
                          <span
                            className="notion-badge notion-badge-mode interactive"
                            onClick={() =>
                              setActiveMenu(
                                activeMenu?.nodeId === node.id && activeMenu?.type === "mode"
                                  ? null
                                  : { nodeId: node.id, type: "mode" }
                              )
                            }
                            title="Click to change Energy Mode"
                          >
                            <HighlightedText text={String(rawMode)} query={searchQuery} />
                          </span>
                        ) : (
                          <span
                            className="notion-badge-add interactive"
                            onClick={() => setActiveMenu({ nodeId: node.id, type: "mode" })}
                            title="Add Mode"
                          >
                            + Mode
                          </span>
                        )}

                        {activeMenu?.nodeId === node.id && activeMenu?.type === "mode" && (
                          <div className="tag-options-popover">
                            <div className="popover-title">Select Mode</div>
                            {MODE_OPTIONS.map((opt) => (
                              <div
                                key={opt}
                                className={`popover-item ${String(rawMode) === opt ? "selected" : ""}`}
                                onClick={() => selectMode(node, opt)}
                              >
                                {opt}
                              </div>
                            ))}
                            {Boolean(rawMode) && (
                              <div className="popover-item clear-item" onClick={() => selectMode(node, null)}>
                                ✕ Clear Mode
                              </div>
                            )}
                          </div>
                        )}
                      </div>

                      {deadline ? (
                        <span className="notion-badge notion-badge-deadline" title={`Deadline: ${deadline}`}>
                          ⚑ {renderDate(deadline)}
                        </span>
                      ) : null}

                      {displayEffort ? (
                        <span className="notion-badge notion-badge-effort" title={`Estimated: ${displayEffort}`}>
                          ⏱ {displayEffort}
                        </span>
                      ) : null}

                      {isCompleted100 ? (
                        <span className="notion-badge notion-badge-done-100" title="Completed 💯✅">
                          💯✅
                        </span>
                      ) : null}

                      {subthemeInfo ? (
                        <span
                          className="notion-badge notion-badge-theme theme-end"
                          style={{
                            backgroundColor: `${subthemeInfo.color}22`,
                            color: subthemeInfo.color,
                            borderColor: `${subthemeInfo.color}44`,
                          }}
                          title={`Theme: ${subthemeInfo.themeName} · Subtheme: ${subthemeInfo.subtheme}`}
                        >
                          <HighlightedText text={subthemeInfo.subtheme} query={searchQuery} />
                        </span>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* 2. Prominent Dividing Line with Gap between Timeline and Non-Timeline */}
          {scheduledRows.length > 0 && unscheduledRows.length > 0 && (
            <div className="notion-list-section-divider">
              <div className="section-divider-line" />
              <div className="section-divider-pill">
                <span className="divider-icon">📋</span>
                <span className="divider-text">Backlog · Without Timeline</span>
                <span className="divider-count">
                  ({unscheduledRoots.length} {unscheduledRoots.length === 1 ? "theme" : "themes"})
                </span>
              </div>
              <div className="section-divider-line" />
            </div>
          )}

          {/* 3. Unscheduled Tasks Section (Without Timeline) */}
          {unscheduledRows.length > 0 && (
            <div className="notion-list-section unscheduled-section">
              {scheduledRows.length === 0 && (
                <div className="notion-list-section-header">
                  <span className="section-header-icon">📋</span>
                  <span className="section-header-title">Tasks · Without Timeline</span>
                  <span className="section-header-count">
                    ({unscheduledRoots.length} {unscheduledRoots.length === 1 ? "theme" : "themes"})
                  </span>
                </div>
              )}
              {unscheduledRows.map(({ node, depth, hasChildren }) => {
                const isExpanded = expandedIds.has(node.id);
                const isDone = node.status === "DONE";
                const isAction = node.work_type === "ACTION" || node.wbs_level === 4;
                const isCurrentMatch = node.id === currentMatchNodeId;
                const isEditing = editingNodeId === node.id;
                const wbs = node.wbs_level || (depth === 0 ? 1 : depth === 1 ? 2 : depth === 2 ? 3 : 4);

                const parsed = parseNodeContent(node.title, node.description);
                const isCompleted100 = isDone || parsed.isCompleted100 || (node.progress && node.progress.ratio === 1);

                const subthemeInfo = resolveSubthemeInfo(node, yoncConfig, nodesById);
                const rawTaskType = node.tags?.["Task Type"];
                const formattedTaskType = cleanTaskType(rawTaskType);
                const rawMode = node.tags?.["Modes"] || node.tags?.["Mode"];
                const deadline = node.deadline;
                const effort = node.estimated_effort_minutes;
                const displayEffort = effort ? renderEffort(effort) : parsed.extractedEffort ? parsed.extractedEffort : null;

                return (
                  <div
                    key={node.id}
                    ref={(el) => {
                      if (el) rowRefs.current.set(node.id, el);
                      else rowRefs.current.delete(node.id);
                    }}
                    className={`notion-row level-${wbs} depth-${depth} ${isCompleted100 ? "is-done is-grayed-row" : ""} ${isCurrentMatch ? "is-active-match" : ""} ${draggingId === node.id ? "is-dragging" : ""} ${dragOverId === node.id ? "is-drag-over" : ""}`}
                    style={{ paddingLeft: `${depth * 22 + 10}px` }}
                    onClick={() => {
                      if (!isEditing && hasChildren) {
                        toggleExpand(node.id);
                      }
                    }}
                    onDragOver={(e) => handleDragOver(node.id, e)}
                    onDrop={(e) => handleDrop(node.id, e)}
                    role="treeitem"
                    aria-expanded={hasChildren ? isExpanded : undefined}
                  >
                    {depth > 0 && (
                      <div className="notion-indent-line" style={{ left: `${(depth - 1) * 22 + 18}px` }} />
                    )}

                    <div
                      className="notion-drag-handle"
                      draggable
                      onDragStart={(e) => handleDragStart(node.id, e)}
                      onClick={(e) => e.stopPropagation()}
                      title="Drag to reorder"
                    >
                      ⠿
                    </div>

                    <div className="notion-toggle-cell">
                      {hasChildren ? (
                        <button
                          className={`notion-toggle-btn level-toggle-${wbs} ${isExpanded ? "expanded" : ""}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleExpand(node.id);
                          }}
                          aria-label={isExpanded ? "Collapse" : "Expand"}
                        >
                          <svg viewBox="0 0 100 100" className="notion-toggle-svg">
                            <polygon points="25,15 80,50 25,85" />
                          </svg>
                        </button>
                      ) : (
                        <span className="notion-toggle-spacer" />
                      )}
                    </div>

                    <div className="notion-control-cell">
                      {isAction ? (
                        <button
                          type="button"
                          className={`notion-checkbox ${isDone ? "checked" : ""}`}
                          onClick={(e) => handleCheckboxClick(node, e)}
                          title={isDone ? "Mark as TODO" : "Mark as DONE"}
                          aria-checked={isDone}
                        >
                          {isDone && (
                            <svg viewBox="0 0 16 16" className="notion-check-svg">
                              <path
                                d="M13.485 3.515a1 1 0 0 1 0 1.414l-7 7a1 1 0 0 1-1.414 0l-3-3a1 1 0 1 1 1.414-1.414L6 10.086l6.293-6.293a1 1 0 0 1 1.414 0z"
                                fill="currentColor"
                              />
                            </svg>
                          )}
                        </button>
                      ) : null}
                    </div>

                    <div className="notion-content-cell" onDoubleClick={(e) => startEdit(node, e)}>
                      {isEditing ? (
                        <div
                          ref={editorContainerRef}
                          className="notion-inline-editor"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <div className="inline-edit-field">
                            <span className="inline-field-label">Title</span>
                            <input
                              type="text"
                              className="inline-edit-title"
                              value={editTitle}
                              onChange={(e) => setEditTitle(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") saveEdit(node.id);
                                if (e.key === "Escape") setEditingNodeId(null);
                              }}
                              autoFocus
                              placeholder="Task title (Title column)…"
                            />
                          </div>
                          <div className="inline-edit-field">
                            <span className="inline-field-label">Description</span>
                            <textarea
                              className="inline-edit-desc"
                              rows={2}
                              value={editDesc}
                              onChange={(e) => setEditDesc(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) saveEdit(node.id);
                                if (e.key === "Escape") setEditingNodeId(null);
                              }}
                              placeholder="Description or notes (Description column)…"
                            />
                          </div>
                          <div className="inline-edit-actions">
                            <button
                              type="button"
                              className="inline-btn-cancel"
                              onClick={(e) => {
                                e.stopPropagation();
                                setEditingNodeId(null);
                              }}
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              className="inline-btn-save"
                              onClick={(e) => {
                                e.stopPropagation();
                                saveEdit(node.id);
                              }}
                              disabled={isSavingEdit}
                            >
                              {isSavingEdit ? "Saving…" : "Save"}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <div className={`notion-title-text level-title-${wbs}`} title="Double-click to edit">
                            <HighlightedText text={parsed.cleanTitle} query={searchQuery} isCurrent={isCurrentMatch} />
                          </div>
                          {parsed.cleanDesc ? (
                            <div className="notion-desc-preview" title="Double-click to edit">
                              <HighlightedText text={parsed.cleanDesc} query={searchQuery} isCurrent={isCurrentMatch} />
                            </div>
                          ) : null}
                        </>
                      )}
                    </div>

                    <div className="notion-badges-cell" onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        className="notion-row-split-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpenSplit(node);
                        }}
                        title={`Split "${parsed.cleanTitle}" into subtasks (⑂ Split)`}
                      >
                        <span className="split-icon">⑂</span>
                        <span className="split-label">Split</span>
                      </button>

                      <div className="tag-dropdown-wrap">
                        {formattedTaskType ? (
                          <span
                            className="notion-badge notion-badge-tasktype interactive"
                            onClick={() =>
                              setActiveMenu(
                                activeMenu?.nodeId === node.id && activeMenu.type === "taskType"
                                  ? null
                                  : { nodeId: node.id, type: "taskType" }
                              )
                            }
                            title="Click to change Task Type"
                          >
                            <HighlightedText text={formattedTaskType} query={searchQuery} />
                          </span>
                        ) : (
                          <span
                            className="notion-badge-add interactive"
                            onClick={() => setActiveMenu({ nodeId: node.id, type: "taskType" })}
                            title="Add Task Type"
                          >
                            + Type
                          </span>
                        )}

                        {activeMenu?.nodeId === node.id && activeMenu.type === "taskType" && (
                          <div className="tag-options-popover">
                            <div className="popover-title">Select Task Type</div>
                            {TASK_TYPE_OPTIONS.map((opt) => (
                              <div
                                key={opt}
                                className={`popover-item ${formattedTaskType === opt.replace(/\|\s*/, " ") ? "selected" : ""}`}
                                onClick={() => selectTaskType(node, opt)}
                              >
                                {opt}
                              </div>
                            ))}
                            {formattedTaskType && (
                              <div className="popover-item clear-item" onClick={() => selectTaskType(node, null)}>
                                ✕ Clear Type
                              </div>
                            )}
                          </div>
                        )}
                      </div>

                      <div className="tag-dropdown-wrap">
                        {rawMode ? (
                          <span
                            className="notion-badge notion-badge-mode interactive"
                            onClick={() =>
                              setActiveMenu(
                                activeMenu?.nodeId === node.id && activeMenu.type === "mode"
                                  ? null
                                  : { nodeId: node.id, type: "mode" }
                              )
                            }
                            title="Click to change Energy Mode"
                          >
                            <HighlightedText text={String(rawMode)} query={searchQuery} />
                          </span>
                        ) : (
                          <span
                            className="notion-badge-add interactive"
                            onClick={() => setActiveMenu({ nodeId: node.id, type: "mode" })}
                            title="Add Mode"
                          >
                            + Mode
                          </span>
                        )}

                        {activeMenu?.nodeId === node.id && activeMenu.type === "mode" && (
                          <div className="tag-options-popover">
                            <div className="popover-title">Select Mode</div>
                            {MODE_OPTIONS.map((opt) => (
                              <div
                                key={opt}
                                className={`popover-item ${String(rawMode) === opt ? "selected" : ""}`}
                                onClick={() => selectMode(node, opt)}
                              >
                                {opt}
                              </div>
                            ))}
                            {Boolean(rawMode) && (
                              <div className="popover-item clear-item" onClick={() => selectMode(node, null)}>
                                ✕ Clear Mode
                              </div>
                            )}
                          </div>
                        )}
                      </div>

                      {deadline ? (
                        <span className="notion-badge notion-badge-deadline" title={`Deadline: ${deadline}`}>
                          ⚑ {renderDate(deadline)}
                        </span>
                      ) : null}

                      {displayEffort ? (
                        <span className="notion-badge notion-badge-effort" title={`Estimated: ${displayEffort}`}>
                          ⏱ {displayEffort}
                        </span>
                      ) : null}

                      {isCompleted100 ? (
                        <span className="notion-badge notion-badge-done-100" title="Completed 💯✅">
                          💯✅
                        </span>
                      ) : null}

                      {subthemeInfo ? (
                        <span
                          className="notion-badge notion-badge-theme theme-end"
                          style={{
                            backgroundColor: `${subthemeInfo.color}22`,
                            color: subthemeInfo.color,
                            borderColor: `${subthemeInfo.color}44`,
                          }}
                          title={`Theme: ${subthemeInfo.themeName} · Subtheme: ${subthemeInfo.subtheme}`}
                        >
                          <HighlightedText text={subthemeInfo.subtheme} query={searchQuery} />
                        </span>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Empty State */}
          {scheduledRows.length === 0 && unscheduledRows.length === 0 && (
            <div className="notion-empty-state">No tasks found</div>
          )}
        </div>
      </main>
    </div>
  );
}
