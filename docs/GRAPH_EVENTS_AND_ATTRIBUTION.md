# Graph Events and Attribution System

This document explains how Lexon tracks changes to the knowledge graph and attributes nodes/edges to users.

## Overview

Lexon uses a **two-phase storage model**:

1. **Draft Phase (Postgres)**: Cases are uploaded, AI-extracted, and reviewed/edited by users
2. **Published Phase (Neo4j)**: Once reviewed, cases are submitted to the Knowledge Graph

The event logging system tracks changes only after content is published to the KG, ensuring clean attribution to the user who verified and submitted the content.

## Storage Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER WORKFLOW                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   Upload Case ──► AI Extraction ──► Review/Edit ──► Submit to KG    │
│       │               │                  │                │          │
│       ▼               ▼                  ▼                ▼          │
│   ┌───────────────────────────────────────────┐    ┌────────────┐   │
│   │              POSTGRES                      │    │   NEO4J    │   │
│   │  • cases table (draft data)               │    │   (KG)     │   │
│   │  • graph_events table (audit log)         │───►│            │   │
│   │  • pending_kg_deletions (admin queue)     │    │            │   │
│   └───────────────────────────────────────────┘    └────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Event Logging Rules

### When Events ARE Logged

| Action | Events Logged? | Details |
|--------|---------------|---------|
| First KG Submit | ✅ Yes | `create` for all new nodes and edges |
| Save (after first KG submit) | ✅ Yes | `create`/`update`/`delete` for changes |
| Subsequent KG Submit | ➡️ Updates | Updates entity_ids to permanent UUIDs |

### When Events Are NOT Logged

| Action | Events Logged? | Reason |
|--------|---------------|--------|
| AI Extraction | ❌ No | Just a draft - user hasn't verified |
| Save (before first KG submit) | ❌ No | Still editing draft |
| Pre-existing nodes | ❌ No | Already tracked by their original case |

## The `graph_events` Table

```sql
CREATE TABLE graph_events (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL,           -- Which case this event belongs to
  entity_type TEXT NOT NULL,       -- "node" or "edge"
  entity_id TEXT NOT NULL,         -- Node UUID or edge key (from:to:label)
  entity_label TEXT NOT NULL,      -- Node label or edge label
  action TEXT NOT NULL,            -- "create", "update", "delete"
  user_id TEXT NOT NULL,           -- User who made the change
  content_hash TEXT,               -- Hash of properties for change detection
  property_changes JSONB,          -- Detailed property changes (optional)
  created_at TIMESTAMPTZ NOT NULL  -- When the event occurred
);
```

### Actions

| Action | Description |
|--------|-------------|
| `create` | Entity was added to the KG |
| `update` | Entity's properties were modified |
| `delete` | Entity was removed from the KG |

## Entity ID Format

### Nodes
- `entity_id` = the node's permanent UUID (e.g., `case_id`, `ruling_id`, etc.)
- Example: `7821a747-ba60-448c-96d2-6de9ca3454d9`

### Edges
- `entity_id` = composite key: `{from_uuid}:{to_uuid}:{label}`
- Example: `a9d48ebd-e020-4a51-956a-a3648da74084:cc876c7c-286b-4a90-a104-09d72c277aab:ADDRESSES`

## Temp ID → UUID Mapping

During the case lifecycle, nodes go through an ID transformation:

1. **AI Extraction**: Nodes get temporary IDs (`n0`, `n1`, `n2`, ...)
2. **User Edits**: Temp IDs are preserved during draft phase
3. **First KG Submit**: Neo4j assigns permanent UUIDs
4. **Event Logging**: Events are logged with the permanent UUIDs

```
AI creates node ──► temp_id = "n0"
                         │
User edits      ──► temp_id = "n0" (unchanged)
                         │
Submit to KG    ──► Neo4j assigns case_id = "7821a747-..."
                         │
Event logged    ──► entity_id = "7821a747-..." ✓
```

For subsequent edits to already-submitted cases:
- The `temp_id` field already contains the UUID
- Events are logged directly with the UUID
- No mapping needed

## Pre-Existing Nodes

Some nodes are shared across cases (e.g., Doctrine, Policy, Party, Law, FactPattern). These are marked with `is_existing: true`.

