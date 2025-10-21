from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Tuple

from crewai.flow.flow import Flow, start, listen

from app.lib.logging_config import setup_logger
from app.lib.schema_runtime import (
    derive_embedding_config_from_schema,
    load_schema_payload,
)
from app.lib.embeddings import generate_embedding_sync
from pydantic import BaseModel


logger = setup_logger("flow-kg")


def is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except Exception:
        return False


def to_snake_case(label: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", label).lower()


def get_id_prop_for_label(label: str, schema_payload: Any) -> str:
    """Return the *_id property name for a label based on schema.json.

    Preference order:
      1) <snake_label>_id if present in schema
      2) first property in schema that endswith("_id")
      3) fallback to <snake_label>_id
    """
    snake = to_snake_case(label)
    preferred = f"{snake}_id"

    if isinstance(schema_payload, list):
        for node_def in schema_payload:
            if not isinstance(node_def, dict):
                continue
            if node_def.get("label") != label:
                continue
            props = node_def.get("properties") or {}
            if isinstance(props, dict):
                # exact preferred
                if preferred in props:
                    return preferred
                # any *_id
                for pname in props.keys():
                    if isinstance(pname, str) and pname.endswith("_id"):
                        return pname
    return preferred


class KGState(BaseModel):
    payload: Dict[str, Any] = {}
    schema_payload: Any | None = None
    embedding_config: Dict[str, List[str]] = {}
    original_input: Dict[str, Any] = {}  # Store original input for validation
    id_mapping: Dict[str, str] = {}  # Store temp_id -> uuid mapping for validation


class KGFlow(Flow[KGState]):
    """Transform a CaseGraph-like payload: normalize IDs, assign *_id props from schema,
    generate embeddings for configured properties, and log the result.
    """

    @start()
    def start_flow(self) -> Dict[str, Any]:
        # Expect self.state.payload to already contain the CaseGraph-like dict
        data = self.state.payload or {}
        logger.info("KGFlow kickoff: received payload with %d nodes, %d edges",
                    len(data.get("nodes", []) if isinstance(data.get("nodes"), list) else []),
                    len(data.get("edges", []) if isinstance(data.get("edges"), list) else []))
        # Store original input for validation
        import copy
        self.state.original_input = copy.deepcopy(data)
        # Load schema and embedding config once
        try:
            self.state.schema_payload = load_schema_payload()
        except Exception as e:
            logger.warning(f"KGFlow: failed to load schema.json: {e}")
            self.state.schema_payload = []
        try:
            self.state.embedding_config = derive_embedding_config_from_schema()
        except Exception as e:
            logger.warning(f"KGFlow: failed to derive embedding config: {e}")
            self.state.embedding_config = {}
        return data

    @listen(start_flow)
    def normalize_ids(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(ctx or {})
        nodes = list(data.get("nodes") or [])
        edges = list(data.get("edges") or [])

        # Build map temp_id -> uuid (reuse if already uuid)
        id_map: Dict[str, str] = {}
        for n in nodes:
            if not isinstance(n, dict):
                continue
            raw_tid = n.get("temp_id")
            if not isinstance(raw_tid, str) or not raw_tid:
                uid = str(uuid.uuid4())
            else:
                uid = raw_tid if is_uuid(raw_tid) else str(uuid.uuid4())
            id_map[raw_tid] = uid
        
        # Store mapping for validation
        self.state.id_mapping = id_map

        # Update edges
        for e in edges:
            if not isinstance(e, dict):
                continue
            frm = e.get("from")
            to = e.get("to")
            if isinstance(frm, str) and frm in id_map:
                e["from"] = id_map[frm]
            if isinstance(to, str) and to in id_map:
                e["to"] = id_map[to]

        # Replace temp_id with schema-driven *_id on nodes
        schema_payload = self.state.schema_payload
        for n in nodes:
            if not isinstance(n, dict):
                continue
            label = n.get("label")
            tid = n.get("temp_id")
            props = dict(n.get("properties") or {})
            if isinstance(label, str):
                id_prop = get_id_prop_for_label(label, schema_payload)
            else:
                id_prop = "id"
            mapped_uuid = id_map.get(tid)
            if mapped_uuid:
                props[id_prop] = mapped_uuid
            n["properties"] = props
            # remove temp_id from node object as requested
            if "temp_id" in n:
                n.pop("temp_id", None)

        data["nodes"] = nodes
        data["edges"] = edges
        self.state.payload = data
        return data

    @listen(normalize_ids)
    def compute_embeddings(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(ctx or {})
        nodes = list(data.get("nodes") or [])
        cfg = self.state.embedding_config or {}

        for n in nodes:
            if not isinstance(n, dict):
                continue
            label = n.get("label")
            if not isinstance(label, str):
                continue
            props = dict(n.get("properties") or {})
            targets = cfg.get(label, [])
            if not isinstance(targets, list) or not targets:
                n["properties"] = props
                continue
            for prop_name in targets:
                try:
                    raw_val = props.get(prop_name)
                    if isinstance(raw_val, str):
                        text = raw_val.strip()
                    else:
                        text = ""
                    if not text:
                        continue
                    vec = generate_embedding_sync(text)
                    props[f"{prop_name}_embedding"] = vec
                except Exception as e:
                    logger.warning(f"KGFlow: embedding failed for {label}.{prop_name}: {e}")
                    continue
            n["properties"] = props

        data["nodes"] = nodes
        self.state.payload = data
        return data

    @listen(compute_embeddings)
    def finish(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(ctx or {})
        # Log structure/schema of the result instead of full data
        structure = self._extract_structure(data)
        try:
            logger.info("KGFlow result structure: %s", json.dumps(structure, indent=2, ensure_ascii=False))
        except Exception:
            logger.info("KGFlow result structure (non-JSON-serializable): %s", str(structure))
        return data

    @listen(finish)
    def validate_output(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Validate the transformed output meets all requirements."""
        output_data = dict(ctx or {})
        input_data = self.state.original_input
        id_mapping = self.state.id_mapping
        schema_payload = self.state.schema_payload
        embedding_config = self.state.embedding_config
        
        issues = []
        stats = {
            "total_nodes": 0,
            "total_edges": 0,
            "uuids_preserved": 0,
            "embeddings_by_label": {},
        }
        
        # First run transformation validation, then schema validation
        issues = self._validate_transformation(output_data, input_data, id_mapping, schema_payload, embedding_config, issues, stats)
        
        # Then validate against schema
        schema_issues = self._validate_against_schema(output_data, schema_payload)
        
        return output_data

    def _validate_transformation(self, output_data, input_data, id_mapping, schema_payload, embedding_config, issues, stats):
        
        # Check 1: Data structure
        if not isinstance(output_data.get("nodes"), list):
            issues.append("Output missing 'nodes' array")
        if not isinstance(output_data.get("edges"), list):
            issues.append("Output missing 'edges' array")
        
        output_nodes = output_data.get("nodes", [])
        output_edges = output_data.get("edges", [])
        input_nodes = input_data.get("nodes", [])
        input_edges = input_data.get("edges", [])
        
        stats["total_nodes"] = len(output_nodes)
        stats["total_edges"] = len(output_edges)
        
        # Check 2: temp_id removal
        for i, node in enumerate(output_nodes):
            if not isinstance(node, dict):
                continue
            if "temp_id" in node:
                issues.append(f"Node {i} still has temp_id property")
        
        # Build output node id lookup for edge validation
        output_node_ids = set()
        
        # Check 3, 4: UUID assignment and preservation
        for i, node in enumerate(output_nodes):
            if not isinstance(node, dict):
                continue
            
            label = node.get("label", "")
            props = node.get("properties", {})
            
            # Find the *_id property for this label
            id_prop = get_id_prop_for_label(label, schema_payload)
            node_id = props.get(id_prop) if isinstance(props, dict) else None
            
            if not node_id:
                issues.append(f"Node {i} ({label}) missing {id_prop} property")
                continue
            
            if not is_uuid(str(node_id)):
                issues.append(f"Node {i} ({label}) {id_prop}='{node_id}' is not a valid UUID")
            else:
                output_node_ids.add(str(node_id))
            
            # Check UUID preservation: find matching input node
            if i < len(input_nodes):
                input_node = input_nodes[i]
                if isinstance(input_node, dict):
                    input_temp_id = input_node.get("temp_id")
                    if input_temp_id and is_uuid(input_temp_id):
                        # Input had a UUID, verify it was preserved
                        expected_uuid = id_mapping.get(input_temp_id, input_temp_id)
                        if str(node_id) == expected_uuid:
                            stats["uuids_preserved"] += 1
                        else:
                            issues.append(f"Node {i}: UUID not preserved (input={input_temp_id}, output={node_id})")
        
        # Check 5: Embeddings count
        for node in output_nodes:
            if not isinstance(node, dict):
                continue
            label = node.get("label", "")
            props = node.get("properties", {})
            if not isinstance(props, dict):
                continue
            
            # Count embedding properties
            embedding_count = sum(1 for k in props.keys() if k.endswith("_embedding"))
            if label not in stats["embeddings_by_label"]:
                stats["embeddings_by_label"][label] = {"expected": 0, "actual": embedding_count}
            else:
                stats["embeddings_by_label"][label]["actual"] = embedding_count
            
            # Check against expected count from config
            expected_fields = embedding_config.get(label, [])
            stats["embeddings_by_label"][label]["expected"] = len(expected_fields)
            
            if embedding_count != len(expected_fields):
                issues.append(f"Node {label}: expected {len(expected_fields)} embeddings, found {embedding_count}")
        
        # Check 6: Edge integrity
        if len(output_edges) != len(input_edges):
            issues.append(f"Edge count mismatch: input={len(input_edges)}, output={len(output_edges)}")
        
        for i, edge in enumerate(output_edges):
            if not isinstance(edge, dict):
                continue
            
            frm = edge.get("from")
            to = edge.get("to")
            
            if not frm or not is_uuid(str(frm)):
                issues.append(f"Edge {i}: 'from' is not a valid UUID: {frm}")
            elif str(frm) not in output_node_ids:
                issues.append(f"Edge {i}: 'from' UUID {frm} not found in output nodes")
            
            if not to or not is_uuid(str(to)):
                issues.append(f"Edge {i}: 'to' is not a valid UUID: {to}")
            elif str(to) not in output_node_ids:
                issues.append(f"Edge {i}: 'to' UUID {to} not found in output nodes")
            
            # Verify edge mapping is correct
            if i < len(input_edges):
                input_edge = input_edges[i]
                if isinstance(input_edge, dict):
                    input_from = input_edge.get("from")
                    input_to = input_edge.get("to")
                    
                    expected_from = id_mapping.get(input_from, input_from)
                    expected_to = id_mapping.get(input_to, input_to)
                    
                    if str(frm) != expected_from:
                        issues.append(f"Edge {i}: 'from' mapping incorrect (expected {expected_from}, got {frm})")
                    if str(to) != expected_to:
                        issues.append(f"Edge {i}: 'to' mapping incorrect (expected {expected_to}, got {to})")
        
        # Check 7: Property preservation
        for i, (input_node, output_node) in enumerate(zip(input_nodes, output_nodes)):
            if not isinstance(input_node, dict) or not isinstance(output_node, dict):
                continue
            
            input_props = input_node.get("properties", {})
            output_props = output_node.get("properties", {})
            
            if not isinstance(input_props, dict) or not isinstance(output_props, dict):
                continue
            
            # Check all input properties (except temp_id related) exist in output
            for prop_key in input_props.keys():
                if prop_key not in output_props:
                    issues.append(f"Node {i}: property '{prop_key}' missing in output")
        
        # Check edge property preservation
        for i, (input_edge, output_edge) in enumerate(zip(input_edges, output_edges)):
            if not isinstance(input_edge, dict) or not isinstance(output_edge, dict):
                continue
            
            input_props = input_edge.get("properties", {})
            output_props = output_edge.get("properties", {})
            
            if not isinstance(input_props, dict) or not isinstance(output_props, dict):
                continue
            
            for prop_key in input_props.keys():
                if prop_key not in output_props:
                    issues.append(f"Edge {i}: property '{prop_key}' missing in output")
        
        # Log transformation validation results
        if issues:
            logger.warning(f"KGFlow transformation validation found {len(issues)} issues:")
            for issue in issues[:10]:  # Log first 10 issues
                logger.warning(f"  - {issue}")
            if len(issues) > 10:
                logger.warning(f"  ... and {len(issues) - 10} more issues")
        else:
            logger.info("KGFlow transformation validation: All checks passed ✓")
        
        # Log statistics
        logger.info(f"Validation stats: {stats['total_nodes']} nodes, {stats['total_edges']} edges, {stats['uuids_preserved']} UUIDs preserved")
        if stats["embeddings_by_label"]:
            logger.info(f"Embeddings by label: {json.dumps(stats['embeddings_by_label'])}")
        
        return issues

    def _extract_structure(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract the schema/structure of the data: node labels with their properties, edge labels with their properties."""
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        
        # Group nodes by label and collect their property keys
        node_structure = {}
        for node in nodes:
            if not isinstance(node, dict):
                continue
            label = node.get("label", "Unknown")
            props = node.get("properties", {})
            if not isinstance(props, dict):
                continue
            
            if label not in node_structure:
                node_structure[label] = {
                    "count": 0,
                    "properties": set()
                }
            
            node_structure[label]["count"] += 1
            node_structure[label]["properties"].update(props.keys())
        
        # Convert sets to sorted lists for JSON serialization
        for label in node_structure:
            node_structure[label]["properties"] = sorted(list(node_structure[label]["properties"]))
        
        # Group edges by label and collect their property keys
        edge_structure = {}
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            label = edge.get("label", "Unknown")
            props = edge.get("properties", {})
            if not isinstance(props, dict):
                continue
            
            if label not in edge_structure:
                edge_structure[label] = {
                    "count": 0,
                    "properties": set()
                }
            
            edge_structure[label]["count"] += 1
            edge_structure[label]["properties"].update(props.keys())
        
        # Convert sets to sorted lists for JSON serialization
        for label in edge_structure:
            edge_structure[label]["properties"] = sorted(list(edge_structure[label]["properties"]))
        
        return {
            "nodes": node_structure,
            "edges": edge_structure,
            "total_nodes": len(nodes),
            "total_edges": len(edges)
        }


    def _validate_against_schema(self, data: Dict[str, Any], schema_payload: Any) -> List[str]:
        """Validate the output data against schema.json definitions."""
        issues = []
        
        if not isinstance(schema_payload, list):
            logger.warning("Schema payload is not a list, skipping schema validation")
            return issues
        
        # Build schema lookup by label
        schema_by_label = {}
        for schema_def in schema_payload:
            if isinstance(schema_def, dict) and "label" in schema_def:
                schema_by_label[schema_def["label"]] = schema_def
        
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        
        # Validate nodes against schema
        for i, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            
            label = node.get("label")
            if not label:
                issues.append(f"Node {i}: missing label")
                continue
            
            schema_def = schema_by_label.get(label)
            if not schema_def:
                issues.append(f"Node {i}: label '{label}' not found in schema")
                continue
            
            props = node.get("properties", {})
            if not isinstance(props, dict):
                continue
            
            schema_props = schema_def.get("properties", {})
            if not isinstance(schema_props, dict):
                continue
            
            # Check for required properties
            for prop_name, prop_def in schema_props.items():
                if not isinstance(prop_def, dict):
                    continue
                
                ui_config = prop_def.get("ui", {})
                is_required = ui_config.get("required", False)
                is_hidden = ui_config.get("hidden", False)
                
                # Skip validation for hidden fields (like embeddings and upload codes)
                if is_hidden:
                    continue
                
                if is_required and prop_name not in props:
                    issues.append(f"Node {i} ({label}): missing required property '{prop_name}'")
                elif is_required and prop_name in props:
                    value = props[prop_name]
                    if value is None or (isinstance(value, str) and not value.strip()):
                        issues.append(f"Node {i} ({label}): required property '{prop_name}' has no value")
            
            # Check for extra properties not in schema
            for prop_name in props.keys():
                if prop_name not in schema_props:
                    issues.append(f"Node {i} ({label}): extra property '{prop_name}' not in schema")
            
            # Type validation (basic)
            for prop_name, value in props.items():
                if prop_name not in schema_props:
                    continue
                
                prop_def = schema_props[prop_name]
                if not isinstance(prop_def, dict):
                    continue
                
                expected_type = prop_def.get("type")
                if expected_type == "STRING" and value is not None and not isinstance(value, str):
                    issues.append(f"Node {i} ({label}).{prop_name}: expected STRING, got {type(value).__name__}")
                elif expected_type == "FLOAT" and value is not None and not isinstance(value, (int, float)):
                    issues.append(f"Node {i} ({label}).{prop_name}: expected FLOAT, got {type(value).__name__}")
                elif expected_type == "DATE" and value is not None and isinstance(value, str):
                    # Validate date format YYYY-MM-DD
                    import re
                    if not re.match(r'^\d{4}-\d{2}-\d{2}$', value):
                        issues.append(f"Node {i} ({label}).{prop_name}: invalid DATE format (expected YYYY-MM-DD), got '{value}'")
                elif expected_type == "LIST" and value is not None and not isinstance(value, list):
                    issues.append(f"Node {i} ({label}).{prop_name}: expected LIST, got {type(value).__name__}")
        
        # Validate edges against schema relationships
        for i, edge in enumerate(edges):
            if not isinstance(edge, dict):
                continue
            
            edge_label = edge.get("label")
            if not edge_label:
                issues.append(f"Edge {i}: missing label")
                continue
            
            # Find which node type(s) can have this relationship
            found_in_schema = False
            expected_props = {}
            
            for schema_def in schema_payload:
                if not isinstance(schema_def, dict):
                    continue
                relationships = schema_def.get("relationships", {})
                if isinstance(relationships, dict) and edge_label in relationships:
                    found_in_schema = True
                    rel_def = relationships[edge_label]
                    if isinstance(rel_def, dict):
                        expected_props = rel_def.get("properties", {})
                    break
            
            if not found_in_schema:
                issues.append(f"Edge {i}: relationship type '{edge_label}' not found in schema")
                continue
            
            edge_props = edge.get("properties", {})
            if not isinstance(edge_props, dict):
                continue
            
            # Check for required edge properties
            if isinstance(expected_props, dict):
                for prop_name, prop_def in expected_props.items():
                    if not isinstance(prop_def, dict):
                        continue
                    
                    ui_config = prop_def.get("ui", {})
                    is_required = ui_config.get("required", False)
                    
                    if is_required and prop_name not in edge_props:
                        issues.append(f"Edge {i} ({edge_label}): missing required property '{prop_name}'")
                    elif is_required and prop_name in edge_props:
                        value = edge_props[prop_name]
                        if value is None or (isinstance(value, str) and not value.strip()):
                            issues.append(f"Edge {i} ({edge_label}): required property '{prop_name}' has no value")
                
                # Check for extra edge properties
                for prop_name in edge_props.keys():
                    if prop_name not in expected_props:
                        issues.append(f"Edge {i} ({edge_label}): extra property '{prop_name}' not in schema")
        
        # Log schema validation results
        if issues:
            logger.warning(f"KGFlow schema validation found {len(issues)} issues:")
            for issue in issues[:20]:  # Log first 20 issues
                logger.warning(f"  - {issue}")
            if len(issues) > 20:
                logger.warning(f"  ... and {len(issues) - 20} more issues")
        else:
            logger.info("KGFlow schema validation: All checks passed ✓")
        
        return issues


def create_flow() -> KGFlow:
    return KGFlow()


