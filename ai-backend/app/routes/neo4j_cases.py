"""Admin endpoints for reading Neo4j case data directly (bypasses Postgres).

These routes are protected by the same X-API-Key mechanism used elsewhere in the backend.
They are intended to be called via Next.js admin proxy routes (so Neo4j credentials never
reach the browser).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from app.lib.neo4j_client import neo4j_client
from app.lib.security import get_api_key


router = APIRouter(prefix="/neo4j-cases", dependencies=[Depends(get_api_key)])

def _load_schema_v3() -> List[Dict[str, Any]]:
    schema_path = os.path.join(os.path.dirname(__file__), "..", "..", "schema_v3.json")
    with open(schema_path, "r") as f:
        return json.load(f)


def _get_relationship_types_from_schema(schema: List[Dict[str, Any]]) -> List[str]:
    """Return all relationship type names defined in schema_v3.json."""
    rel_types = set()
    for node_def in schema or []:
        if not isinstance(node_def, dict):
            continue
        rels = node_def.get("relationships") or {}
        if not isinstance(rels, dict):
            continue
        for rel_type in rels.keys():
            if isinstance(rel_type, str) and rel_type:
                rel_types.add(rel_type)
    return sorted(rel_types)

def _strip_embedding_properties(value: Any) -> Any:
    """Remove any properties whose key ends with '_embedding' from dicts (recursively)."""
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and k.endswith("_embedding"):
                continue
            cleaned[k] = _strip_embedding_properties(v)
        return cleaned
    if isinstance(value, list):
        return [_strip_embedding_properties(v) for v in value]
    return value

def _load_case_graph_cypher() -> str:
    cypher_path = os.path.join(os.path.dirname(__file__), "..", "cypher", "case_graph.cypher")
    with open(cypher_path, "r") as f:
        return f.read()

def _escape_cypher_string_literal(s: str) -> str:
    # Cypher strings use single quotes; escape backslash and single-quote.
    return s.replace("\\", "\\\\").replace("'", "\\'")

def _split_node_properties(obj: Dict[str, Any], reserved_keys: List[str]) -> Dict[str, Any]:
    """Return a copy of obj without reserved_keys."""
    out: Dict[str, Any] = {}
    for k, v in (obj or {}).items():
        if k in reserved_keys:
            continue
        out[k] = v
    return out

def _case_data_to_extracted(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the nested Neo4j `case_data` structure to extracted-style {nodes, edges}.

    This allows us to reuse the existing CaseViewBuilder (views_v3.json) and the frontend
    case viewer components that expect nodes/edges with temp_id/label/properties.
    """
    from app.lib.neo4j_uploader import get_id_prop_for_label

    schema = _load_schema_v3()

    nodes_by_id: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    def add_node(label: str, props: Dict[str, Any]) -> str:
        if not isinstance(props, dict):
            raise ValueError(f"Invalid props for {label}")
        id_prop = get_id_prop_for_label(label, schema)
        node_id = props.get(id_prop)
        if not node_id:
            # Fallback: any *_id
            for k, v in props.items():
                if isinstance(k, str) and k.endswith("_id") and v:
                    node_id = v
                    break
        if not node_id:
            raise ValueError(f"Missing id for label={label} (expected {id_prop})")
        tid = str(node_id)
        if tid not in nodes_by_id:
            nodes_by_id[tid] = {
                "temp_id": tid,
                "label": label,
                "properties": props,
            }
        return tid

    def add_edge(frm: str, to: str, label: str, properties: Dict[str, Any] | None = None):
        if not frm or not to:
            return
        e: Dict[str, Any] = {"from": frm, "to": to, "label": label}
        if properties is not None:
            e["properties"] = properties
        edges.append(e)

    # Case (top-level)
    c_props = _split_node_properties(case_data, ["domain", "proceedings"])
    case_id = add_node("Case", c_props)

    # Domain
    domain = case_data.get("domain")
    if isinstance(domain, dict):
        d_id = add_node("Domain", domain)
        add_edge(d_id, case_id, "CONTAINS")

    # Proceedings and nested structures
    proceedings = case_data.get("proceedings") or []
    if not isinstance(proceedings, list):
        proceedings = []

    for proc in proceedings:
        if not isinstance(proc, dict):
            continue

        p_props = _split_node_properties(proc, ["forum", "jurisdiction", "parties", "issues", "rulings"])
        p_id = add_node("Proceeding", p_props)
        add_edge(case_id, p_id, "HAS_PROCEEDING")

        forum = proc.get("forum")
        if isinstance(forum, dict):
            f_id = add_node("Forum", forum)
            add_edge(p_id, f_id, "HEARD_IN")
            jurisdiction = proc.get("jurisdiction")
            if isinstance(jurisdiction, dict):
                j_id = add_node("Jurisdiction", jurisdiction)
                add_edge(f_id, j_id, "PART_OF")

        # Parties (edge property role)
        parties = proc.get("parties") or []
        if isinstance(parties, list):
            for item in parties:
                if not isinstance(item, dict):
                    continue
                party_props = item.get("party")
                if not isinstance(party_props, dict):
                    continue
                party_id = add_node("Party", party_props)
                role = item.get("role")
                edge_props = {"role": role} if role is not None else {}
                add_edge(p_id, party_id, "INVOLVES", edge_props)

        # Issues
        issues = proc.get("issues") or []
        if isinstance(issues, list):
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                i_props = _split_node_properties(issue, ["doctrines", "policies", "fact_patterns"])
                i_id = add_node("Issue", i_props)
                add_edge(p_id, i_id, "ADDRESSES")

                doctrines = issue.get("doctrines") or []
                if isinstance(doctrines, list):
                    for doc in doctrines:
                        if isinstance(doc, dict):
                            d = add_node("Doctrine", doc)
                            add_edge(i_id, d, "RELATES_TO_DOCTRINE")
                policies = issue.get("policies") or []
                if isinstance(policies, list):
                    for po in policies:
                        if isinstance(po, dict):
                            pn = add_node("Policy", po)
                            add_edge(i_id, pn, "RELATES_TO_POLICY")
                fps = issue.get("fact_patterns") or []
                if isinstance(fps, list):
                    for fp in fps:
                        if isinstance(fp, dict):
                            fpn = add_node("FactPattern", fp)
                            add_edge(i_id, fpn, "RELATES_TO_FACTPATTERN")

        # Rulings
        rulings = proc.get("rulings") or []
        if isinstance(rulings, list):
            for ruling in rulings:
                if not isinstance(ruling, dict):
                    continue
                r_props = _split_node_properties(ruling, ["sets_issue", "reliefs", "laws", "arguments"])
                r_id = add_node("Ruling", r_props)
                add_edge(p_id, r_id, "RESULTS_IN")

                sets_issue = ruling.get("sets_issue")
                if isinstance(sets_issue, dict):
                    in_favor = sets_issue.get("in_favor")
                    si_props = dict(sets_issue)
                    si_props.pop("in_favor", None)
                    i_id = add_node("Issue", si_props)
                    edge_props = {"in_favor": in_favor} if in_favor is not None else {}
                    add_edge(r_id, i_id, "SETS", edge_props)

                reliefs = ruling.get("reliefs") or []
                if isinstance(reliefs, list):
                    for rel in reliefs:
                        if not isinstance(rel, dict):
                            continue
                        relief_status = rel.get("relief_status")
                        rt = rel.get("relief_type")
                        rel_props = dict(rel)
                        rel_props.pop("relief_status", None)
                        rel_props.pop("relief_type", None)
                        rel_id = add_node("Relief", rel_props)
                        edge_props = {"relief_status": relief_status} if relief_status is not None else {}
                        add_edge(r_id, rel_id, "RESULTS_IN", edge_props)
                        if isinstance(rt, dict):
                            rt_id = add_node("ReliefType", rt)
                            add_edge(rel_id, rt_id, "IS_TYPE")

                laws = ruling.get("laws") or []
                if isinstance(laws, list):
                    for law in laws:
                        if isinstance(law, dict):
                            l_id = add_node("Law", law)
                            add_edge(r_id, l_id, "RELIES_ON_LAW")

                arguments = ruling.get("arguments") or []
                if isinstance(arguments, list):
                    for a in arguments:
                        if not isinstance(a, dict):
                            continue
                        status = a.get("status")
                        a_props = _split_node_properties(a, ["status", "doctrines", "policies", "fact_patterns"])
                        a_id = add_node("Argument", a_props)
                        edge_props = {"status": status} if status is not None else {}
                        add_edge(a_id, r_id, "EVALUATED_IN", edge_props)

                        doctrines = a.get("doctrines") or []
                        if isinstance(doctrines, list):
                            for doc in doctrines:
                                if isinstance(doc, dict):
                                    d = add_node("Doctrine", doc)
                                    add_edge(a_id, d, "RELATES_TO_DOCTRINE")
                        policies = a.get("policies") or []
                        if isinstance(policies, list):
                            for po in policies:
                                if isinstance(po, dict):
                                    pn = add_node("Policy", po)
                                    add_edge(a_id, pn, "RELATES_TO_POLICY")
                        fps = a.get("fact_patterns") or []
                        if isinstance(fps, list):
                            for fp in fps:
                                if isinstance(fp, dict):
                                    fpn = add_node("FactPattern", fp)
                                    add_edge(a_id, fpn, "RELATES_TO_FACTPATTERN")

    extracted = {"nodes": list(nodes_by_id.values()), "edges": edges}
    return extracted


