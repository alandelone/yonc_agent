# Yonc Graph Project System
## Product + UX + Graph Architecture Specification
**Status:** Concept specification v0.1  
**Primary goal:** Define how the Graph Project System works, how Canvas and Timeline should look and behave, and how other agents/tools interact with it.

---

# 1. Product Definition

Yonc Graph Project System is **not a traditional task list** and is **not an agent scheduler**.

It is a **human-controlled project truth system** built around a graph.

Its job is to externalize:

- What projects exist
- How a big goal is decomposed
- Which nodes belong to which parent/module/project
- Which work depends on other work
- Which nodes are done / cancelled / superseded
- When work is expected to happen
- What deadlines constrain the graph
- What artifact/resource/pathway was produced
- What the current project structure actually is

The same graph can be rendered through several views:

1. **Canvas View** — spatial/structural graph
2. **Timeline View** — temporal/project scheduling graph
3. **Mobile View** — compact execution-oriented view
4. Optional later views — Notion, table, list, reporting, etc.

The source of truth should therefore **not be Notion**.

Notion is only one possible UI / projection.

---

# 2. Product Principle

The system follows one key principle:

> **Show the whole system when the user wants to understand. Hide complexity when the user wants to act.**

Canvas exists for understanding.

Timeline exists for temporal reasoning.

Mobile exists for compact viewing and execution.

Graph Core holds the truth underneath all of them.

---

# 3. Core Scope

## 3.1 In Scope

The Graph Project System owns:

- Project graph structure
- Node hierarchy
- Parent / child relationships
- Dependencies
- Required / optional relationships
- Status
- Stage / lifecycle metadata
- Deadline
- Estimated effort
- Estimated finish
- Timeline position
- Temporal pressure
- Graph health warnings
- Split proposals
- User-approved split commits
- Artifact/resource references
- Persistent view state
- Undo/history of graph operations
- Graph read/write interface for other agents

## 3.2 Explicitly Out of Scope for now

The Graph Project System does **not** own:

- Agent work queues
- Human review queues
- Agent workforce scheduling
- Agent load balancing
- Autonomous agent orchestration
- Notification routing
- "Which agent should work next?"
- Complex permission/audit UI

Those concerns can be handled by another orchestration system.

The Graph Project System only needs to expose enough information so another agent/system can read the current project truth.

---

# 4. Graph Source of Truth

The canonical model is a graph-based store.

Conceptually:

```text
Graph
├── Nodes
├── Edges
├── Draft Proposals
├── Graph Operations / History
└── View State
```

Graph truth and UI state must remain separate.

---

# 5. Node Model

A node can represent a project-level unit or an actionable unit.

Example logical levels:

```text
L1 Goal / Programme
↓
L2 Deliverable / Module
↓
L3 Work Package
↓
L4 Action
```

An additional "Atomic Refinement" can exist inside an Action without necessarily becoming another visible graph node.

## 5.1 Node Fields

Recommended conceptual schema:

```json
{
  "id": "node_xxx",
  "title": "Define Graph Core",
  "node_type": "work_package",
  "wbs_level": 3,

  "project_id": "project_yonc",
  "parent_id": "node_parent",

  "stage": "planning",
  "status": "active",

  "time": {
    "deadline": null,
    "estimated_effort_minutes": 120,
    "estimated_finish": null,
    "temporal_pressure": 0.0
  },

  "tags": {
    "task_type": "Design",
    "mode": "Focus",
    "theme": "Yonc"
  },

  "resources": [],

  "required": true
}
```

This is conceptual, not a final implementation schema.

---

# 6. Edge Model

The graph becomes useful only when relationships are explicit.

Minimum useful edge types:

```text
contains
depends_on
blocks
related_to
```

Possible future types:

```text
produces
uses
validates
references
supersedes
```

Example:

```text
Thesis
  └──contains──> Methodology

Methodology
  └──contains──> Prototype

Prototype
  └──depends_on──> Design Spec
```

## 6.1 Required vs Optional Child

A `contains` edge should support:

```text
required = true
required = false
```

This is useful for progress calculation and project closure reasoning.

Optional work should not prevent a parent from being considered structurally complete.

---

# 7. Actionability Contract

WBS level alone must not determine whether decomposition is finished.

A node is considered actionable when the user and agent agree it satisfies the following:

### Startable
The user knows how to begin without another planning session.

