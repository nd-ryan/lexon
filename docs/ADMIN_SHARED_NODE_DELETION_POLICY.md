# Catalog / Shared Node Deletion Policy

## Overview

This document describes the deletion policy for shared nodes in the shared nodes management system, including:
- **Catalog nodes** (`can_create_new: false`) - fixed taxonomies
- **Preset nodes** (`preset: true`) - canonical nodes uploaded by legal experts
- **Regular (user-created) shared nodes** - nodes created by users

**Important:** The deletion behavior depends on whether the node is **preset** and whether it has **case references**:

- If a shared node is referenced by **one or more cases**, the delete action **detaches it from cases and preserves the node** in Neo4j.
- If a shared node is **orphaned** (no case references):
  - **Preset nodes**: **preserved** in Neo4j (unless admin uses `force_delete=true`)
  - **Non-preset nodes**: **deleted** from Neo4j automatically

**Related:** For a full end-to-end view of *all* delete entry points (admin shared-nodes delete, delete case, editor delete + save/submit), see `docs/DELETE_WORKFLOWS.md`.

## Node Types

### Catalog Nodes (`can_create_new: false`)

**Definition:** Pre-defined nodes that represent fixed taxonomies in the legal domain.

**Examples:**
- **Domain** - Legal domains (Criminal Law, Contract Law, etc.)
- **Forum** - Courts (Supreme Court, District Court, etc.)  
- **Jurisdiction** - Geographic jurisdictions (Federal, State, etc.)
- **ReliefType** - Fixed relief type taxonomy (injunction, damages, etc.)

**Characteristics:**
- Cannot be created by users in the case editor
- Shared across all cases
- Managed by admins only

### Regular/User-Created Nodes (`can_create_new: true`)

**Definition:** Nodes that users can create on-demand when editing cases.

**Examples:**
- **Party** - Litigants, defendants, etc.
- **Doctrine** - Legal doctrines
- **Policy** - Policy considerations
- **Other shared (non-case-unique) user-created nodes** (e.g., Law, FactPattern, etc.)

**Characteristics:**
- Can be created by users in case editor
- May be shared across cases or case-unique
- More ephemeral nature

### Preset Nodes (`preset: true`)

**Definition:** Canonical, stable nodes uploaded by legal experts that should be protected from accidental deletion.

**Examples:**
- Pre-loaded **Doctrine** nodes (e.g., "Rule of Reason", "Per Se Illegality")
- Pre-loaded **FactPattern** nodes (e.g., "Price Fixing", "Bid Rigging")
- Pre-loaded **Policy** nodes (e.g., "Consumer Welfare", "Economic Efficiency")
- Pre-loaded **Law** nodes (e.g., "Sherman Act, Section 1", "Clayton Act, Section 7")

**Characteristics:**
- Marked with `preset: true` property in Neo4j
- Protected from auto-deletion when orphaned
- Admin can toggle preset status via the shared nodes page
- Admin can force-delete orphaned preset nodes if needed

**Note:** The preset flag is orthogonal to `can_create_new` - both catalog nodes and user-creatable node types can be marked as preset.

**Note:** The **admin shared nodes page** (and the `/api/ai/shared-nodes/...` endpoints) only manages labels where `case_unique=false`. Case-specific labels like `Case`, `Issue`, and `Ruling` (`case_unique=true`) are managed via the **case update / submit / delete** flows, not via the shared-nodes admin interface.

**Related safety note (case delete / KG submit):**
When the backend decides whether it is safe to delete a `case_unique:true` node from Neo4j, it uses an isolation safety check:

- Connections to **shared/catalog** nodes (e.g. `Domain`, `ReliefType`, `Doctrine`, `Party`) are expected and **do not** block deletion of the case-unique node.
- Only connections to **case-unique** nodes outside the case will force “detach-only” instead of deletion.

---

## Deletion Behavior

### 1. Any Shared Node WITH Case References (Catalog OR Regular)

**Scenario:** Admin deletes a shared node (e.g., Domain, Forum, Jurisdiction, ReliefType, Party, Doctrine, etc.) that is referenced by one or more cases.

**Behavior:**
```
✅ Detach from all connected cases
❌ DO NOT delete from Knowledge Graph
```