**Rules for pre-existing nodes:**
- ❌ No `create` events logged (they were created by another case)
- ✅ Edges TO these nodes ARE logged (the relationship is new)
- ✅ If edited, `update` events are logged

```
Case A creates: Doctrine "Fair Use" ──► create event logged for Case A
Case B references: Doctrine "Fair Use" ──► NO create event for Case B
Case B adds edge: Ruling → RELATES_TO_DOCTRINE → Doctrine ──► create event for edge
```

## Attribution Queries

### Find who last modified a node

```sql
SELECT user_id, action, created_at 
FROM graph_events 
WHERE entity_id = '<node-uuid>' 
ORDER BY created_at DESC 
LIMIT 1;
```

### Find all changes by a user

```sql
SELECT * FROM graph_events 
WHERE user_id = '<user-id>' 
ORDER BY created_at DESC;
```

### Find all events for a case

```sql
SELECT * FROM graph_events 
WHERE case_id = '<case-uuid>' 
ORDER BY created_at ASC;
```

### Get event statistics

```sql
SELECT action, COUNT(*) as count 
FROM graph_events 
GROUP BY action;
```

## Case-Level Attribution

In addition to per-entity tracking, the `cases` table tracks:

| Column | Description |
|--------|-------------|
| `original_author_id` | User who uploaded the case file |
| `kg_submitted_by` | User who first submitted to KG |
| `kg_submitted_at` | Timestamp of first KG submission |

## Node Deletion Handling

When a user deletes a node and submits to KG:

### Case-Unique Nodes
Nodes that only exist within one case (e.g., Proceeding, Ruling, Issue, Argument, Relief):
1. Check if node is isolated (no external connections in KG)
2. If isolated → delete from Neo4j immediately
3. If has external connections → detach from this case (unexpected, logged as warning)

### Non-Case-Unique (Shared) Nodes
Nodes that can be shared across cases (e.g., Party, Doctrine, Policy, Law, FactPattern):
- **Detach relationships** from this case's nodes only
- Node remains in KG - managed via Admin Shared Nodes page

### Deletion Flow Diagram

```
User deletes node in Case Editor
              │
              ▼
      ┌───────────────┐
      │ Is node       │
      │ case_unique?  │
      └───────┬───────┘
              │
     ┌────────┴────────┐
     │                 │
     ▼                 ▼
   YES            NO (shared)
     │                 │
     ▼                 ▼
┌─────────────┐   ┌─────────────────────┐
│ Check if    │   │ Detach from this    │
│ isolated    │   │ case's nodes in KG  │
└──────┬──────┘   └──────────┬──────────┘
       │                     │
  ┌────┴────┐                ▼
  │         │            ┌──────┐
  ▼         ▼            │ DONE │
 YES       NO            └──────┘
  │         │
  ▼         ▼
┌─────┐ ┌──────────┐
│DELETE│ │ Detach   │
│ NOW │ │ from case│
└─────┘ └──────────┘
```

**Key point**: Users can only detach shared nodes from their case. 
KG-wide deletion of shared nodes is done via the Admin Shared Nodes page.

## Case Deletion

When a user deletes an entire case from the case list:

### Draft Cases (never submitted to KG)
- Simply deleted from Postgres
- No KG cleanup needed
- File deleted from storage

### KG-Submitted Cases
Full cleanup is performed:

1. **KG Cleanup**:
   - **Case-unique nodes** (created by this case): Deleted from Neo4j
   - **Non-case-unique nodes** (created by this case): Detached from this case's nodes (stay in KG)
   - **Pre-existing nodes** (referenced from other cases): Detached from this case's nodes (stay in KG)

2. **Event Logging**:
   - `delete` events logged for all nodes and edges
   - Events are kept for audit trail

3. **File Storage**:
   - Original uploaded file deleted from Tigris

4. **Database**:
   - Case record deleted from Postgres

### Important Notes
- Deleting a case does **NOT** delete shared/pre-existing nodes from the KG
- All relationships from this case to other nodes are removed (detached)
- Shared and pre-existing nodes remain in the KG for other cases
- Only case-unique nodes created by this case are fully deleted from the KG

