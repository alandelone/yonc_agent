# Domain Context: Yonc Graph Project System

## Concepts

### Direction / Phase Annotation (阶段方向标注)
A high-level temporal intent and conceptual boundary created by the user on the timeline. It represents an overarching theme or target for a specific time horizon (e.g., this week, this month, this year), such as "Deepening Research & Thesis Foundation". 

A Direction lives as an independent timeline annotation layer, not as a `GraphNode`. It does not participate in graph edges (`depends_on`, `blocks`), but serves as an upstream conceptual incubator that can later graduate into concrete `L1 Goal` projects manually or with AI assistance.

### Selection Range (选区范围)
A continuous calendar date span (`[start_date, end_date]`) on the Capacity Grid. 
- Triggered by `Shift + Drag` across date cells.
- Visually represented by per-week rounded capsule outlines in the Direction's color, connected across week column boundaries by subtle dashed bridge lines.

### Floating Direction Tag (悬浮方向便签)
A draggable note card anchored in the dedicated top Direction header strip above the Selection Range on the Capacity Grid.
- Automatically allocated to non-colliding vertical stacking lanes (Lane 1, Lane 2, etc.) while allowing free horizontal micro-adjustments within the date span.
- Connected to the encircled date cells via a dynamic pointer arrow.
- Contains: Title, Color Picker (preset theme swatches + custom hex), and Multi-line Bullet Points.
- Operations on Directions (create, move, edit, delete) are recorded in the system `OperationBatch` for full Undo/Redo (`Ctrl+Z` / `Ctrl+Y`) support.

### Direction List View (方向列表视图)
A dedicated, chronologically organized view (Month-by-month / Day-by-day) accessible as the 3rd mode in the Timeline toolbar (`[ Forecast ] [ Capacity Grid ] [ Direction List ]`).
- Displays all Directions in top-down sequential order.
- Always visible on the Capacity Grid (no toggle needed).
- Clicking any Direction card or its locate button smoothly transitions to Capacity Grid and centers the corresponding date cells.
- The `[+ New Direction]` creation trigger is positioned at the very bottom, below the last item of the list.

### Graduation & AI Setup (概念孵化与立项)
The lifecycle transition where a conceptual Direction is formalized into actual execution work.
- **Manual Graduation**: User manually translates the thoughts into L1 Goals / L2 Modules in the Module Pool or Canvas.
- **AI Recommendation**: In-situ pure-text decomposition advice displayed inside the floating tag card.

## Architecture Decision Records
- [ADR 0001: Direction as an Independent Timeline Annotation Layer](docs/adr/0001-direction-timeline-annotation-layer.md)