**Rationale:** The shared-nodes delete action is primarily a **case cleanup** operation. When a node is in use, we remove it from cases but keep the node itself available for future reuse and to reduce accidental data loss across cases.

**Implementation:**
- Removes relationships between the shared node and nodes belonging to each connected case
- Node remains in Neo4j with all its properties
- Cases can still be saved (they just won’t reference that node anymore)
- For each affected case, Postgres is updated to keep case membership and “last published” baselines consistent:
  - Updates `cases.extracted` (authoritative case membership)
  - Updates `cases.kg_extracted` when present (published baseline used by KG diff/cleanup)
  - Updates `kg_submitted_at/by` when `kg_extracted` is updated (keeps `kg_diverged` aligned)

**UI Message (admin shared nodes page):**
> ℹ️ **Detach from Cases:** This node will be **detached from all connected cases** but **preserved in the Knowledge Graph**.

### 2. Orphaned Non-Preset Shared Node

**Scenario:** Admin deletes a non-preset shared node that has no case references.

**Behavior:**
```
✅ Delete from Knowledge Graph (DETACH DELETE)
```

**Rationale:** Orphaned non-preset shared nodes serve no purpose and can be safely cleaned up.

**Event logging note:** Orphaned node deletion does not log to `graph_events` because the audit log is case-scoped and there are no referencing cases to attach an event to.

**UI Message (admin shared nodes page):**
> ⚠️ **Orphaned Node:** This orphaned node will be **permanently deleted** from the Knowledge Graph.

### 3. Orphaned Preset Shared Node

**Scenario:** Admin deletes a preset shared node that has no case references.

**Behavior:**
```
❌ DO NOT delete from Knowledge Graph (by default)
✅ Can be deleted with force_delete=true
```

**Rationale:** Preset nodes are canonical data uploaded by legal experts and should be protected from accidental deletion. They may be temporarily orphaned but could be needed for future cases.

**UI Message (admin shared nodes page):**
> 🔒 **Preset Node:** This is a **preset node** (canonical data from legal experts). It will be **preserved in the Knowledge Graph** unless you explicitly force delete it.

**Force Delete:** Admin can explicitly force-delete an orphaned preset node by clicking "Force Delete Preset Node" in the delete modal. This passes `force_delete=true` to the backend.

---

## Min_Per_Case Constraint

### Rule

If deleting a node would leave a case with fewer than `min_per_case` instances of that node type, deletion is blocked.

**Example:**
- `Party` has `min_per_case: 1`
- A case has only 1 Party node
- Attempting to delete that Party returns an error

### Options When Blocked

1. **Cancel the deletion entirely**
2. **Partial deletion** (with `force_partial=true` flag):
   - Detach from cases where the constraint allows
   - Leave connected to cases where detaching would violate the constraint

### Behavior on Min_Per_Case Violation

When `force_partial=false`:

```
❌ No deletion or detachment occurs
✅ Returns error with details of blocked/deletable cases
```

When `force_partial=true`:
- Detach only from **deletable** cases
- Leave the node connected to **blocked** cases
- The node is **not deleted** from Neo4j (because it remains referenced)

**UI Message:**
> ⚠️ **Warning:** Some cases require at least one {NodeType} node. Deleting this node would violate that constraint.

---

## Implementation Details

### Backend Logic

**File:** `ai-backend/app/routes/shared_nodes.py`

**Key Logic:**

```python
# Identify catalog nodes (used for back-compat flagging)
node_def = next((n for n in schema if n.get("label") == label), {})
is_catalog_node = node_def.get("can_create_new") is False

# Current deletion policy:
# - If referenced by any cases: detach from connected cases, preserve node in Neo4j
# - Only fully delete when orphaned (no case references)
if len(all_cases) > 0:
    # Delete relationships, preserve node
    resp = {"success": True, "nodePreserved": True}
    if is_catalog_node:
        resp["catalogNodePreserved"] = True  # back-compat
    return resp

# Orphaned: fully delete
DETACH DELETE node
return {"success": True}  # plus message + deletedFromCases in the real response
```

### Frontend Indication

**File:** `src/app/admin/shared-nodes/page.tsx`

**Visual Cues:**
- **Blue alert box** when the node has connected cases (detach + preserve)
- **Red alert box** when the node is orphaned (permanent deletion)
- **Min-per-case confirmation modal** when detaching from all cases is blocked; allows partial detachment

