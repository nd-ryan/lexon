"""API routes for managing shared (non-case-unique) nodes in the Knowledge Graph."""

import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.lib.security import get_api_key
from app.lib.neo4j_client import neo4j_client
from app.lib.neo4j_uploader import Neo4jUploader
from app.lib.logging_config import setup_logger
from app.lib.db import get_db
from app.lib.graph_events_repo import graph_events_repo, compute_content_hash
from app.lib.case_repo import case_repo


logger = setup_logger("shared-nodes")
router = APIRouter(prefix="/shared-nodes", dependencies=[Depends(get_api_key)])


def get_user_id(request: Request) -> str:
    """Extract user ID from X-User-Id header (set by Next.js API routes)."""
    return request.headers.get("X-User-Id", "admin")


def load_schema() -> List[Dict[str, Any]]:
    """Load the schema from file."""
    import os
    schema_path = os.path.join(os.path.dirname(__file__), "..", "..", "schema_v3.json")
    with open(schema_path, "r") as f:
        return json.load(f)


def get_shared_labels(schema: List[Dict[str, Any]]) -> List[str]:
    """Get labels where case_unique=false."""
    return [
        node_def.get("label")
        for node_def in schema
        if isinstance(node_def, dict) and node_def.get("case_unique") is False
    ]


def get_min_per_case(schema: List[Dict[str, Any]], label: str) -> int:
    """Get min_per_case value for a label (default 0)."""
    for node_def in schema:
        if isinstance(node_def, dict) and node_def.get("label") == label:
            return node_def.get("min_per_case", 0)
    return 0


def get_id_property(label: str) -> str:
    """Get the *_id property name for a label."""
    # Convert label to snake_case and add _id
    # e.g., "ReliefType" -> "relief_type_id", "Party" -> "party_id"
    import re
    snake = re.sub(r'(?<!^)(?=[A-Z])', '_', label).lower()
    return f"{snake}_id"


def get_node_display_name(node: Dict[str, Any]) -> str:
    """Get a display name for a node."""
    props = node.get("properties", {})
    # Try common name properties
    for key in ["name", "label", "type", "text", "description"]:
        if key in props and props[key]:
            val = props[key]
            if isinstance(val, str) and len(val) > 100:
                return val[:100] + "..."
            return str(val)
    return f"{node.get('label', 'Unknown')}"


