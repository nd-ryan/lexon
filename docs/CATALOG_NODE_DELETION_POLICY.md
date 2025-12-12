# Catalog Node Deletion Policy

## Overview

This document describes the deletion policy for **catalog nodes** vs **regular nodes** in the shared nodes management system.

## Node Types

### Catalog Nodes (`can_create_new: false`)

**Definition:** Pre-defined nodes that represent fixed taxonomies in the legal domain.

**Examples:**
- **Domain** - Legal domains (Criminal Law, Contract Law, etc.)
- **Forum** - Courts (Supreme Court, District Court, etc.)  
- **Jurisdiction** - Geographic jurisdictions (Federal, State, etc.)

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
- **All case-specific nodes** (Case, Issue, Ruling, etc.)

**Characteristics:**
- Can be created by users in case editor
- May be shared across cases or case-unique
- More ephemeral nature

---

## Deletion Behavior

### 1. Catalog Nodes WITH Connections

**Scenario:** Admin deletes a catalog node (e.g., "Criminal Law" domain) that is used in one or more cases.

**Behavior:**
```
✅ Detach from all connected cases
❌ DO NOT delete from Knowledge Graph
```

**Rationale:** Catalog nodes represent permanent domain knowledge. Even if no current cases use them, they should remain available for future cases.

**Implementation:**
- Removes relationships between catalog node and all case nodes
- Node remains in Neo4j with all its properties
- Cases can still be saved (they just won't have that domain/forum/jurisdiction anymore)

**UI Message:**
> ℹ️ **Catalog Node Detachment:** This is a catalog node (Domain, Forum, or Jurisdiction). It will be **detached from all connected cases** but **preserved in the Knowledge Graph** for future use.

### 2. Catalog Nodes WITHOUT Connections (Orphaned)

**Scenario:** Admin deletes a catalog node that has no case connections.

**Behavior:**
```
✅ Delete from Knowledge Graph
```

**Rationale:** If a catalog node is truly orphaned and the admin wants to remove it, allow deletion. This handles cleanup of unused/deprecated catalog entries.

**UI Message:**
> ⚠️ **Orphaned Catalog Node:** This catalog node has no case connections. It will be **permanently deleted** from the Knowledge Graph.

### 3. Regular Nodes WITH Connections

**Scenario:** Admin deletes a regular shared node (e.g., a Party) that is used in one or more cases.

**Behavior:**
```
✅ Detach from all connected cases
✅ Delete from Knowledge Graph
```

**Rationale:** Regular nodes are user-created and more disposable. Once detached from all cases, they serve no purpose in the KG.

**UI Message:**
> ⚠️ **Permanent Deletion:** This node will be **permanently deleted** from the Knowledge Graph and removed from all connected cases.

### 4. Regular Nodes WITHOUT Connections (Orphaned)

**Scenario:** Admin deletes a regular node that has no case connections.

**Behavior:**
```
✅ Delete from Knowledge Graph
```

**Rationale:** Orphaned user-created nodes should be cleaned up.

**UI Message:**
> ⚠️ **Orphaned Node:** This orphaned node will be **permanently deleted** from the Knowledge Graph.

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
   - Delete from cases where constraint allows
   - Leave connected to cases where it would violate constraint

### Behavior on Min_Per_Case Violation

```
❌ No deletion or detachment occurs
✅ Returns error with details of blocked/deletable cases
```

**UI Message:**
> ⚠️ **Warning:** Some cases require at least one {NodeType} node. Deleting this node would violate that constraint.

---

## Implementation Details

### Backend Logic

**File:** `ai-backend/app/routes/shared_nodes.py`

**Key Logic:**

```python
# 1. Check if catalog node
node_def = next((n for n in schema if n.get("label") == label), {})
is_catalog_node = node_def.get("can_create_new") is False

# 2. If catalog node WITH connections → detach only
if is_catalog_node and len(all_cases) > 0:
    # Delete relationships, preserve node
    # Log "delete" events for cases (meaning detached)
    return {"catalogNodePreserved": True}

# 3. Otherwise → full deletion
DETACH DELETE node
return {"success": True}
```

### Frontend Indication

**File:** `src/app/admin/shared-nodes/page.tsx`

**Visual Cues:**
- **Blue alert box** for catalog node detachment (preserved)
- **Red alert box** for permanent deletion
- **Different messages** based on node type and connection status

### Test Coverage

**File:** `ai-backend/tests/test_shared_nodes.py`

**New Tests (5 additional):**
1. ✅ `test_catalog_node_detached_not_deleted_when_connected`
2. ✅ `test_orphaned_catalog_node_can_be_deleted`
3. ✅ `test_non_catalog_node_deleted_after_detachment`
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
- ✅ Node fully deleted from KG
- 📝 2 "delete" events logged
- 💬 Red warning: "Permanently deleted"

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

### Successful Catalog Node Detachment

```json
{
  "success": true,
  "partial": false,
  "catalogNodePreserved": true,
  "message": "Catalog node detached from all cases but preserved in Knowledge Graph",
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

### Successful Regular Node Deletion

```json
{
  "success": true,
  "partial": false,
  "message": "Node deleted successfully from Knowledge Graph",
  "deletedFromCases": [
    {
      "case_id": "uuid",
      "case_name": "Smith v. Jones",
      "status": "deleted"
    }
  ]
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

Last Updated: December 11, 2024