### Test Coverage

**File:** `ai-backend/tests/test_shared_nodes.py`

**New Tests (5 additional):**
1. ✅ `test_catalog_node_detached_not_deleted_when_connected`
2. ✅ `test_orphaned_catalog_node_can_be_deleted`
3. ✅ `test_non_catalog_node_deleted_after_detachment` *(name is misleading; it asserts the node is preserved when referenced)*
4. ✅ `test_min_per_case_error_prevents_any_deletion`
5. ✅ `test_detachment_removes_only_case_relationships`

**Total Deletion Tests:** 10 (all passing)

---

## Examples

### Example 1: Deleting "Criminal Law" Domain (Catalog)

**State:**
- Used in 5 cases
- No violations

**Result:**
- ✅ Detached from all 5 cases
- ✅ Node remains in KG with full data
- 📝 5 "delete" events logged (one per case detachment)
- 💬 Blue info message: "Catalog node detached but preserved"

### Example 2: Deleting "John Doe" Party (Regular)

**State:**
- Used in 2 cases (both have other parties)
- No violations

**Result:**
- ✅ Detached from both cases
- ✅ Node preserved in KG
- 📝 2 "delete" events logged
- 💬 Blue info message: "Detached but preserved"

### Example 3: Deleting Last "Forum" in a Case

**State:**
- Forum has `min_per_case: 1`
- Case only has this one Forum

**Result:**
- ❌ Deletion blocked
- 📝 No events logged
- 💬 Red error: "Would violate min_per_case constraint"
- 💡 Option: Partial delete from other cases only

---

## API Response Format

### Successful Detachment (Node Preserved; Catalog OR Regular)

```json
{
  "success": true,
  "partial": false,
  "nodePreserved": true,
  "catalogNodePreserved": true,
  "message": "Node detached from all cases but preserved in Knowledge Graph",
  "deletedFromCases": [
    {
      "case_id": "uuid",
      "case_name": "Smith v. Jones",
      "status": "detached",
      "relationshipsRemoved": 3
    }
  ]
}
```

**Notes:**
- `catalogNodePreserved` is only present/true for catalog nodes (`can_create_new: false`) for backwards compatibility.
- For non-catalog shared nodes, expect `nodePreserved: true` and `catalogNodePreserved` to be absent/falsey.

### Successful Orphaned Node Deletion (Node Deleted)

```json
{
  "success": true,
  "partial": false,
  "message": "Node deleted successfully from Knowledge Graph",
  "deletedFromCases": []
}
```

### Min_Per_Case Violation

```json
{
  "success": false,
  "error": "min_per_case_violation",
  "message": "Cannot delete: 1 case(s) would have fewer than 1 Party node(s)",
  "blockedCases": [
    {"case_id": "uuid1", "case_name": "Case 1", "currentCount": 1}
  ],
  "deletableCases": [
    {"case_id": "uuid2", "case_name": "Case 2", "currentCount": 2}
  ],
  "minPerCase": 1
}
```

### Partial Detachment (`force_partial=true`)

```json
{
  "success": true,
  "partial": true,
  "message": "Node remains connected to 1 case(s) due to min_per_case constraint",
  "deletedFromCases": [
    {
      "case_id": "uuid2",
      "case_name": "Case 2",
      "status": "detached",
      "relationshipsRemoved": 2
    }
  ],
  "remainingCases": [
    { "case_id": "uuid1", "case_name": "Case 1" }
  ]
}
```

---

## Future Considerations

### Potential Enhancements

1. **Soft Delete for Catalog Nodes**
   - Add `is_active` flag instead of detachment
   - Archive rather than delete

2. **Catalog Node Replacement**
   - When detaching, optionally replace with another catalog node of same type

3. **Audit Trail Enhancement**
   - Distinguish "detached" vs "deleted" in event logs
   - Add `catalogNodePreserved` flag to events

4. **UI Improvements**
   - Show "Catalog" badge on node list
   - Warning icon for nodes used in many cases

---

## Schema Configuration

Catalog nodes are identified by the `can_create_new` property in `ai-backend/schema_v3.json`:

```json
{
  "label": "Domain",
  "case_unique": false,
  "can_create_new": false,  // ← Marks this as a catalog node
  "min_per_case": 1,
  "properties": { ... }
}
```

Last Updated: December 31, 2025
