# Case Editor Delete / Unlink (Frontend-only UX + State Semantics)

This doc describes **what an editor sees** in the case editor UI (`/cases/[id]`) around **Delete** and **Unlink**, and **what happens in frontend state** only.

- **In scope**: UI controls, confirmation modal copy, `graphState`/`displayData` changes, “orphaned” behavior.
- **Out of scope**: Saving to Postgres, submitting to Neo4j, backend APIs.

Note: the UI uses `(shared)` to mean `case_unique: false`. In backend KG deletion/cleanup, **shared/catalog relationships do not block deletion** of case-unique nodes; the backend only falls back to “detach-only” when it detects connections to **case-unique nodes outside the case**.

## Entry points: where Delete / Unlink appears

### Node “actions” menu (three-dot menu)

- **Where**: `src/components/cases/editor/NodeCard.tsx` renders `NodeActionMenu` when **not** in view mode.
- **How to access**: switch the page into **edit mode**, then open a node’s three-dot menu.
- **Menu items** (exact labels):
  - **Delete**: `Delete node`
  - **Unlink** (only when eligible): `Unlink from {parentLabel}`

**Which one you see**:
- If the node has **multiple incoming edges of the same relationship type** (i.e., it is effectively “reused” under multiple parents for that relationship), the menu shows **Unlink** for the current parent context.
- Otherwise the menu shows **Delete node**.

Implementation:
- Eligibility is computed in `src/app/cases/[id]/page.tsx` via `shouldShowUnlink(...)`, which checks whether the node has more than one incoming edge of the same label as the parent edge.

### Relationship delete (edge delete)

Separately from deleting nodes, the editor supports deleting a **relationship** (edge) via a confirmation modal (see “Delete relationship confirmation modal” below).

## Tooltips / disabled states (`min_per_case`)

Both node **Delete** and **Unlink** may be **disabled** by `min_per_case` constraints.

- **Where computed**: `src/components/cases/editor/NodeCard.tsx`
  - `getDeleteDisabledReason()` uses `getMinPerCaseWorseningAfterDeleteNode(...)`
  - `getUnlinkDisabledReason()` uses `getMinPerCaseWorseningAfterUnlinkEdge(...)`
- **What the user sees**: a disabled menu item with a tooltip showing the reason string:
  - `Case requires at least {min} {Label} node(s) (would have {countAfter}).`

Note: these guards are **connected-only** (reachable from Case root) and they only block actions that would make deficits **worse**.

## Delete Node confirmation modal (exact UI copy)

- **Component**: `src/components/cases/editor/modals/DeleteNodeConfirmation.tsx`
- **When it appears**: after starting a node delete flow (`uiActions.startDeleteNode(nodeId)`), the page computes a cascade plan and renders this modal.

### Header + body

- Title: `Delete Node?`
- Prompt: `Are you sure you want to delete {primaryNode.label}: {primaryNode.name}?`
- Connection count: `This will remove {N} connection(s).`

### Cascade sections

The modal may show two sections:

- **Cascade removal** (red):
  - Heading: `{N} item(s) will also be removed:`
  - Per-item display: `• [{label}] {name}`
  - If `case_unique === false`, item includes: `(shared)`
  - Footer note: `Items marked (shared) will be preserved in the knowledge graph.`

- **Detach-only / unlink** (blue):
  - Heading: `{N} item(s) will be unlinked (used elsewhere):`
  - Footer note: `These items have other connections in this case and will remain visible.`

### Footer + buttons

- Note: `The deletion will be persisted when you save the case.`
- If blocked by `min_per_case`:
  - `Cannot delete: {disabledReason}`
  - The **Delete Node** button is disabled and shows a tooltip with the disabled reason.
- Buttons:
  - `Cancel`
  - `Delete Node`

## Delete relationship confirmation modal (exact UI copy)