def find_cases_containing_node(db: Session, node_id: str, node_label: str) -> List[Dict[str, Any]]:
    """Find all cases that contain a reference to this node (from Postgres extracted data)."""
    from sqlalchemy import text
    
    # Query cases where extracted references this node_id.
    #
    # Important: for *catalog nodes* (can_create_new=false) the case JSON may not include the
    # catalog node in extracted.nodes; instead, the catalog node is referenced by extracted.edges
    # and later enriched client-side (see `useCatalogEnrichment` in the frontend).
    #
    # Note: cases table has id, filename, extracted - NOT name or citation columns.
    # The case name and citation are stored in extracted.nodes where label="Case".
    id_prop = get_id_property(node_label)

    # Map of catalog node labels to how they are referenced from edges in extracted JSON.
    # Each entry is a list of (edge_label, endpoint) where endpoint is "from" or "to".
    # This mirrors the frontend enrichment logic.
    catalog_edge_refs: Dict[str, List[Dict[str, str]]] = {
        "Domain": [{"edge_label": "CONTAINS", "endpoint": "from"}],  # Domain -> Case
        "Forum": [
            {"edge_label": "HEARD_IN", "endpoint": "to"},  # Proceeding -> Forum
            {"edge_label": "PART_OF", "endpoint": "from"},  # Forum -> Jurisdiction
        ],
        "Jurisdiction": [{"edge_label": "PART_OF", "endpoint": "to"}],  # Forum -> Jurisdiction
        "ReliefType": [{"edge_label": "IS_TYPE", "endpoint": "to"}],  # Relief -> ReliefType
    }

    edge_refs = catalog_edge_refs.get(node_label, [])

    # Build edge EXISTS clause for catalog nodes (empty for non-catalog nodes)
    edge_exists_clause = ""
    if edge_refs:
        # (edge->>'label' = 'X' AND edge->>'from' = :node_id) OR ...
        edge_conditions = []
        for ref in edge_refs:
            edge_label = ref["edge_label"]
            endpoint = ref["endpoint"]
            if endpoint not in ("from", "to"):
                continue
            edge_conditions.append(
                f"(edge->>'label' = '{edge_label}' AND edge->>'{endpoint}' = :node_id)"
            )
        if edge_conditions:
            edge_exists_clause = f"""
              OR EXISTS (
                SELECT 1 FROM jsonb_array_elements(extracted->'edges') AS edge
                WHERE {" OR ".join(edge_conditions)}
              )
            """

    query = text("""
        SELECT id, filename, extracted, kg_extracted
        FROM cases
        WHERE extracted IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM jsonb_array_elements(extracted->'nodes') AS node
            WHERE node->>'label' = :label
              AND node->'properties'->>:id_prop = :node_id
          )
          {edge_exists_clause}
    """)
    
    query = text(query.text.format(edge_exists_clause=edge_exists_clause))
    result = db.execute(query, {"label": node_label, "id_prop": id_prop, "node_id": node_id})
    
    cases = []
    for row in result:
        extracted = row.extracted or {}
        nodes = extracted.get("nodes", [])
        edges = extracted.get("edges", [])
        
        # Find the Case node to get case_name and citation
        case_node = next((n for n in nodes if n.get("label") == "Case"), None)
        case_props = case_node.get("properties", {}) if case_node else {}
        case_name = case_props.get("name") or row.filename
        citation = case_props.get("citation")
        
        # Count how many nodes of this label are in this case.
        #
        # For catalog nodes, the node may be absent from extracted.nodes; count unique references
        # from extracted.edges instead.
        if edge_refs:
            ref_ids: Set[str] = set()
            for e in edges:
                if not isinstance(e, dict):
                    continue
                e_label = e.get("label")
                e_from = e.get("from")
                e_to = e.get("to")
                for ref in edge_refs:
                    if e_label != ref["edge_label"]:
                        continue
                    endpoint = ref["endpoint"]
                    val = e_from if endpoint == "from" else e_to
                    if val:
                        ref_ids.add(str(val))
            label_count = len(ref_ids)
        else:
            label_count = sum(1 for n in nodes if n.get("label") == node_label)
        
        cases.append({
            "case_id": str(row.id),
            "case_name": case_name,
            "citation": citation,
            "labelCount": label_count,
            "extracted": extracted,  # Keep for later use in detachment
            "kg_extracted": row.kg_extracted,  # Keep for published snapshot consistency updates
        })
    
    return cases


def get_case_node_ids(nodes: List[Dict]) -> Set[str]:
    """Get all *_id values from nodes."""
    ids = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        props = node.get("properties", {})
        for key, val in props.items():
            if key.endswith("_id") and val:
                ids.add(str(val))
    return ids


def remove_node_from_extracted(
    extracted: Dict[str, Any],
    node_label: str,
    node_id: str,
) -> Tuple[Dict[str, Any], int, int]:
    """Remove a shared node reference from a case's extracted payload.

    This mutates *Postgres case data* (cases.extracted) semantics:
    - Remove the node from extracted.nodes if present (match by label + *_id property)
    - Remove any incident edges from extracted.edges that reference:
      - the node's temp_id(s) (typical for non-catalog nodes), or
      - the node_id directly (typical for catalog node references)

    Returns:
      (new_extracted, removed_nodes_count, removed_edges_count)
    """
    if not isinstance(extracted, dict):
        return extracted, 0, 0

    nodes = extracted.get("nodes") or []
    edges = extracted.get("edges") or []
    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(edges, list):
        edges = []

    id_prop = get_id_property(node_label)
    target_edge_ids: Set[str] = {str(node_id)}

    removed_nodes = 0
    new_nodes: List[Any] = []
    for n in nodes:
        if not isinstance(n, dict):
            new_nodes.append(n)
            continue
        if n.get("label") != node_label:
            new_nodes.append(n)
            continue
        props = n.get("properties") or {}
        if not isinstance(props, dict):
            new_nodes.append(n)
            continue
        if str(props.get(id_prop, "")) != str(node_id):
            new_nodes.append(n)
            continue

        removed_nodes += 1
        tid = n.get("temp_id")
        if isinstance(tid, str) and tid:
            target_edge_ids.add(tid)
        continue

    removed_edges = 0
    new_edges: List[Any] = []
    for e in edges:
        if not isinstance(e, dict):
            new_edges.append(e)
            continue
        frm = e.get("from") or e.get("from_")
        to = e.get("to")
        if (isinstance(frm, str) and frm in target_edge_ids) or (isinstance(to, str) and to in target_edge_ids):
            removed_edges += 1
            continue
        new_edges.append(e)

    if removed_nodes == 0 and removed_edges == 0:
        return extracted, 0, 0

    new_extracted = dict(extracted)
    new_extracted["nodes"] = new_nodes
    new_extracted["edges"] = new_edges
    return new_extracted, removed_nodes, removed_edges