### Observable Done
There is a clear observable result.

### Single Intent
The task is not secretly multiple jobs combined together.

### Low Decision Load
Execution does not hide a major planning decision.

### Bounded Effort
The work is small enough to move meaningfully in one or a few working sessions.

Time is a soft rule, not an absolute rule.

Example:

Bad:

```text
Research Graph Engineering
```

Better:

```text
Find 5 agent graph architecture examples and record
node / edge / runtime patterns in graph-notes.md
```

For uncertain work, use bounded exploration:

```text
Investigate crash for 45 minutes.

Output:
- reproduction steps
- 3 likely causes
- next experiment
```

The answer may be uncertain.  
The **next action must not be uncertain**.

---

# 8. Collaborative Split Session

Task decomposition must not be a black-box AI operation.

The correct workflow is:

```text
User selects node
↓
Start Split Session
↓
Agent reads node + graph context
↓
Agent proposes decomposition
↓
User responds
↓
Agent revises
↓
User and agent reach agreement
↓
User commits
↓
Graph nodes + edges are created
```

## 8.1 Canvas Entry

The split control is deliberately hidden most of the time.

Desktop behavior:

1. User moves pointer near the right edge / right corner of a node.
2. After a short intentional hover (~0.8–1.0 s), a `+` appears.
3. Clicking `+` opens a compact Split Session interface.

Important:

> `+` means **Split / Extend Graph**, not "instantly create a random todo".

## 8.2 Split Session UI

Suggested layout:

```text
┌─────────────────────────────────────────┐
│ Split: Design Project Manager           │
├─────────────────────────────────────────┤
│ AI                                      │
│ I suggest splitting this into...        │
│                                         │
│ User                                    │
│ Canvas and Timeline should be separate. │
│                                         │
│ AI                                      │
│ Updated proposal...                     │
│                                         │
├─────────────────────────────────────────┤
│ Current proposal                        │
│ ├─ Canvas View                          │
│ ├─ Timeline View                        │
│ ├─ Graph Core                           │
│ └─ Agent Interface                      │
│                                         │
│ [Continue] [Revise] [Commit Split]      │
└─────────────────────────────────────────┘
```

### Buttons

**Continue**
- Continue discussing the current proposal.

**Revise**
- Explicitly ask the agent to regenerate/restructure the proposal.

**Commit Split**
- Convert the current proposal into real graph nodes and edges.
- The proposal becomes reality only here.

**Cancel / Close**
- Close the Split Session without modifying the committed graph.

---

# 9. Proposal vs Reality

Draft AI proposals must be visually and structurally separated from the committed graph.

Concept:

```text
Committed Graph
≠
Draft Proposal Graph
```

Proposal nodes may use:

- Lower opacity
- Partial border
- Dashed edge
- "Draft" treatment

Only after `Commit Split` do they become ordinary committed nodes.

This prevents the user from confusing AI suggestions with actual project truth.

---

# 10. Graph Operations

The UI should not directly mutate raw JSON.

Changes should conceptually happen through graph operations:

```text
CREATE_NODE
UPDATE_NODE
DELETE_NODE
CREATE_EDGE
DELETE_EDGE
MOVE_TIME
SET_DEADLINE
MARK_DONE
CANCEL
SUPERSEDE
COMMIT_SPLIT
```

This enables:

- Undo
- Redo later
- History
- Reliable derived-state recalculation

---

# 11. Completion Rules

## 11.1 DONE

The rule is simple:

> **A node is DONE only when the user says it is done.**

Children completion does not automatically mark a parent as DONE.

Example:

```text
Methodology
Status: DOING

Children: 4 / 4 DONE
```

The parent remains open until the user explicitly marks it done.

## 11.2 Progress ≠ Status

Progress is calculated information.

Status is user-controlled truth.

Possible:

```text
Status: DONE
Calculated progress: 87%
```

This is allowed because the user may decide remaining planned actions are no longer necessary.

## 11.3 CANCELLED

Requires a reason.

```text
status = CANCELLED
reason = "No longer required after architecture change"
```

## 11.4 SUPERSEDED

Requires a reason.

Optional replacement reference:

```text
status = SUPERSEDED
reason = "Replaced by v2 architecture"
superseded_by = node_v2
```

The UI must show the reason.

---

# 12. Effort Estimation

Every Action should have an `estimated_effort`.

Estimate priority:

```text
A. User provides estimate
B. AI proposes estimate
C. If missing → use Task Type default
```

**Accepted default behavior:**

> If there is no estimate, use the default value for that Task Type.

Example defaults:

```text
Read       → 30 min
Search     → 45 min
Write      → 90 min
Design     → 120 min
Build      → 120 min
Discussion → 30 min
```

These values are configurable.

---

# 13. No Mandatory Actual-Effort Q&A

The system should **not** interrupt the user after every task with:

> "How long did this take?"

No mandatory timer.
No required effort survey.

This would add friction and is likely to be abandoned.

---

# 14. Observed Delivery Pace

Instead of measuring perfect "actual effort", the system observes what the user actually closes over time.

Every completed Action already has an estimated effort.

Example:

```text
A = 1h  DONE
B = 2h  DONE
C = 3h  DONE
```

If these were completed across 14 calendar days:

```text
6h-equivalent / 14 days
≈ 3h-equivalent / week
```

This is called:

> **Observed Delivery Pace**

It does **not** claim the user literally worked for that exact number of hours.

It means:

> Based on estimated task size, this is approximately how much planned workload the user actually finishes over calendar time.

First version:

```text
Look at last 4–8 weeks
↓
Sum estimated effort of nodes marked DONE
↓
Calculate typical completed workload per week
```

Prefer a robust typical value such as median/rolling behavior rather than assuming perfectly stable weekly productivity.

---

# 15. Elastic Timeline Philosophy

The Timeline must not assume the user follows a rigid daily plan.

This is especially important for an ADHD-oriented system.

The Timeline is:

> **Forecast + Capacity Map**

not:

> **Discipline Calendar**

Dragging a module into a date region means:

> "I roughly intend this work to live around here."

It does not mean:

> "I must execute exactly this task on exactly this day."

If reality changes, the forecast moves.

The system adapts to the user's real delivery pace instead of treating deviation as failure.

---

# 16. Estimated Finish

The system should distinguish:

```text
Estimated Effort
Estimated Calendar Span
Estimated Finish
Deadline
```

Example:

```text
Estimated effort: 20h-equivalent
Observed delivery pace: 4h-equivalent/week

Typical calendar span ≈ 5 weeks
```

Because delivery pace varies, prefer a range:

```text
Estimated span:
~4–7 weeks
```

Then:

```text
Estimated Finish: 12 Oct
Deadline: 30 Sep

⚠ Forecast exceeds deadline by 12 days
```

The forecast should be recalculated whenever important graph facts change.

---

# 17. Derived-State Recalculation

Whenever a graph-changing event happens, derived values should update.

Example:

```text
Module A
├─ Action 1 = 2h
├─ Action 2 = 3h
└─ Action 3 = 5h

Total = 10h
```

A new Action is committed:

```text
Action 4 = 4h
```

System recalculates:

```text
Module effort: 10h → 14h
Estimated span → recalculated
Estimated finish → recalculated
Temporal pressure → recalculated
Warnings → recalculated
Canvas glow → recalculated
Timeline rendering → recalculated
```

---

# 18. Temporal Pressure

Glow is not a generic "attention score".

It is primarily a visual projection of **Timeline Urgency / Temporal Pressure**.

Concept:

```text
NOW ───────────────────────── DEADLINE
                          ↑
                 pressure increases
```

Later it may consider:

- Time remaining
- Estimated remaining effort
- Dependency state
- Parent deadline
- Forecasted finish
- Whether the node is overdue

Do not define urgency as only `days_to_deadline`.

Prefer a field such as:

```text
temporal_pressure = 0.0 ... 1.0
```

---

# 19. Visual Encoding Rules

Every visual variable should have exactly one main meaning.

```text
Project hue
= Which project / lineage?

Color lightness
= WBS / decomposition depth

Border style
= Stage / lifecycle

Glow intensity
= Temporal pressure

⚠ icon
= Graph health problem

Expand / collapse
= View state

Canvas X position
= Time / temporal intent
```

This prevents visual ambiguity.

---

# 20. Canvas View

## 20.1 Purpose

Canvas answers:

> What is the project structure?
> How are things connected?
> What depends on what?
> How far has this project been decomposed?
> Where are its artifacts?
> Where is it in time?

Canvas is primarily a desktop/tablet view.

It should visually resemble a clean workflow dashboard rather than a loose whiteboard.

