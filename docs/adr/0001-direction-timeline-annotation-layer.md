# 0001: Direction as an Independent Timeline Annotation Layer

## Context & Decision
The Yonc Graph Project System requires a mechanism to capture high-level conceptual intents ("Directions") for time horizons (e.g. "Focus on Paper Writing this month") prior to formal task decomposition. 

We decided to model **Direction** as an **independent timeline annotation layer** rather than an additional `GraphNode` kind (e.g. `L0 Goal`) in the core project graph. 

## Rationale & Trade-offs
- **Graph Purity**: `GraphNode` represents committed, actionable project work units (L1–L4) bound by topological edges (`contains`, `depends_on`, `blocks`). Injecting floating, open-ended conceptual tags into the graph model would pollute graph validation, progress aggregation, and layout engines (ElkJS).
- **Presentation Flexibility**: Directions are decoupled temporal overlays rendered on the Capacity Grid (via multi-week segmented capsules and floating top notes) and queried chronologically in the Direction List View without requiring parent-child graph semantics.
- **Graduation Boundary**: When a Direction matures, it can be manually converted or AI-decomposed into formal L1/L2 graph nodes in the Module Pool rather than mutating in place.