@router.get("")
def list_neo4j_cases(
    q: str = Query("", description="Optional search string (name/citation/case_id)"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List cases from Neo4j (authoritative KG source)."""
    cypher = """
    MATCH (c:Case)
    WHERE $q = ''
      OR toLower(coalesce(c.name, '')) CONTAINS toLower($q)
      OR toLower(coalesce(c.citation, '')) CONTAINS toLower($q)
      OR toLower(coalesce(c.case_id, '')) CONTAINS toLower($q)
    RETURN
      c.case_id AS case_id,
      c.name AS name,
      c.citation AS citation
    ORDER BY coalesce(c.name, c.citation, c.case_id)
    SKIP $offset
    LIMIT $limit
    """

    rows = neo4j_client.execute_query(cypher, {"q": q or "", "offset": offset, "limit": limit})

    cases: List[Dict[str, Any]] = []
    for r in rows or []:
        case_id = r.get("case_id") or ""
        name = r.get("name") or r.get("citation") or case_id
        cases.append(
            {
                "case_id": case_id,
                "name": name,
                "citation": r.get("citation"),
            }
        )

    return {"success": True, "cases": cases, "limit": limit, "offset": offset, "q": q or ""}


@router.get("/{case_id}/graph")
def get_case_graph_from_neo4j(
    case_id: str,
):
    """Fetch the Neo4j subgraph for a case (nodes + relationships).

    Important: This is intentionally *Neo4j-native* shape, not the Postgres extracted/edited shape.
    We also prevent traversal through other Case nodes to avoid pulling in neighboring cases via
    shared nodes like Domain.
    """
    if not case_id:
        raise HTTPException(status_code=400, detail="case_id is required")

    # Use a static, schema-aligned query for performance and predictable shape.
    # Per request: replace $caseId directly in the Cypher (rather than sending parameters).
    template = _load_case_graph_cypher()
    case_literal = f"'{_escape_cypher_string_literal(case_id)}'"
    cypher = template.replace("$caseId", case_literal)

    rows = neo4j_client.execute_query(cypher, {})
    if not rows:
        raise HTTPException(status_code=404, detail="Case not found in Neo4j")

    # We return a single record with key `case_data`
    row = rows[0]
    case_data = row.get("case_data")
    if not case_data:
        raise HTTPException(status_code=404, detail="Case not found in Neo4j")

    return {
        "success": True,
        "case_id": case_id,
        # Embeddings are removed in Cypher; keep scrubber as defense-in-depth.
        "case_data": _strip_embedding_properties(case_data),
    }


@router.get("/{case_id}/view")
def get_case_view_from_neo4j(case_id: str, view: str = "holdingsCentric"):
    """Return a Neo4j-backed case in the same {nodes,edges}+displayData shape as Postgres cases."""
    if not case_id:
        raise HTTPException(status_code=400, detail="case_id is required")

    template = _load_case_graph_cypher()
    case_literal = f"'{_escape_cypher_string_literal(case_id)}'"
    cypher = template.replace("$caseId", case_literal)
    rows = neo4j_client.execute_query(cypher, {})
    if not rows:
        raise HTTPException(status_code=404, detail="Case not found in Neo4j")
    row = rows[0]
    case_data = row.get("case_data")
    if not case_data:
        raise HTTPException(status_code=404, detail="Case not found in Neo4j")

    case_data = _strip_embedding_properties(case_data)
    extracted = _case_data_to_extracted(case_data)

    try:
        from app.lib.case_view_builder import build_case_display_view, load_views_config
        from app.lib.property_filter import filter_case_data, filter_display_data

        extracted_filtered = filter_case_data(extracted)
        structured = build_case_display_view(extracted_filtered, view)
        views_config = load_views_config()
        view_config = views_config.get(view, {})
        filtered_structured = filter_display_data(structured)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build Neo4j view: {e}")

    return {
        "success": True,
        "case_id": case_id,
        "view": view,
        "viewConfig": view_config,
        "extracted": extracted_filtered,
        "data": filtered_structured,
    }