---

# 21. Canvas Layout

Suggested high-level layout:

```text
┌──────────────────────────────────────────────────────────────┐
│ Project / Scope     Search     Filter        Zoom / Settings │
├──────────┬───────────────────────────────────────────────────┤
│          │                                                   │
│ Sidebar  │                 GRAPH CANVAS                      │
│          │                                                   │
│          │   [Project]                                       │
│          │       │                                           │
│          │   ┌───┴────────┐                                  │
│          │   │            │                                  │
│          │ [Module]    [Module]                              │
│          │   │                                               │
│          │ [Action]                                          │
│          │                                                   │
│          │                                       Mini-map    │
└──────────┴───────────────────────────────────────────────────┘
```

Canvas is not fully freeform.

It is a **time-constrained graph canvas**.

---

# 22. Canvas Background

Canvas uses a dark or neutral low-noise background.

Time reference lines should be visible but subtle.

Default wide view:

```text
Q1        Q2        Q3        Q4
│         │         │         │
│         │         │         │
```

Zooming in may reveal:

```text
Month → Week → Day
```

The background should never feel like an Excel grid.

Reference lines are light, thin, and low contrast.

---

# 23. Canvas Edge Routing

Edges must use orthogonal routing.

Allowed:

```text
─────┐
     │
     └────
```

Avoid:

- Diagonal edges
- Messy curves
- Large arbitrary bezier paths

Rounded 90° corners are acceptable as a visual treatment.

The logical path is always horizontal/vertical.

---

# 24. Canvas Node Anatomy

Suggested node:

```text
╭──────────────────────────────╮
│ Stage label             ⚠    │
│                              │
│ Methodology                  │
│ 72%                          │
│                              │
│ Sep 30        3 resources    │
╰──────────────────────────────╯
```

Only essential information belongs on the collapsed card.

Recommended visible fields:

- Title
- Small stage/status treatment
- Progress if meaningful
- Deadline if present
- Small resource count/icon
- Warning icon if present

Detailed information belongs in an Inspector / Detail Panel.

---

# 25. Canvas Project Color System

Each project has a base hue.

Example:

```text
Thesis = red family
Yonc   = blue family
AGV    = green family
```

Within the same project:

```text
L1 = deepest / strongest
L2 = lighter
L3 = lighter again
L4 = lightest
```

So the brain can understand:

- Hue → project identity
- Lightness → decomposition depth

without reading every label.

---

# 26. Border / Stage Visual System

Stage is expressed mainly through the node border/body treatment.

Exact lifecycle names may still evolve, but visual grammar can be defined now.

Example:

### Planning
- Overall node is dimmer
- Border illumination partial/incomplete
- No strong glow

### Proposed / Draft
- Partial border
- Lower opacity
- Clearly different from committed reality

### Ready / Active Structure
- Complete border
- Normal contrast

### Blocked
- Broken/dashed/disrupted border treatment
- Warning details accessible separately

### Done
- Lower contrast
- Minimal glow
- Quiet visual state

Important:

> Border describes lifecycle/state. Glow describes time pressure.

Do not use glow to mean everything.

---

# 27. Glow / Temporal Pressure

The glow belongs to the **whole block perimeter**, not a small dot.

Concept:

```text
low pressure
╭──────────────╮
│     Task     │
╰──────────────╯
```

Higher pressure:

```text
    ✦       ✦
 ╭════════════╮
✦│    Task    │✦
 ╰════════════╯
    ✦       ✦
```

Very high pressure may be visually intense.

However motion must be limited.

---

# 28. Attention / Motion Budget

Truth must not be hidden.

If 10 nodes are urgent, all 10 may still visually show high temporal pressure.

But motion/animation should be constrained.

Example:

```text
Highest-pressure node:
- stronger pulse allowed

Next 2–3 urgent nodes:
- subtle breathing

Other urgent nodes:
- bright but static
```

Rule:

> **Data truth is unlimited; motion attention is budgeted.**

Glow must communicate information, not decoration.

---

# 29. Canvas Toggle / Expand-Collapse

The correct term is **toggle / expand-collapse**.

A node can hide/show its descendants.

Collapsed:

```text
▶ Methodology
```

Expanded:

```text
▼ Methodology
   ├─ Design
   ├─ Simulation
   └─ Validation
```

The expand state must persist.

If the user leaves and returns:

- previously expanded nodes remain expanded
- previously collapsed nodes remain collapsed

This is a key anti-overwhelm mechanism.

---

# 30. View State vs Graph State

Expand/collapse is not graph truth.

Store separately:

```json
{
  "canvas": {
    "node_A": {"expanded": true},
    "node_B": {"expanded": false}
  },
  "timeline": {
    "node_A": {"expanded": false}
  }
}
```

Canvas and Timeline should be allowed to remember different expansion states.

---

# 31. Canvas Hover / Hidden Controls

The Canvas should remain visually clean.

Desktop pointer behavior:

### Node right edge / corner
After short intentional hover:

```text
+
```

appears.

Purpose:

- Start Split Session
- Extend the node graph

It should not be permanently visible.

### Node selection
Single click/tap selects the node and opens or updates the Inspector.

### Double click
Possible later behavior:
- Toggle expand/collapse
or
- Focus node as current scope

Do not overload double-click in the first version unless needed.

---

# 32. Canvas Global Buttons

Recommended top/side controls:

### Project / Scope Selector
Choose what part of the graph is the current root.

### Search
Find node by title/tag.

### Filter
Filter by:
- Project
- WBS level
- Stage
- Status
- Tag
- Deadline window

### Zoom +
Zoom in.

### Zoom -
Zoom out.

### Fit
Fit current visible graph to viewport.

### Auto Layout
Recalculate clean orthogonal positions.

### Undo
Undo latest graph operation.

### Redo
Optional later.

### Canvas / Timeline / Mobile Preview switch
Switch projections without changing graph truth.

---

# 33. Node Context Buttons

When a node is selected, recommended actions:

### Toggle
Expand/collapse children.

### Split
Open Collaborative Split Session.

### Add Link
Add dependency / related-to connection.

### Deadline
Set or edit deadline.

### Resources
View/add artifact reference.

### Status
Mark:
- Doing/Active if used
- Done
- Cancelled
- Superseded

### More
Secondary actions:
- Set current project scope
- Move/reparent
- Duplicate if ever needed
- View history

---

# 34. Deadline Locking Rules in Canvas

A node with an explicit deadline is a temporal anchor.

Rule:

> A deadline-anchored node should not casually move horizontally on the Canvas.

To change its deadline:
- open node detail
- explicitly edit deadline

A child without its own fixed deadline may move, but:

```text
child planned position <= nearest ancestor deadline
```

If the child is dragged beyond the parent deadline:

- block the drop
or
- show a clear warning/forbidden region

The first version should prefer a constrained drop.

---

# 35. Dependency Drag Constraints

If:

```text
B depends_on A
```

then temporal positioning should not imply B completes before A when the dependency requires the opposite.

During drag:
- invalid temporal region may be shaded
- warning shown before commit

Do not silently produce impossible graph/time states.

---

# 36. Graph Health

Graph Health runs in the background.

Possible checks:

- Deadline conflict
- Child beyond parent deadline
- Dependency ordering conflict
- Circular dependency
- Orphan node
- Large unsplit node
- Missing output definition
- Blocked too long
- Missing required relationship

UI:

```text
╭──────────────────────── ! ╮
│ Methodology               │
╰───────────────────────────╯
```

Click warning:

```text
⚠ Deadline conflict

2 child actions exceed
parent deadline.

[Show affected nodes]
```

Graph Health should warn.

It should not make project decisions for the user.

---

# 37. Resource / Artifact Model

Artifacts do not always need to become graph nodes.

Default model:

> **Artifact Reference / Resource Pathway**

Examples:

```text
local://D:/project/design.md
github://repo/pull/47
notion://page/...
drive://...
https://...
conversation://...
```

A task can store:

```text
resources[]
```

Example:

```text
Define Architecture
  └── output/reference
      → github://docs/architecture.md
```

If an artifact becomes structurally important later, it may be promoted into a real Artifact Node.

So:

```text
Simple output → reference
Important connected output → graph node
```

---

# 38. Inspector / Detail Panel

Selecting a node opens a detail view.

Recommended sections:

```text
Title
Stage / Status
Project / WBS Level
Description
Deadline
Estimated effort
Estimated finish
Temporal pressure
Progress
Dependencies
Children
Resources
Warnings
History
```

Recommended buttons:

```text
[Toggle]
[Split]
[Set Deadline]
[Add Dependency]
[Add Resource]
[Mark Done]
[More]
```