def get_case_connection_counts_for_nodes(
    db: Session, node_label: str, id_prop: str, node_ids: List[str]
) -> Dict[str, int]:
    """Return {node_id: distinct_case_count} for the given node ids, based on Postgres extracted JSON.

    This matches the same 'case membership' concept used by `find_cases_containing_node`, but in
    a batched form suitable for list views.
    """
    if not node_ids:
        return {}

    from sqlalchemy import text, bindparam

    # Same catalog edge reference map used in `find_cases_containing_node`
    catalog_edge_refs: Dict[str, List[Dict[str, str]]] = {
        "Domain": [{"edge_label": "CONTAINS", "endpoint": "from"}],  # Domain -> Case
        "Forum": [
            {"edge_label": "HEARD_IN", "endpoint": "to"},  # Proceeding -> Forum
            {"edge_label": "PART_OF", "endpoint": "from"},  # Forum -> Jurisdiction
        ],
        "Jurisdiction": [{"edge_label": "PART_OF", "endpoint": "to"}],  # Forum -> Jurisdiction
        "ReliefType": [{"edge_label": "IS_TYPE", "endpoint": "to"}],  # Relief -> ReliefType
    }
    edge_refs = catalog_edge_refs.get(node_label, [])

    # Build SELECTs (UNION ALL) from nodes and edges
    selects: List[str] = [
        """
        SELECT
          node->'properties'->>:id_prop AS node_id,
          c.id AS case_id
        FROM cases c
        CROSS JOIN LATERAL jsonb_array_elements(c.extracted->'nodes') AS node
        WHERE c.extracted IS NOT NULL
          AND node->>'label' = :label
          AND node->'properties'->>:id_prop IN :node_ids
        """
    ]

    for ref in edge_refs:
        edge_label = ref.get("edge_label")
        endpoint = ref.get("endpoint")
        if not edge_label or endpoint not in ("from", "to"):
            continue
        selects.append(
            f"""
            SELECT
              edge->>'{endpoint}' AS node_id,
              c.id AS case_id
            FROM cases c
            CROSS JOIN LATERAL jsonb_array_elements(c.extracted->'edges') AS edge
            WHERE c.extracted IS NOT NULL
              AND edge->>'label' = '{edge_label}'
              AND edge->>'{endpoint}' IN :node_ids
            """
        )

    sql = f"""
      WITH matched AS (
        {' UNION ALL '.join(selects)}
      )
      SELECT node_id, COUNT(DISTINCT case_id)::int AS case_count
      FROM matched
      GROUP BY node_id
    """

    stmt = (
        text(sql)
        .bindparams(bindparam("node_ids", expanding=True))
    )
    rows = db.execute(stmt, {"label": node_label, "id_prop": id_prop, "node_ids": node_ids}).fetchall()
    return {str(r.node_id): int(r.case_count) for r in rows if r.node_id}