## Admin Interfaces

### Event Logs (`/admin/event-logs`)
- View all graph events with filters
- Filter by action, entity type, user, case
- See event statistics

### Shared Nodes (`/admin/shared-nodes`)
- View all non-case-unique nodes in the KG
- Filter by label (Party, Doctrine, Policy, etc.)
- Orphaned nodes are flagged (not connected to any case)
- Admin can edit or delete shared nodes directly
- Shows connected cases before edit/delete confirmation
- Respects `min_per_case` constraint when deleting

#### min_per_case Schema Property
Some node types require at least one instance per case:

| Node Type | min_per_case | Notes |
|-----------|--------------|-------|
| Domain | 1 | Every case needs a domain |
| Forum | 1 | Every case needs a forum |
| Jurisdiction | 1 | Every case needs a jurisdiction |
| Party | 1 | Every case needs at least one party |
| ReliefType | 1 | Every case needs a relief type |
| Case | 1 | - |
| Proceeding | 1 | - |
| Issue | 1 | - |
| Ruling | 1 | - |
| Argument | 1 | - |
| Relief | 1 | - |

When admin deletes a shared node:
1. System checks if deletion would violate `min_per_case` for any connected case
2. If violated, admin can choose to delete from cases where allowed, or cancel
3. If not violated, node is deleted from all cases and removed from KG

#### Admin Operations Event Logging
All admin operations on shared nodes are logged to `graph_events`:

| Operation | Action | Events Logged |
|-----------|--------|---------------|
| Edit node properties | `update` | One event per connected case |
| Delete node (full) | `delete` | One event per affected case |
| Delete node (partial) | `delete` | One event per case where node was detached |

This ensures complete audit trail even for admin KG-wide operations.

## API Endpoints

### Graph Events
- `GET /api/ai/graph-events` - List events with filters
- `GET /api/ai/graph-events/stats` - Get event statistics

## Example Event Timeline

```
Timeline for Case "Smith v. Jones"
──────────────────────────────────────────────────────────────────

10:00 AM - User uploads case file
           → No events (draft phase)

10:01 AM - AI extracts 15 nodes, 30 edges
           → No events (AI draft)

10:15 AM - User reviews, edits 3 nodes, deletes 1, which deletes 2 edges
           → No events (still draft)

10:30 AM - User clicks "Submit to KG"
           → 14 node create events (user_id = "user123")
           → 28 edge create events (user_id = "user123")
           → 1 node deletion processed

11:00 AM - User edits a Ruling's summary
           → 1 update event (user_id = "user123")

11:05 AM - User adds a new Argument
           → 1 node create event (user_id = "user123")
           → 2 edge create events (user_id = "user123")

11:10 AM - User clicks "Submit to KG"
           → Entity IDs updated with Neo4j UUIDs
           → No new events (already logged on save)

--- Later, user decides to delete the case ---

2:00 PM  - User clicks "Delete" on case in case list
           → Case-unique nodes deleted from KG
           → Non-case-unique nodes detached (stay in KG)
           → 15 node delete events (user_id = "user123")
           → 30 edge delete events (user_id = "user123")
           → Original file deleted from storage
           → Case record deleted from Postgres

--- Admin manages shared nodes ---

3:00 PM  - Admin edits a Party node's name (shared across 5 cases)
           → 5 update events (user_id = "admin@example.com")

3:15 PM  - Admin deletes an orphaned Doctrine node
           → 0 events (node had no case connections)
```

## Implementation Files

| File | Purpose |
|------|---------|
| `ai-backend/app/lib/graph_events_repo.py` | Event logging repository |
| `ai-backend/app/lib/schema.py` | Table DDL (ensure_graph_events_table) |
| `ai-backend/app/routes/kg.py` | KG submit event logging |
| `ai-backend/app/routes/cases.py` | Save event logging, case deletion logging |
| `ai-backend/app/routes/shared_nodes.py` | Admin shared node edit/delete logging |
| `ai-backend/app/routes/graph_events.py` | API endpoints |
| `src/app/admin/event-logs/page.tsx` | Admin UI for events |
| `src/app/admin/shared-nodes/page.tsx` | Admin UI for shared nodes |
