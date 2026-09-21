import React, { useState } from "react";
import { api } from "./api";
import type { Direction, YoncConfig } from "./types";

export type UndoAction = { kind: "local"; undo: () => Promise<void> | void } | { kind: "batch"; batchId: string };

const PRESET_COLORS = [
  "#38bdf8", // Sky blue
  "#818cf8", // Indigo
  "#a855f7", // Purple
  "#ec4899", // Pink
  "#f43f5e", // Rose
  "#f59e0b", // Amber
  "#10b981", // Emerald
  "#06b6d4", // Cyan
];

function daysBetween(start: string, end: string): number {
  const d1 = new Date(`${start}T00:00:00`);
  const d2 = new Date(`${end}T00:00:00`);
  return Math.round((d2.getTime() - d1.getTime()) / (1000 * 60 * 60 * 24)) + 1;
}

function formatDateSpan(start: string, end: string): string {
  const span = daysBetween(start, end);
  return `${start} ~ ${end} · ${span}天`;
}

export function DirectionListView({
  directions,
  yoncConfig,
  onLocateInGrid,
  onRefresh,
  onError,
  onRegisterUndo,
}: {
  directions: Direction[];
  yoncConfig: YoncConfig | null;
  onLocateInGrid: (direction: Direction) => void;
  onRefresh: () => Promise<void>;
  onError: (error: unknown) => void;
  onRegisterUndo: (action: UndoAction) => void;
}) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editNotes, setEditNotes] = useState("");
  const [editColor, setEditColor] = useState("#38bdf8");
  const [editStart, setEditStart] = useState("");
  const [editEnd, setEditEnd] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  // New Direction Creation Form State (Below the list)
  const [isCreating, setIsCreating] = useState(false);
  const todayStr = new Date().toISOString().slice(0, 10);
  const defaultEndStr = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const [newTitle, setNewTitle] = useState("");
  const [newNotes, setNewNotes] = useState("");
  const [newColor, setNewColor] = useState("#38bdf8");
  const [newStart, setNewStart] = useState(todayStr);
  const [newEnd, setNewEnd] = useState(defaultEndStr);

  // Palette from config if available
  const themeColors = (yoncConfig?.themes || []).map((t) => t.color).filter(Boolean);
  const availableColors = Array.from(new Set([...PRESET_COLORS, ...themeColors]));

  const startEdit = (dir: Direction) => {
    setEditingId(dir.id);
    setEditTitle(dir.title);
    setEditNotes(dir.notes);
    setEditColor(dir.color);
    setEditStart(dir.start_date);
    setEditEnd(dir.end_date);
  };

  const handleSaveEdit = async (id: string) => {
    if (!editTitle.trim()) return;
    setIsSaving(true);
    try {
      const res = await api.updateDirection(id, {
        title: editTitle.trim(),
        notes: editNotes,
        color: editColor,
        start_date: editStart,
        end_date: editEnd,
      });
      if (res.operation_batch) {
        onRegisterUndo({ kind: "batch", batchId: res.operation_batch.id });
      }
      setEditingId(null);
      await onRefresh();
    } catch (err) {
      onError(err);
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (dir: Direction) => {
    if (!window.confirm(`确定删除阶段方向「${dir.title}」吗？`)) return;
    try {
      const res = await api.deleteDirection(dir.id);
      if (res.operation_batch) {
        onRegisterUndo({ kind: "batch", batchId: res.operation_batch.id });
      }
      await onRefresh();
    } catch (err) {
      onError(err);
    }
  };

  const handleCreateNew = async () => {
    if (!newTitle.trim()) {
      onError(new Error("请输入方向名称"));
      return;
    }
    if (!newStart || !newEnd || newStart > newEnd) {
      onError(new Error("请选择有效的开始和结束日期"));
      return;
    }
    setIsSaving(true);
    try {
      const res = await api.createDirection({
        title: newTitle.trim(),
        notes: newNotes,
        color: newColor,
        start_date: newStart,
        end_date: newEnd,
      });
      if (res.operation_batch) {
        onRegisterUndo({ kind: "batch", batchId: res.operation_batch.id });
      }
      setIsCreating(false);
      setNewTitle("");
      setNewNotes("");
      await onRefresh();
    } catch (err) {
      onError(err);
    } finally {
      setIsSaving(false);
    }
  };

  // Group directions by Year-Month of start_date
  const grouped = directions.reduce<Record<string, Direction[]>>((acc, dir) => {
    const monthKey = dir.start_date.slice(0, 7); // "YYYY-MM"
    if (!acc[monthKey]) acc[monthKey] = [];
    acc[monthKey].push(dir);
    return acc;
  }, {});

  const monthKeys = Object.keys(grouped).sort();

  return (
    <div className="direction-list-view">
      <header className="direction-list-header">
        <div className="direction-list-title-wrap">
          <h2>方向总览 · Direction List</h2>
          <span className="direction-list-count">
            共 {directions.length} 个阶段方向（按时间排期顺序）
          </span>
        </div>
        <p className="direction-list-desc">
          宏观意图与阶段主题。在此总览所有已设定的 Direction，随时在日历上高亮定位，或在末尾追加新方向。
        </p>
      </header>

      <div className="direction-list-content">
        {monthKeys.length === 0 && !isCreating && (
          <div className="direction-empty-state">
            <p>暂无阶段方向标注。在下方点击「+ 新建 Direction」或在日历中按住 Shift 框选日期即可创建。</p>
          </div>
        )}

        {monthKeys.map((monthKey) => {
          const dirs = grouped[monthKey];
          const [year, month] = monthKey.split("-");
          return (
            <section key={monthKey} className="direction-month-section">
              <div className="direction-month-heading">
                <h3>{`${year} 年 ${parseInt(month, 10)} 月`}</h3>
                <span className="month-badge">{dirs.length} 个方向</span>
              </div>

              <div className="direction-cards-grid">
                {dirs.map((dir) => {
                  const isEditing = editingId === dir.id;
                  if (isEditing) {
                    return (
                      <article key={dir.id} className="direction-card editing" style={{ borderLeftColor: editColor }}>
                        <div className="direction-card-edit-form">
                          <input
                            type="text"
                            className="direction-edit-title"
                            value={editTitle}
                            onChange={(e) => setEditTitle(e.target.value)}
                            placeholder="方向名称…"
                            autoFocus
                          />
                          <div className="direction-date-row">
                            <label>
                              开始:
                              <input type="date" value={editStart} onChange={(e) => setEditStart(e.target.value)} />
                            </label>
                            <label>
                              结束:
                              <input type="date" value={editEnd} onChange={(e) => setEditEnd(e.target.value)} />
                            </label>
                          </div>
                          <div className="direction-color-picker-row">
                            <span className="color-label">颜色:</span>
                            <div className="color-swatches">
                              {availableColors.map((col) => (
                                <button
                                  key={col}
                                  type="button"
                                  className={`color-swatch-btn ${editColor === col ? "active" : ""}`}
                                  style={{ backgroundColor: col }}
                                  onClick={() => setEditColor(col)}
                                />
                              ))}
                              <input
                                type="color"
                                value={editColor}
                                onChange={(e) => setEditColor(e.target.value)}
                                title="自定义颜色"
                                className="custom-color-input"
                              />
                            </div>
                          </div>
                          <textarea
                            className="direction-edit-notes"
                            value={editNotes}
                            onChange={(e) => setEditNotes(e.target.value)}
                            rows={4}
                            placeholder="思考笔记 (Bullet points, 每行一个要点)…"
                          />
                          <div className="direction-edit-actions">
                            <button
                              type="button"
                              className="btn-sm primary"
                              disabled={isSaving}
                              onClick={() => handleSaveEdit(dir.id)}
                            >
                              保存
                            </button>
                            <button
                              type="button"
                              className="btn-sm"
                              onClick={() => setEditingId(null)}
                            >
                              取消
                            </button>
                          </div>
                        </div>
                      </article>
                    );
                  }

                  return (
                    <article key={dir.id} className="direction-card" style={{ borderLeftColor: dir.color }}>
                      <div className="direction-card-main">
                        <div className="direction-card-header">
                          <div className="direction-card-title-row">
                            <span className="direction-color-dot" style={{ backgroundColor: dir.color }} />
                            <h4 className="direction-title">{dir.title}</h4>
                          </div>
                          <div className="direction-card-actions">
                            <button
                              type="button"
                              className="btn-locate-grid"
                              onClick={() => onLocateInGrid(dir)}
                              title="在日历中定位"
                            >
                              <span>◫ 在日历中定位</span>
                            </button>
                            <button
                              type="button"
                              className="btn-icon"
                              onClick={() => startEdit(dir)}
                              title="编辑"
                            >
                              ✎
                            </button>
                            <button
                              type="button"
                              className="btn-icon danger"
                              onClick={() => handleDelete(dir)}
                              title="删除"
                            >
                              ×
                            </button>
                          </div>
                        </div>

                        <div className="direction-card-span-badge" style={{ color: dir.color, borderColor: `${dir.color}40`, backgroundColor: `${dir.color}15` }}>
                          📅 {formatDateSpan(dir.start_date, dir.end_date)}
                        </div>

                        {dir.notes ? (
                          <div className="direction-notes-body">
                            {dir.notes.split("\n").map((line, idx) => (
                              <p key={idx} className="direction-note-line">
                                {line}
                              </p>
                            ))}
                          </div>
                        ) : (
                          <p className="direction-notes-empty">无附加思考笔记</p>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          );
        })}

        {/* New Direction creation block at the END of the list */}
        <footer className="direction-list-footer">
          {!isCreating ? (
            <button
              type="button"
              className="btn-add-direction-bottom"
              onClick={() => setIsCreating(true)}
            >
              <span className="plus-icon">+</span>
              <b>新建 Direction</b>
              <small>（在时间轴末尾设立新阶段方向）</small>
            </button>
          ) : (
            <div className="new-direction-form-card" style={{ borderLeftColor: newColor }}>
              <div className="new-direction-form-header">
                <h4>新建阶段方向 (New Direction)</h4>
                <button
                  type="button"
                  className="inspector-close"
                  onClick={() => setIsCreating(false)}
                >
                  ×
                </button>
              </div>
              <div className="new-direction-form-body">
                <input
                  type="text"
                  className="direction-edit-title"
                  placeholder="方向主题（例如：论文攻坚、Q4 基础设施升级）…"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  autoFocus
                />
                <div className="direction-date-row">
                  <label>
                    开始日期:
                    <input
                      type="date"
                      value={newStart}
                      onChange={(e) => setNewStart(e.target.value)}
                    />
                  </label>
                  <label>
                    结束日期:
                    <input
                      type="date"
                      value={newEnd}
                      onChange={(e) => setNewEnd(e.target.value)}
                    />
                  </label>
                </div>
                <div className="direction-color-picker-row">
                  <span className="color-label">主题颜色:</span>
                  <div className="color-swatches">
                    {availableColors.map((col) => (
                      <button
                        key={col}
                        type="button"
                        className={`color-swatch-btn ${newColor === col ? "active" : ""}`}
                        style={{ backgroundColor: col }}
                        onClick={() => setNewColor(col)}
                      />
                    ))}
                    <input
                      type="color"
                      value={newColor}
                      onChange={(e) => setNewColor(e.target.value)}
                      title="自定义颜色"
                      className="custom-color-input"
                    />
                  </div>
                </div>
                <textarea
                  className="direction-edit-notes"
                  placeholder="思考笔记 (Bullet points，例如：\n- 交付前置原型\n- 验证核心拓扑结构)…"
                  rows={4}
                  value={newNotes}
                  onChange={(e) => setNewNotes(e.target.value)}
                />
                <div className="direction-edit-actions">
                  <button
                    type="button"
                    className="btn-sm primary"
                    disabled={isSaving}
                    onClick={handleCreateNew}
                  >
                    创建方向
                  </button>
                  <button
                    type="button"
                    className="btn-sm"
                    onClick={() => setIsCreating(false)}
                  >
                    取消
                  </button>
                </div>
              </div>
            </div>
          )}
        </footer>
      </div>
    </div>
  );
}
