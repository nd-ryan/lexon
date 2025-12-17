# Delete Workflows (Cases + Nodes)

## Overview

Lexon has **three user-facing delete entrypoints** that affect nodes and/or cases. They are intentionally aligned around a shared principle:

- **Shared nodes** (`case_unique: false`) are generally **preserved** in Neo4j; “delete” usually means **detach** relationships to a case (or to many cases).
- **Case-unique nodes** (`case_unique: true`) are generally **owned by a single case** and may be **deleted** from Neo4j, but we use an **isolation check** as a safety guard where applicable.

This doc describes **what each entrypoint does**, which APIs are called, and what happens in **Postgres vs Neo4j**.

## Terminology

- **Detach**: delete only the relationships connecting a node to nodes that belong to a specific case (or set of cases). The node itself remains in Neo4j.
- **Delete**: `DETACH DELETE` the node in Neo4j (removes the node and all its relationships).
- **Case membership (authoritative)**: computed from Postgres `cases.extracted` JSON (nodes/edges), not from Neo4j traversal.

## 1) Admin: Delete Shared Node (`/admin/shared-nodes`)

### User action
Admin opens the shared nodes admin page and clicks “Delete”.

### Request path
- **Frontend UI**: `src/app/admin/shared-nodes/page.tsx`
- **Next.js API**: `/api/admin/shared-nodes/[label]/[nodeId]` (DELETE)
- **Backend**: `/api/ai/shared-nodes/{label}/{node_id}` (DELETE)

### Neo4j behavior (current)
The backend first computes which cases reference this shared node (from Postgres extracted data), then applies:

- **If referenced by ≥1 case**: detach from those cases and **preserve** the node in Neo4j.
- **If referenced by 0 cases (orphaned)**: **delete** the node from Neo4j.
- **`min_per_case` constraint**: can block detaching from some cases; supports `force_partial=true` to detach only where safe.

### Implementation notes
- Detachment/deletion uses the same Neo4j primitives as KG flows via `Neo4jUploader`:
  - `detach_node_from_case(...)`
  - `delete_node(...)`
- Response includes flags:
  - `nodePreserved: true` when the node had any case references
  - `catalogNodePreserved: true` (back-compat) when `can_create_new: false`

See also: `docs/ADMIN_SHARED_NODE_DELETION_POLICY.md`.

## 2) User: Delete Case (`/cases` list)

### User action
User clicks “Delete” next to a case on the cases list page.

### Request path
- **Frontend UI**: `src/app/cases/page.tsx` → `DELETE /api/cases/:id`
- **Next.js API**: `src/app/api/cases/[id]/route.ts` (DELETE)
- **Backend**: `/api/ai/cases/{case_id}` (DELETE)

### Postgres behavior
- The case row is deleted from Postgres.
- The original uploaded file is deleted from storage if present.
- Delete events are logged for the case graph.

### Neo4j behavior (depends on whether case was KG-submitted)
Case deletion only performs Neo4j cleanup if the case has been submitted to KG:

- **If `kg_submitted_at` is null**: **no Neo4j cleanup** runs (the case never wrote to KG).
- **If `kg_submitted_at` is set**: Neo4j cleanup runs per node in the case graph:
  - **`is_existing: true`**: detach from this case, preserve node (shared / reused)
  - **`case_unique: true`**: delete only if isolated to this case; otherwise detach (defensive safety)
  - **`case_unique: false`**: detach from this case, preserve node

### Why the isolation check matters
Even “case-unique” nodes can theoretically end up with external connections (unexpected graph state, reuse edge-case, manual changes). In that case, deleting the case should not delete globally connected KG data.

## 3) User: Delete Nodes in Case Editor (`/cases/[id]`)

### User action
In edit mode, user deletes nodes, then either **Save** or **Submit to KG**.

### Client-side semantics ("delete" in the editor)
The editor uses a graph-state model with statuses:
- `active`
- `deleted` (explicitly deleted)
- `orphaned` (descendant nodes that may be removed if they no longer have an active parent)

### Cascade Delete System

When a user deletes a node in the editor, the system computes a **cascade plan** based on the UI hierarchy (`views_v3.json`) and relationship cardinalities (`schema_v3.json`).