- **Component**: `src/components/cases/editor/modals/DeleteRelationshipConfirmation.tsx`
- **Copy**:
  - Title: `Delete relationship?`
  - Subtitle: `This action cannot be undone.`
  - If blocked: `Cannot delete: {disabledReason}`
  - Buttons: `Cancel`, `Delete`

## Frontend-only state behavior

The case editor maintains:
- `graphState`: canonical client-side graph (`nodes[]`, `edges[]`) with status markers.
- `displayData`: UI-friendly, backend-shaped nested structure that is updated locally so UI changes are immediate.

### Node / edge statuses in `graphState`

Defined in `src/hooks/cases/useGraphState.ts`:
- Nodes: `active | deleted | orphaned`
- Edges: `active | deleted`

Derived arrays:
- `nodesArray`: only **active** nodes (and excludes certain “selector” labels like `Domain`, `Forum`, `Jurisdiction`, `ReliefType`)
- `nodesArrayForModals`: includes **active + orphaned**, excludes deleted
- `edgesArray`: only **active** edges

### Unlinking a node from a parent (frontend-only)

Flow:
1. User chooses **Unlink from {parentLabel}** in the node action menu.
2. `src/app/cases/[id]/page.tsx` runs `handleUnlink(nodeId, parentId)` which:
   - Applies `min_per_case` guard (connected-only). If blocked, sets an error banner and does nothing else.
   - Calls `unlinkNode(nodeId, parentId, edgeLabel)` from `useGraphState`.
   - Sets `hasUnsavedChanges = true`.
   - Updates `displayData` by removing the child node from the parent’s arrays recursively (so the node disappears from that parent’s rendered subtree immediately).

State mutation in `graphState`:
- Only the matching edge is marked `status: 'deleted'`.
- The node stays `active` (it remains connected elsewhere).

### Deleting a node with cascade plan (frontend-only)

Flow:
1. User chooses **Delete node**.
2. The page computes a **cascade plan** based on UI hierarchy + graph connections:
   - `computeCascadePlan(...)` in `src/lib/cases/cascadeDelete.ts`
3. On confirm:
   - `deleteNodeWithCascade(cascadePlan)` updates `graphState` by applying `applyCascadePlan(...)`.
   - `hasUnsavedChanges = true`.
   - `displayData` is recursively pruned to remove the deleted node(s) so they disappear immediately.

Important implementation note:
- `applyCascadePlan(...)` marks the primary node as deleted, deletes relevant edges, and also marks `toDelete` **and** `toDetachOnly` nodes as `status: 'deleted'` in `graphState`.
- The UI intends `toDetachOnly` to mean “unlinked from this parent but still visible elsewhere” (and the modal copy says so). The “still visible elsewhere” behavior is achieved via `displayData` structure and/or other contexts, but the underlying `graphState` status marking is currently “deleted” for those nodes.

### Orphaned nodes (frontend-only)

The editor uses `orphaned` to represent nodes that are no longer connected to the active graph via any active parent chain.

- **Where computed**: `src/hooks/cases/useGraphState.ts`
  - `orphanedNodes` only includes nodes with status `orphaned` that have **no active parents** (based on active edges).
- **What the user sees**: `src/app/cases/[id]/page.tsx` renders `OrphanedNodesSection` with the list of `orphanedNodes`.

## Key files (quick reference)

- **Page orchestration**: `src/app/cases/[id]/page.tsx`
- **Node action UI**: `src/components/cases/editor/NodeCard.tsx`, `src/components/cases/editor/NodeActionMenu.tsx`
- **Delete node modal**: `src/components/cases/editor/modals/DeleteNodeConfirmation.tsx`
- **Delete relationship modal**: `src/components/cases/editor/modals/DeleteRelationshipConfirmation.tsx`
- **Graph state hook**: `src/hooks/cases/useGraphState.ts`
- **Cascade logic**: `src/lib/cases/cascadeDelete.ts`
- **`min_per_case` helpers**: `src/lib/cases/graphHelpers.ts`