If cancelled:

```text
Reason: ...
```

If superseded:

```text
Reason: ...
Replacement: ...
[Open replacement]
```

---

# 39. Current Project Scope

"Project" is not necessarily one fixed node type.

A large L1 may be too large to operate as a practical project.

A user can choose an L2/L3 node as the current project scope.

Example:

```text
PhD Thesis
├─ Literature Review
├─ Methodology
├─ Prototype
└─ Validation
```

In a portfolio view, `Methodology` may behave as a project.

Selecting:

```text
Set as Current Project Scope
```

allows Canvas/Timeline to treat that node as the working root.

This provides scale flexibility.

---

# 40. Timeline View

Timeline answers:

> How much work is this?
> Where does it roughly live in time?
> Which projects overlap?
> What is likely to miss its deadline?
> How long is this module likely to take in real life?

Timeline is not just a Gantt chart.

It is a **temporal projection of the same Graph Core**.

---

# 41. Timeline Modes

Recommended two sub-modes:

## A. Estimate Mode

Best for L1/L2/L3 comparison.

Looks more like a restrained Gantt/timeline:

```text
              AUG        SEP        OCT        NOV

Literature    ━━━━━━━━━━━━━●
Methodology             ━━━━━━━━━━━━━━━━━●
Prototype                       ━━━━━━━━━━━━━━━●
```

Focus:
- estimated span
- project/module length
- deadline
- overlap
- dependency
- forecast

## B. Block Grid Mode

Best for visual capacity/planning.

Each day is represented as a square cell.

Concept:

```text
Mon Tue Wed Thu Fri Sat Sun
□   □   □   □   □   □   □
□   □   □   □   □   □   □
□   □   □   □   □   □   □
```

The user drags a project/module/work package into the calendar region.

This creates a visual scheduling intention.

---

# 42. Timeline Block Grid Layout

Recommended desktop layout:

```text
┌────────────────────────────────────────────────────────────┐
│ Timeline   [Estimate] [Block Grid]   Month   Filters       │
├────────────────────┬───────────────────────────────────────┤
│ Module / Card Pool │ Time Grid                             │
│                    │                                       │
│ Literature Review  │ [□][□][□][□][□][□][□]                │
│ Methodology        │ [□][□][□][□][□][□][□]                │
│ Prototype          │ [□][□][□][□][□][□][□]                │
│ Yonc Canvas        │ [□][□][□][□][□][□][□]                │
└────────────────────┴───────────────────────────────────────┘
```

---

# 43. Timeline Left Card Pool

The left panel contains schedulable units.

Recommended default:

- WBS L2 modules
- WBS L3 work packages

Avoid showing every Atomic Action by default.

A card may show:

```text
Methodology
Est. effort: 12h
Forecast span: 4–7 days
Deadline: 30 Sep
Tags: Design / Focus
```

Button/interaction:

- Drag to timeline
- Click to inspect
- Toggle descendants
- Filter

---

# 44. Timeline Drag Behavior

Dragging a module into the grid means:

> "I roughly intend this work to occupy this region."

It is not a rigid calendar promise.

The system uses the dropped position as temporal intent.

The displayed span may be informed by:

- estimated effort
- observed delivery pace
- dependencies
- deadline constraints

---

# 45. Timeline Resize Behavior

A scheduled block can be stretched/shortened visually.

This changes the intended calendar span.

Important:

- It does not necessarily rewrite estimated effort.
- Effort and span are different concepts.

Example:

```text
Estimated effort = 8h
Calendar span = 3 days
```

The user may stretch it to 6 days because real life is fragmented.

That is valid.

---

# 46. Timeline Overlap Visualization

Projects may overlap.

If two project/module colors occupy the same day cell, the cell may split.

Example concept:

```text
┌─────┐
│ A|B │
└─────┘
```

or a top/bottom split.

Recommendation:

Use a consistent split system.

First version:
- 2 overlaps → 50/50 split
- >2 overlaps → compact segmented treatment or stacked indicator

Do not create noisy gradients.

The center/label region should still make the project/module identity understandable.

---

# 47. Timeline Deadline Anchor

A fixed deadline is visually explicit.

Example:

```text
────────────────────────◆
                       30 Sep
```

Deadline is an anchor.

Changing deadline should require an explicit edit, not accidental dragging.

---

# 48. Timeline Warning