@router.get("")
def list_shared_nodes(
    label: Optional[str] = Query(None, description="Filter by node label"),
    orphaned_only: bool = Query(False, description="Only show nodes with no connections"),
    include_case_counts: bool = Query(False, description="If true, compute Postgres-based case connection counts (slower)"),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    """List shared nodes from the Knowledge Graph."""
    schema = load_schema()
    shared_labels = get_shared_labels(schema)
    
    if label and label not in shared_labels:
        raise HTTPException(400, f"Label '{label}' is not a shared node type")
    
    labels_to_query = [label] if label else shared_labels
    
    nodes = []
    
    for lbl in labels_to_query:
        id_prop = get_id_property(lbl)

        # Case-count computation is the expensive part; by default we only do it for single-label
        # views (or when explicitly requested).
        use_case_counts = bool(label) or include_case_counts
        
        # Query nodes with Neo4j relationship count (graph connections)
        query = f"""
            MATCH (n:{lbl})
            OPTIONAL MATCH (n)-[r]-()
            WITH n, count(r) as connectionCount
            {"WHERE connectionCount = 0" if (orphaned_only and not use_case_counts) else ""}
            RETURN n, connectionCount
            ORDER BY n.name, n.{id_prop}
            SKIP $offset LIMIT $limit
        """
        
        results = neo4j_client.execute_query(query, {"offset": offset, "limit": limit})

        case_counts: Dict[str, int] = {}
        if use_case_counts:
            # Compute Postgres case-connection counts in batch for this page of nodes
            node_ids = []
            for record in results:
                node = record["n"]
                node_id_val = node.get(id_prop, "")
                if node_id_val:
                    node_ids.append(str(node_id_val))
            case_counts = get_case_connection_counts_for_nodes(db, lbl, id_prop, node_ids)

        for record in results:
            node = record["n"]
            graph_conn_count = record["connectionCount"]
            node_id_val = str(node.get(id_prop, "") or "")
            case_conn_count = int(case_counts.get(node_id_val, 0)) if use_case_counts else None

            # Orphaned/connected status:
            # - If using Postgres case counts, base orphaned status on case membership (matches delete modal behavior)
            # - Otherwise, base it on Neo4j relationships (fast for "All Types" browsing)
            is_orphaned = (case_conn_count == 0) if use_case_counts else (graph_conn_count == 0)
            if orphaned_only and not is_orphaned:
                continue
            
            node_data = {
                "label": lbl,
                "id": node_id_val,
                "name": get_node_display_name({"label": lbl, "properties": node}),
                "properties": node,
                # For backwards compatibility:
                # - When case counts are computed, `connectionCount` reflects case connections.
                # - Otherwise it reflects Neo4j relationship count.
                "connectionCount": (case_conn_count if use_case_counts else graph_conn_count),
                "caseConnectionCount": case_conn_count,
                # Expose Neo4j relationship count for debugging/visibility
                "graphConnectionCount": graph_conn_count,
                "isOrphaned": is_orphaned,
                # Preset status - canonical nodes defined by legal experts
                "isPreset": node.get("preset") is True,
            }
            nodes.append(node_data)
    
    return {
        "success": True,
        "nodes": nodes,
        "labels": shared_labels,
    }


@router.get("/{label}/{node_id}")
def get_shared_node(label: str, node_id: str, db: Session = Depends(get_db)):
    """Get a single shared node with its connected cases."""
    schema = load_schema()
    shared_labels = get_shared_labels(schema)
    
    if label not in shared_labels:
        raise HTTPException(400, f"Label '{label}' is not a shared node type")
    
    id_prop = get_id_property(label)
    
    # Get the node from Neo4j
    query = f"""
        MATCH (n:{label} {{{id_prop}: $node_id}})
        OPTIONAL MATCH (n)-[r]-()
        RETURN n, count(r) as connectionCount
    """
    results = neo4j_client.execute_query(query, {"node_id": node_id})
    
    if not results:
        raise HTTPException(404, "Node not found")
    
    record = results[0]
    node = record["n"]
    conn_count = record["connectionCount"]
    
    # Get connected cases from Postgres (authoritative source)
    cases_data = find_cases_containing_node(db, node_id, label)
    connected_cases = [
        {"case_id": c["case_id"], "case_name": c["case_name"], "citation": c["citation"]}
        for c in cases_data
    ]
    
    return {
        "success": True,
        "node": {
            "label": label,
            "id": node_id,
            "name": get_node_display_name({"label": label, "properties": node}),
            "properties": node,
            "connectionCount": conn_count,
            "isOrphaned": conn_count == 0,
            "isPreset": node.get("preset") is True,
        },
        "connectedCases": connected_cases,
        "minPerCase": get_min_per_case(schema, label),
    }


class UpdateNodeRequest(BaseModel):
    properties: Dict[str, Any]


@router.put("/{label}/{node_id}")
def update_shared_node(
    label: str, 
    node_id: str, 
    body: UpdateNodeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update a shared node's properties."""
    schema = load_schema()
    shared_labels = get_shared_labels(schema)
    
    if label not in shared_labels:
        raise HTTPException(400, f"Label '{label}' is not a shared node type")
    
    id_prop = get_id_property(label)
    user_id = get_user_id(request)
    
    # Get current node properties for change tracking
    get_query = f"""
        MATCH (n:{label} {{{id_prop}: $node_id}})
        RETURN n
    """
    current_result = neo4j_client.execute_query(get_query, {"node_id": node_id})
    if not current_result:
        raise HTTPException(404, "Node not found")
    
    old_props = dict(current_result[0]["n"])
    
    # Filter out protected properties
    protected_props = {id_prop, f"{label.lower()}_upload_code"}
    props_to_update = {
        k: v for k, v in body.properties.items() 
        if k not in protected_props and not k.endswith("_embedding")
    }
    
    if not props_to_update:
        raise HTTPException(400, "No properties to update")
    
    # Build SET clause
    set_clauses = ", ".join([f"n.{k} = ${k}" for k in props_to_update.keys()])
    
    query = f"""
        MATCH (n:{label} {{{id_prop}: $node_id}})
        SET {set_clauses}
        RETURN n
    """
    
    params = {"node_id": node_id, **props_to_update}
    results = neo4j_client.execute_query(query, params)
    
    if not results:
        raise HTTPException(404, "Node not found")
    
    new_props = dict(results[0]["n"])
    
    # Compute property changes
    property_changes = {}
    for key in props_to_update:
        if old_props.get(key) != new_props.get(key):
            property_changes[key] = {"old": old_props.get(key), "new": new_props.get(key)}
    
    # Log update events for each connected case
    cases_data = find_cases_containing_node(db, node_id, label)
    events_logged = 0
    
    with db.connection() as conn:
        for case in cases_data:
            try:
                graph_events_repo.log_node_event(
                    conn=conn,
                    case_id=case["case_id"],
                    node_temp_id=node_id,
                    node_label=label,
                    action="update",
                    user_id=user_id,
                    properties=new_props,
                    property_changes=property_changes if property_changes else None,
                )
                events_logged += 1
            except Exception as e:
                logger.error(f"Failed to log update event for case {case['case_id']}: {e}")
        conn.commit()
    
    logger.info(f"Updated shared node {label}:{node_id} by {user_id} ({events_logged} events logged)")
    
    return {
        "success": True,
        "node": {
            "label": label,
            "id": node_id,
            "properties": new_props,
        }
    }


class SetPresetRequest(BaseModel):
    preset: bool


@router.patch("/{label}/{node_id}/preset")
def set_node_preset(
    label: str,
    node_id: str,
    body: SetPresetRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Set or unset the preset flag on a shared node.
    
    Preset nodes are canonical, stable nodes defined by legal experts.
    They receive special treatment during deletion:
    - Preset nodes are never auto-deleted when orphaned (only admin can force-delete)
    - Non-preset nodes can be deleted when orphaned from any delete source
    """
    schema = load_schema()
    shared_labels = get_shared_labels(schema)
    
    if label not in shared_labels:
        raise HTTPException(400, f"Label '{label}' is not a shared node type")
    
    id_prop = get_id_property(label)
    user_id = get_user_id(request)
    
    # Check if node exists
    check_query = f"""
        MATCH (n:{label} {{{id_prop}: $node_id}})
        RETURN n
    """
    check_result = neo4j_client.execute_query(check_query, {"node_id": node_id})
    if not check_result:
        raise HTTPException(404, "Node not found")
    
    # Use the uploader to set the preset property
    uploader = Neo4jUploader(schema, neo4j_client)
    success = uploader.set_node_preset(label, node_id, body.preset)
    
    if not success:
        raise HTTPException(500, "Failed to update preset status")
    
    logger.info(f"Set preset={body.preset} for {label}:{node_id} by {user_id}")
    
    return {
        "success": True,
        "label": label,
        "nodeId": node_id,
        "preset": body.preset,
    }


class DeleteNodeRequest(BaseModel):
    force_partial: bool = False  # If true, delete from cases where min_per_case allows


@router.delete("/{label}/{node_id}")
def delete_shared_node(
    label: str, 
    node_id: str, 
    request: Request,
    force_partial: bool = Query(False),
    force_delete: bool = Query(False, description="Force deletion of preset orphaned nodes"),
    db: Session = Depends(get_db),
):
    """Delete a shared node from the Knowledge Graph.
    
    This will:
    1. Check min_per_case constraints for connected cases (via Postgres)
    2. If constraints violated and force_partial=False, return error with details
    3. If force_partial=True, delete only from cases where constraint allows
    4. For orphaned nodes:
       - Non-preset nodes: auto-delete from Neo4j
       - Preset nodes: preserve unless force_delete=True
    """
    schema = load_schema()
    shared_labels = get_shared_labels(schema)
    
    if label not in shared_labels:
        raise HTTPException(400, f"Label '{label}' is not a shared node type")
    
    # Use the same KG mutation primitives as KG submit / case delete flows
    uploader = Neo4jUploader(schema, neo4j_client)

    id_prop = get_id_property(label)
    min_per_case = get_min_per_case(schema, label)
    user_id = get_user_id(request)
    
    # Check if node exists in Neo4j and get its properties for logging
    check_query = f"""
        MATCH (n:{label} {{{id_prop}: $node_id}})
        RETURN n
    """
    check_result = neo4j_client.execute_query(check_query, {"node_id": node_id})
    if not check_result:
        raise HTTPException(404, "Node not found")
    
    node_props = dict(check_result[0]["n"])
    
    # Get connected cases from Postgres (authoritative source for case membership)
    cases_data = find_cases_containing_node(db, node_id, label)
    
    blocked_cases = []
    deletable_cases = []
    
    for case in cases_data:
        case_info = {
            "case_id": case["case_id"],
            "case_name": case["case_name"],
            "currentCount": case["labelCount"],
            "extracted": case["extracted"],  # Keep for detachment
            "kg_extracted": case.get("kg_extracted"),  # Keep published snapshot in sync when present
        }
        
        # If deleting this node would leave fewer than min_per_case
        if min_per_case > 0 and case["labelCount"] <= min_per_case:
            blocked_cases.append(case_info)
        else:
            deletable_cases.append(case_info)
    
    # If there are blocked cases and not forcing partial deletion
    if blocked_cases and not force_partial:
        return {
            "success": False,
            "error": "min_per_case_violation",
            "message": f"Cannot delete: {len(blocked_cases)} case(s) would have fewer than {min_per_case} {label} node(s)",
            "blockedCases": [{"case_id": c["case_id"], "case_name": c["case_name"], "currentCount": c["currentCount"]} for c in blocked_cases],
            "deletableCases": [{"case_id": c["case_id"], "case_name": c["case_name"], "currentCount": c["currentCount"]} for c in deletable_cases],
            "minPerCase": min_per_case,
        }
    
    # Perform deletion
    deleted_from_cases = []
    events_logged = 0
    
    if force_partial and blocked_cases:
        # Only detach from deletable cases, leave node connected to blocked cases
        with db.connection() as conn:
            for case in deletable_cases:
                try:
                    # Get node IDs from Postgres extracted data (no graph traversal!)
                    case_node_ids = get_case_node_ids(case["extracted"].get("nodes", []))

                    # Detach relationships between the shared node and nodes that belong to this case
                    deleted_count = uploader.detach_node_from_case(label, node_id, case_node_ids)
                    # Remove the node reference from Postgres extracted data (authoritative case membership)
                    updated_extracted, removed_nodes, removed_edges = remove_node_from_extracted(
                        case.get("extracted") or {},
                        label,
                        node_id,
                    )
                    if removed_nodes > 0 or removed_edges > 0:
                        # Persist updated extracted back to Postgres
                        case_repo.update_case(conn, case["case_id"], updated_extracted, user_id=user_id)

                        # Keep the last-published snapshot consistent (used for diffing / KG cleanup elsewhere).
                        # Only update if it exists; legacy/unpublished cases may have NULL kg_extracted.
                        current_kg_extracted = case.get("kg_extracted")
                        updated_kg_extracted, kg_removed_nodes, kg_removed_edges = remove_node_from_extracted(
                            current_kg_extracted or {},
                            label,
                            node_id,
                        )
                        if current_kg_extracted is not None and (kg_removed_nodes > 0 or kg_removed_edges > 0):
                            case_repo.set_kg_extracted(conn, case["case_id"], updated_kg_extracted)
                            # This admin action mutates the published graph; keep KG submission metadata aligned
                            # so `kg_diverged` (timestamp-based) doesn't incorrectly flag divergence.
                            case_repo.set_kg_submitted(conn, case["case_id"], user_id)
                    
                    # Log delete event for this case (node detached from case)
                    try:
                        graph_events_repo.log_node_event(
                            conn=conn,
                            case_id=case["case_id"],
                            node_temp_id=node_id,
                            node_label=label,
                            action="delete",
                            user_id=user_id,
                            properties=node_props,
                        )
                        events_logged += 1
                    except Exception as e:
                        logger.error(f"Failed to log delete event for case {case['case_id']}: {e}")
                    
                    deleted_from_cases.append({
                        "case_id": case["case_id"],
                        "case_name": case["case_name"],
                        "status": "detached",
                        "relationshipsRemoved": deleted_count,
                        "postgresNodesRemoved": removed_nodes,
                        "postgresEdgesRemoved": removed_edges,
                    })
                    logger.info(f"Detached {label}:{node_id} from case {case['case_id']} ({deleted_count} relationships)")
                except Exception as e:
                    logger.error(f"Failed to detach {label}:{node_id} from case {case['case_id']}: {e}")
                    deleted_from_cases.append({
                        "case_id": case["case_id"],
                        "case_name": case["case_name"],
                        "status": "failed",
                        "error": str(e),
                    })
            conn.commit()
        
        logger.info(f"Partial detachment of {label}:{node_id} by {user_id} ({events_logged} events logged)")
        
        return {
            "success": True,
            "partial": True,
            "message": f"Node remains connected to {len(blocked_cases)} case(s) due to min_per_case constraint",
            "deletedFromCases": deleted_from_cases,
            "remainingCases": [{"case_id": c["case_id"], "case_name": c["case_name"]} for c in blocked_cases],
        }
    
    # Check if this is a catalog node (can_create_new=false)
    node_def = next((n for n in schema if n.get("label") == label), {})
    is_catalog_node = node_def.get("can_create_new") is False
    
    all_cases = blocked_cases + deletable_cases

    # New deletion policy (shared nodes):
    # - If node is referenced by any cases, detach from all cases and PRESERVE the node in the KG.
    # - Only fully delete the node when it is orphaned (no case references).
    if len(all_cases) > 0:
        with db.connection() as conn:
            for case in all_cases:
                try:
                    # Get node IDs from Postgres extracted data
                    case_node_ids = get_case_node_ids(case["extracted"].get("nodes", []))

                    # Detach relationships between the shared node and nodes that belong to this case
                    deleted_count = uploader.detach_node_from_case(label, node_id, case_node_ids)
                    # Remove the node reference from Postgres extracted data (authoritative case membership)
                    updated_extracted, removed_nodes, removed_edges = remove_node_from_extracted(
                        case.get("extracted") or {},
                        label,
                        node_id,
                    )
                    if removed_nodes > 0 or removed_edges > 0:
                        case_repo.update_case(conn, case["case_id"], updated_extracted, user_id=user_id)

                        # Keep last-published snapshot consistent with out-of-band admin graph mutations.
                        current_kg_extracted = case.get("kg_extracted")
                        updated_kg_extracted, kg_removed_nodes, kg_removed_edges = remove_node_from_extracted(
                            current_kg_extracted or {},
                            label,
                            node_id,
                        )
                        if current_kg_extracted is not None and (kg_removed_nodes > 0 or kg_removed_edges > 0):
                            case_repo.set_kg_extracted(conn, case["case_id"], updated_kg_extracted)
                            case_repo.set_kg_submitted(conn, case["case_id"], user_id)
                    
                    # Log delete event for this case (node detached from case)
                    try:
                        graph_events_repo.log_node_event(
                            conn=conn,
                            case_id=case["case_id"],
                            node_temp_id=node_id,
                            node_label=label,
                            action="delete",
                            user_id=user_id,
                            properties=node_props,
                        )
                        events_logged += 1
                    except Exception as e:
                        logger.error(f"Failed to log delete event for case {case['case_id']}: {e}")
                    
                    deleted_from_cases.append({
                        "case_id": case["case_id"],
                        "case_name": case["case_name"],
                        "status": "detached",
                        "relationshipsRemoved": deleted_count,
                        "postgresNodesRemoved": removed_nodes,
                        "postgresEdgesRemoved": removed_edges,
                    })
                    logger.info(f"Detached {label}:{node_id} from case {case['case_id']} ({deleted_count} relationships)")
                except Exception as e:
                    logger.error(f"Failed to detach {label}:{node_id} from case {case['case_id']}: {e}")
                    deleted_from_cases.append({
                        "case_id": case["case_id"],
                        "case_name": case["case_name"],
                        "status": "failed",
                        "error": str(e),
                    })
            conn.commit()
        
        logger.info(f"Detached shared node {label}:{node_id} from {len(all_cases)} case(s) by {user_id} (node preserved in KG, {events_logged} events logged)")

        resp = {
            "success": True,
            "partial": False,
            "nodePreserved": True,
            "message": "Node detached from all cases but preserved in Knowledge Graph",
            "deletedFromCases": deleted_from_cases,
        }
        # Back-compat: keep catalogNodePreserved for catalog node detachment
        if is_catalog_node:
            resp["catalogNodePreserved"] = True
        return resp
    
    # Orphaned node deletion logic
    # Check if node is preset (canonical node defined by legal experts)
    is_preset = node_props.get("preset") is True
    
    if is_preset and not force_delete:
        # Preset orphaned nodes are preserved unless force_delete=True
        logger.info(f"Preserved preset orphaned node {label}:{node_id} (force_delete=False)")
        return {
            "success": True,
            "partial": False,
            "nodePreserved": True,
            "isPreset": True,
            "message": "Preset node preserved in Knowledge Graph (use force_delete=true to permanently delete)",
            "deletedFromCases": [],
        }
    
    # Full deletion - delete the node and all its relationships
    # This is for non-preset orphaned nodes OR preset nodes with force_delete=True
    uploader.delete_node(label, node_id)
    
    # Log delete events for all affected cases (if any)
    if len(all_cases) > 0:
        with db.connection() as conn:
            for case in all_cases:
                try:
                    graph_events_repo.log_node_event(
                        conn=conn,
                        case_id=case["case_id"],
                        node_temp_id=node_id,
                        node_label=label,
                        action="delete",
                        user_id=user_id,
                        properties=node_props,
                    )
                    events_logged += 1
                except Exception as e:
                    logger.error(f"Failed to log delete event for case {case['case_id']}: {e}")
            conn.commit()
    
    node_type = "preset" if is_preset else ("catalog" if is_catalog_node else "shared")
    logger.info(f"Deleted orphaned {node_type} node {label}:{node_id} by {user_id} ({events_logged} events logged)")
    
    return {
        "success": True,
        "partial": False,
        "message": f"Node deleted successfully from Knowledge Graph",
        "deletedFromCases": [
            {"case_id": c["case_id"], "case_name": c["case_name"], "status": "deleted"}
            for c in all_cases
        ] if len(all_cases) > 0 else [],
    }