#### How it works

1. **Build UI Hierarchy**: Parse `views_v3.json` to determine parent-child relationships as displayed in the editor (e.g., Issue → Ruling → Argument → Doctrine).

2. **Compute Cascade Plan**: For each UI-child of the deleted node:
   - Count how many **other parents** (of the same relationship type) the child has in the graph
   - **If no other parents exist** → cascade delete the child
   - **If other parents exist** → detach only (remove edge, child remains active)

3. **Recurse**: Process cascaded children the same way, building a complete deletion plan.

#### Example: Deleting an Issue

| Node | Relationship | Other parents? | Result |
|------|--------------|----------------|--------|
| Issue | (primary delete) | - | Deleted |
| Ruling | SETS → Issue | None (one-to-one) | Cascade delete |
| Argument | EVALUATED_IN → Ruling | Has other Rulings? | Cascade if no, detach if yes |
| Doctrine | RELATES_TO_DOCTRINE ← Argument | Has other Arguments? | Cascade if no, detach if yes |
| ReliefType | IS_TYPE ← Relief | Has other Reliefs? | Cascade if no, detach if yes |

#### Confirmation Modal

The delete confirmation modal shows:
- **"Will be removed"** (red): Nodes that cascade-delete because they have no other parents
  - Items marked `(shared)` indicate `case_unique: false` nodes that will be preserved in the KG
- **"Will be unlinked"** (blue): Nodes that have other parents in this case and will remain visible

#### Key files

- `src/lib/cases/cascadeDelete.ts` - Core cascade logic
  - `buildUIHierarchy()` - Parses views config
  - `buildCardinalityMap()` - Parses schema relationships
  - `computeCascadePlan()` - Computes which nodes cascade vs detach
  - `checkCascadeMinPerCase()` - Validates against min_per_case constraints
  - `applyCascadePlan()` - Applies the plan to graph state
- `src/components/cases/editor/modals/DeleteNodeConfirmation.tsx` - Confirmation UI
- `src/hooks/cases/useGraphState.ts` - `deleteNodeWithCascade()` applies the plan

### `min_per_case` protection (editor)
Some labels in the schema define a `min_per_case` constraint (minimum count required per case).

- **UI guard**: delete/unlink actions that would reduce the case’s reachable node counts below `min_per_case` are disabled in the editor, and the disabled controls show a tooltip explaining the reason.
- **Validation backstop**: save/submit runs validation against the post-edit graph and will block persistence if any reachable label violates `min_per_case` (even if a user bypasses the UI disable).

### Save behavior (Postgres only)
Saving a case (`PUT /api/cases/:id` → `/api/ai/cases/:id`) writes a payload that contains:
- only `active` nodes
- only `active` edges not attached to deleted nodes
- “truly orphaned” nodes are excluded from the saved payload

**Save does not mutate Neo4j.**

### Submit-to-KG behavior (Neo4j sync)
Submit calls:
- **Next.js API**: `/api/kg/submit` (POST)
- **Backend**: `/api/ai/kg/submit` (POST)

The backend compares the case graph previously stored in Postgres vs the newly produced graph and identifies **deleted nodes** (“in old but not in new”). For each deleted node:

- **`case_unique: true`**: delete from Neo4j only if isolated; otherwise detach.
- **`case_unique: false`**: detach from the case (shared nodes preserved; admin handles global cleanup).

## Summary Matrix

| Entry point | Scope | Shared (`case_unique:false`) | Case-unique (`case_unique:true`) | Notes |
| --- | --- | --- | --- | --- |
| Admin shared-nodes delete | Across cases referencing a shared node | Detach from all referencing cases; delete only if orphaned | N/A (labels rejected) | Enforces `min_per_case` and supports partial detach |
| Delete case | Per-case | Detach (preserve) when KG-submitted | Delete if isolated; else detach | Neo4j cleanup runs only when `kg_submitted_at` is set |
| Editor delete + Submit | Per-case | Detach (preserve) | Delete if isolated; else detach | Save is Postgres-only; Submit performs Neo4j sync |

Last Updated: December 16, 2025