If:

```text
Estimated Finish > Deadline
```

show:

```text
⚠ Forecast exceeds deadline
```

The warning should show the amount:

```text
Estimated Finish: 12 Oct
Deadline: 30 Sep

12 days beyond deadline
```

This is a forecast warning, not a judgment.

---

# 49. Timeline Capacity / Density

Optional but recommended:

A compact capacity strip can visualize scheduled load.

Example:

```text
Sep 01  ▓▓
Sep 02  ▓▓▓▓
Sep 03  ▓▓▓▓▓▓
Sep 04  ▓
```

This is especially useful for showing:

> "This region is overloaded."

It should be interpreted as planning density, not moral performance.

---

# 50. Timeline Buttons

Recommended toolbar:

### Estimate / Block Grid
Switch timeline sub-mode.

### Today
Jump to current date.

### Previous / Next
Move temporal window.

### Day / Week / Month / Quarter
Change temporal scale.

### Filter
Filter by:
- project
- scope
- WBS
- tag
- stage
- deadline

### Unscheduled
Show modules not yet placed on timeline.

### Fit Project
Fit selected project from now to deadline.

### Forecast
Show/update estimated finish and temporal pressure.

### Toggle
Expand/collapse module descendants.

---

# 51. Timeline Node/Card Actions

Selecting a scheduled block:

```text
[Open]
[Toggle]
[Set Deadline]
[Resize Span]
[Remove from Timeline]
[View in Canvas]
[Resources]
```

`Remove from Timeline` should remove temporal placement only.

It must not delete the graph node.

---

# 52. Canvas ↔ Timeline Relationship

Both are projections of the same graph.

Canvas emphasizes:

```text
structure
hierarchy
relationships
dependencies
stage
resources
```

Timeline emphasizes:

```text
time
span
deadline
overlap
forecast
pressure
```

A node selected in one view should be easy to locate in the other.

Buttons:

```text
View in Canvas
View in Timeline
```

---

# 53. Mobile View

Mobile should not try to reproduce the full drag-heavy Canvas.

Primary goals:

- See current important project/module
- See nearby deadline
- See key actions
- Mark done
- Open resource
- Open Split Session when needed
- Read warnings

Possible structure:

```text
Current Project

Methodology
Deadline: 30 Sep
Forecast: 24 Sep

Next visible actions:
○ Define variables
○ Draft model
○ Review simulation

[Open details]
```

No complex graph dragging is required.

---

# 54. Portfolio / Module View

Optional but strongly useful.

Purpose:

> What projects/modules currently exist at the scale I care about?

Example:

```text
┌──────────────────────┐
│ Literature Review    │
│ Stage: Execution     │
│ Deadline: 20 Sep     │
│ Forecast: 15 Sep     │
└──────────────────────┘

┌──────────────────────┐
│ Methodology          │
│ Stage: Planning      │
│ Deadline: 31 Oct     │
└──────────────────────┘
```

This view can promote WBS L2/L3 units into "project cards" without changing their actual graph type.

---

# 55. Inbox / Capture Layer

The user should not need to classify every new thought immediately.

A lightweight Inbox accepts:

```text
"Need to test another solar forecast method"
```

Later:

```text
Inbox Item
↓
User + Agent discussion
↓
Attach to project
↓
Convert to node
```

This reduces capture friction.

---

# 56. External Agent / MCP / Function Interface

Split capability and graph manipulation must not be tied to Canvas.

Other agents should be able to use the same project system.

Conceptual tool interface:

```text
project.list
project.get_graph
project.get_node
project.get_children
project.get_dependencies
project.get_resources

split.start
split.get_context
split.propose
split.revise
split.get_current_proposal
split.commit

node.mark_done
node.cancel
node.supersede
node.set_deadline
node.add_resource
```

The exact API can later be MCP, function calling, local service, or another protocol.

The key architecture rule:

> UI and agent interfaces call the same Graph Core.

---

# 57. Other Agent Scenario

An external agent may ask:

```text
What projects is the user currently working on?
What is the structure of Methodology?
Which nodes are not done?
What artifacts already exist?
What is the deadline?
```

The Project Graph answers those questions.

If the agent produces a useful result, it may add an artifact reference to the relevant node.

Example:

```text
Task: Define API architecture

Resource:
github://repo/docs/api-architecture.md
```

The project system records the result.

It does not need to manage the agent's own queue.

---

# 58. Suggested Overall Architecture

```text
                         USER
                          │
             ┌────────────┼────────────┐
             │            │            │
          Canvas       Timeline      Mobile
             │            │            │
             └────────────┼────────────┘
                          │
                    Graph Core API
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
   Graph Store      Split Sessions     History/Undo
        │                 │                 │
        └─────────────────┼─────────────────┘
                          │
                 Derived-State Engine
                          │
         ┌────────────────┼────────────────┐
         │                │                │
      Progress        Forecast      Graph Health
         │                │                │
         └────────────────┼────────────────┘
                          │
                    View Projectors
                          │
                    UI rendering

External Agents / MCP
          │
          └──────────────→ Graph Core API
```

---

# 59. Graph System Processing Flow

Typical flow:

```text
1. User creates/imports a project
2. Graph node exists
3. User opens Split Session
4. User + AI agree on decomposition
5. User commits split
6. Graph operations create children/edges
7. Estimated effort assigned
   - user
   - AI
   - Task Type default
8. Derived state recalculates
9. Canvas re-renders
10. Timeline forecast updates
11. User optionally places modules in timeline
12. User works in real life / other agents produce artifacts
13. Artifact references are attached
14. User says DONE
15. Observed Delivery Pace updates
16. Future forecast gradually becomes more realistic
```

---

# 60. Button Summary

## Canvas Global

```text
Project/Scope
Search
Filter
Zoom +
Zoom -
Fit
Auto Layout
Undo
View Switch
```

## Canvas Node

```text
Toggle
Split
Set Deadline
Add Dependency
Resources
Mark Done
Cancel
Supersede
More
```

Hidden hover control:

```text
+ = Split / Extend
```

## Split Session

```text
Continue
Revise
Commit Split
Cancel/Close
```

## Timeline Global

```text
Estimate
Block Grid
Today
Previous
Next
Day
Week
Month
Quarter
Filter
Unscheduled
Fit Project
Forecast
```

## Timeline Block

```text
Open
Toggle
Set Deadline
Resize Span
Remove from Timeline
View in Canvas
Resources
```

## Detail/Inspector

```text
Toggle
Split
Set Deadline
Add Dependency
Add Resource
Mark Done
Cancel
Supersede
View History
```

---

# 61. UX Rules That Must Not Be Violated

1. **DONE is controlled by the user.**
2. AI decomposition is proposal-first, never silent graph mutation.
3. No mandatory "How long did this take?" question.
4. Notion is a view, not the source of truth.
5. Expand/collapse state persists.
6. Canvas lines are orthogonal.
7. Deadline nodes do not casually move.
8. Children cannot silently violate deadline/dependency constraints.
9. Glow represents temporal pressure.
10. Glow is whole-block perimeter treatment.
11. Motion is limited even when many nodes are urgent.
12. Project hue and WBS lightness have separate meanings.
13. Graph Health warns; it does not decide.
14. Resources may remain references/pathways instead of graph nodes.
15. Timeline is an elastic forecast, not a rigid behavior schedule.
16. Agent orchestration/work queues are outside this system for now.

---

# 62. MVP Recommendation

A realistic first build should include only:

### Graph Core
- Nodes
- contains / depends_on edges
- DONE / CANCELLED / SUPERSEDED
- deadline
- estimated effort
- resource references
- graph operations
- persistent view state

### Split
- Sub-chat Split Session
- Proposal graph
- Commit Split

### Canvas
- Orthogonal graph
- Toggle
- Persistent expanded state
- Project colors
- WBS lightness
- Stage border
- temporal glow
- warning icon
- node inspector
- hidden hover `+`

### Timeline
- Estimate Mode
- Block Grid Mode
- Drag/drop modules
- Resize calendar span
- Deadline anchor
- overlap rendering
- forecast warning

### Estimation
- Task Type default effort
- DONE-based Observed Delivery Pace
- 4–8 week rolling history
- Estimated Finish
- Deadline gap warning

Do **not** add complex multi-agent scheduling to the first version.

---

# 63. One-Sentence Product Definition

> **Yonc Graph Project System is a human-controlled, graph-based project operating system that converts large goals into actionable structures through collaborative AI decomposition, visualizes structure through a persistent Canvas, visualizes real-life temporal pressure through an elastic Timeline, and exposes the same project truth to humans, UIs, and external agents.**
