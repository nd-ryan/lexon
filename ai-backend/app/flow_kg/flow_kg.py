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
from app.lib.property_filter import CATALOG_ONLY_NODES
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
    """Return the *_id property name for a label based on schema_v3.json.

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
    catalog_node_references: Dict[str, str] = {}  # Store original catalog node IDs referenced in edges: edge_ref -> expected_uuid
    nodes_needing_embeddings: set = set()  # Set of node UUIDs that need embedding generation


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
        # Log ReliefType.relief_type_id from input data
        nodes = data.get("nodes", [])
        for i, node in enumerate(nodes):
            if isinstance(node, dict) and node.get("label") == "ReliefType":
                props = node.get("properties", {})
                if isinstance(props, dict):
                    relief_type_id = props.get("relief_type_id")
                    logger.info("KGFlow input: ReliefType node %d has relief_type_id=%s", i, relief_type_id)
        # Store original input for validation
        import copy
        self.state.original_input = copy.deepcopy(data)
        # Load schema and embedding config once
        try:
            self.state.schema_payload = load_schema_payload()
        except Exception as e:
            logger.warning(f"KGFlow: failed to load schema_v3.json: {e}")
            self.state.schema_payload = []
        try:
            self.state.embedding_config = derive_embedding_config_from_schema()
        except Exception as e:
            logger.warning(f"KGFlow: failed to derive embedding config: {e}")
            self.state.embedding_config = {}
        return data

    @listen(start_flow)
    def validate_uuid_references(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Validate that UUIDs referenced in edges and nodes exist in Neo4j.
        
        For read-only catalog nodes (Forum, Jurisdiction, ReliefType, Domain):
        - Validate UUIDs referenced in edges exist in Neo4j
        - Don't load node data, just validate existence
        - Edges will maintain these UUIDs for later Cypher queries
        
        For other nodes with _id properties (like Law with law_id):
        - Validate UUIDs exist in Neo4j
        - Don't load node data
        - Ensure UUIDs remain in the data
        """
        data = dict(ctx or {})
        nodes = list(data.get("nodes") or [])
        edges = list(data.get("edges") or [])
        
        validation_errors = []
        
        try:
            from app.lib.neo4j_client import neo4j_client
            
            schema_payload = self.state.schema_payload
            
            # Map label to ID property name for catalog nodes
            catalog_id_property_map = {
                'ReliefType': 'relief_type_id',
                'Forum': 'forum_id',
                'Jurisdiction': 'jurisdiction_id',
                'Domain': 'domain_id',
            }
            
            # Map edge labels to their expected catalog node types and which end references the catalog node
            edge_to_catalog_config = {
                'IS_TYPE': {'type': 'ReliefType', 'end': 'to'},  # Relief -> ReliefType
                'HEARD_IN': {'type': 'Forum', 'end': 'to'},  # Proceeding -> Forum
                'PART_OF': {'type': 'Jurisdiction', 'end': 'to'},  # Forum -> Jurisdiction
                'CONTAINS': {'type': 'Domain', 'end': 'from'}  # Domain -> Case (source is catalog)
            }
            
            # Collect catalog node UUIDs referenced in edges for validation
            catalog_ids_to_validate: Dict[str, List[str]] = {}  # label -> list of UUIDs
            catalog_references: Dict[str, str] = {}  # Track for validation reporting
            
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                
                edge_label = edge.get("label")
                if edge_label not in edge_to_catalog_config:
                    continue
                
                config = edge_to_catalog_config[edge_label]
                catalog_type = config['type']
                end_field = config['end']
                
                catalog_uuid = edge.get(end_field)
                if not catalog_uuid:
                    continue
                
                # Store reference for validation tracking
                ref_key = f"{edge_label}:{catalog_type}:{catalog_uuid}"
                catalog_references[ref_key] = str(catalog_uuid)
                
                if catalog_type not in catalog_ids_to_validate:
                    catalog_ids_to_validate[catalog_type] = []
                
                if catalog_uuid not in catalog_ids_to_validate[catalog_type]:
                    catalog_ids_to_validate[catalog_type].append(catalog_uuid)
            
            # Validate catalog node UUIDs exist in Neo4j
            for catalog_label, uuids in catalog_ids_to_validate.items():
                if not uuids:
                    continue
                
                id_prop = catalog_id_property_map.get(catalog_label, f'{catalog_label.lower()}_id')
                
                # Validate UUIDs exist in Neo4j (just check existence, don't fetch data)
                query = f"MATCH (n:`{catalog_label}`) WHERE n.{id_prop} IN $ids RETURN n.{id_prop} as id"
                try:
                    result = neo4j_client.execute_query(query, {"ids": uuids})
                    found_uuids = {str(record.get('id')) for record in result if record.get('id')}
                    
                    # Check for missing UUIDs
                    for uuid_val in uuids:
                        uuid_str = str(uuid_val)
                        if uuid_str not in found_uuids:
                            validation_errors.append(
                                f"Catalog node {catalog_label} with {id_prop}={uuid_str} not found in Neo4j"
                            )
                    logger.info(f"KGFlow: Validated {len(found_uuids)}/{len(uuids)} {catalog_label} UUIDs exist in Neo4j")
                except Exception as e:
                    logger.warning(f"KGFlow: Failed to validate {catalog_label} UUIDs: {e}")
                    validation_errors.append(f"Failed to validate {catalog_label} UUIDs: {e}")
            
            # Validate other nodes with _id properties exist in Neo4j
            nodes_to_validate: Dict[str, List[tuple]] = {}  # label -> list of (uuid, node_index)
            
            for idx, node in enumerate(nodes):
                if not isinstance(node, dict):
                    continue
                
                label = node.get("label")
                if not label or label in CATALOG_ONLY_NODES:
                    continue  # Skip catalog nodes (already validated above)
                
                props = node.get("properties") or {}
                if not isinstance(props, dict):
                    continue
                
                # Get the *_id property for this label
                id_prop = get_id_prop_for_label(label, schema_payload)
                node_uuid = props.get(id_prop)
                
                # If node has a UUID in its _id property, validate it exists in Neo4j
                if node_uuid and is_uuid(str(node_uuid)):
                    if label not in nodes_to_validate:
                        nodes_to_validate[label] = []
                    nodes_to_validate[label].append((str(node_uuid), idx))
            
            # Validate each node type's UUIDs exist in Neo4j
            for label, uuid_list in nodes_to_validate.items():
                if not uuid_list:
                    continue
                
                uuids = [uuid_val for uuid_val, _ in uuid_list]
                id_prop = get_id_prop_for_label(label, schema_payload)
                
                # Validate UUIDs exist in Neo4j (just check existence, don't fetch data)
                query = f"MATCH (n:`{label}`) WHERE n.{id_prop} IN $ids RETURN n.{id_prop} as id"
                try:
                    result = neo4j_client.execute_query(query, {"ids": uuids})
                    found_uuids = {str(record.get('id')) for record in result if record.get('id')}
                    
                    # Check for missing UUIDs
                    for uuid_val, node_idx in uuid_list:
                        uuid_str = str(uuid_val)
                        if uuid_str not in found_uuids:
                            validation_errors.append(
                                f"Node {node_idx} ({label}) with {id_prop}={uuid_str} not found in Neo4j"
                            )
                    logger.info(f"KGFlow: Validated {len(found_uuids)}/{len(uuids)} {label} UUIDs exist in Neo4j")
                except Exception as e:
                    logger.warning(f"KGFlow: Failed to validate {label} UUIDs: {e}")
                    validation_errors.append(f"Failed to validate {label} UUIDs: {e}")
            
            # Store catalog references for later validation reporting
            self.state.catalog_node_references = catalog_references
            
            # Log validation results
            if validation_errors:
                logger.warning(f"KGFlow: UUID validation found {len(validation_errors)} errors:")
                for error in validation_errors[:10]:  # Log first 10 errors
                    logger.warning(f"  - {error}")
                if len(validation_errors) > 10:
                    logger.warning(f"  ... and {len(validation_errors) - 10} more errors")
            else:
                logger.info("KGFlow: All UUID references validated successfully ✓")
            
        except Exception as e:
            logger.warning(f"KGFlow: Failed to validate UUID references in Neo4j: {e}")
            validation_errors.append(f"Neo4j validation failed: {e}")
        
        # Continue processing even if validation fails (validation issues will be logged)
        # The actual submission to Neo4j will fail if UUIDs don't exist anyway
        data["nodes"] = nodes
        data["edges"] = edges
        self.state.payload = data
        return data

    @listen(validate_uuid_references)
    def normalize_ids(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(ctx or {})
        nodes = list(data.get("nodes") or [])
        edges = list(data.get("edges") or [])

        # Build map temp_id -> uuid (reuse if already uuid)
        # For nodes with existing *_id properties (like Law with law_id), prefer those
        id_map: Dict[str, str] = {}
        schema_payload = self.state.schema_payload
        
        for n in nodes:
            if not isinstance(n, dict):
                continue
            raw_tid = n.get("temp_id")
            label = n.get("label")
            props = n.get("properties") or {}
            
            # Check if node already has a *_id property with a UUID value
            existing_id = None
            if isinstance(label, str) and isinstance(props, dict):
                id_prop = get_id_prop_for_label(label, schema_payload)
                existing_id_value = props.get(id_prop)
                if existing_id_value and is_uuid(str(existing_id_value)):
                    existing_id = str(existing_id_value)
            
            # Determine the UUID to use:
            # 1. If node has existing *_id with UUID, use that
            # 2. If temp_id is already a UUID, use that
            # 3. Otherwise generate new UUID
            if existing_id:
                uid = existing_id
            elif raw_tid and isinstance(raw_tid, str):
                uid = raw_tid if is_uuid(raw_tid) else str(uuid.uuid4())
            else:
                uid = str(uuid.uuid4())
            
            # Map temp_id to the chosen UUID
            if raw_tid:
                id_map[raw_tid] = uid
            # Also map existing_id if different from temp_id
            if existing_id and existing_id != raw_tid:
                id_map[existing_id] = uid
        
        # Store mapping for validation
        self.state.id_mapping = id_map

        # Update edges - map temp_ids to UUIDs, but preserve catalog UUIDs
        # Catalog UUIDs (read-only nodes) are already UUIDs and should not be remapped
        for e in edges:
            if not isinstance(e, dict):
                continue
            frm = e.get("from")
            to = e.get("to")
            
            # Only remap if the value is in id_map (i.e., it's a temp_id that needs mapping)
            # If it's already a UUID and not in id_map, preserve it (likely a catalog UUID)
            if isinstance(frm, str):
                if frm in id_map:
                    e["from"] = id_map[frm]
                elif not is_uuid(frm):
                    # Not a UUID and not in map - this is an error, but log it
                    logger.warning(f"Edge 'from' value '{frm}' is not a UUID and not in id_map")
            
            if isinstance(to, str):
                if to in id_map:
                    e["to"] = id_map[to]
                elif not is_uuid(to):
                    # Not a UUID and not in map - this is an error, but log it
                    logger.warning(f"Edge 'to' value '{to}' is not a UUID and not in id_map")

        # Replace temp_id with schema-driven *_id on nodes
        # Note: We already handled existing *_id properties in the id_map building above
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
            
            # Get the UUID - prefer from temp_id mapping, but preserve existing *_id if already set
            mapped_uuid = id_map.get(tid)
            
            # Only set *_id if not already present or if we need to update it
            if mapped_uuid:
                # Only overwrite if the existing value is different or missing
                existing_id_value = props.get(id_prop)
                if not existing_id_value or str(existing_id_value) != mapped_uuid:
                    props[id_prop] = mapped_uuid
            elif not props.get(id_prop):
                # No mapping and no existing *_id - generate one
                props[id_prop] = str(uuid.uuid4())
            
            n["properties"] = props
            # Note: temp_id will be removed before Neo4j upload and added back before Postgres save

        data["nodes"] = nodes
        data["edges"] = edges
        self.state.payload = data
        return data

    @listen(normalize_ids)
    def check_existing_for_embeddings(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Query Neo4j for existing nodes to determine which need new embeddings.
        
        Compares text field hashes to determine if embeddings need regeneration.
        """
        data = dict(ctx or {})
        nodes = list(data.get("nodes") or [])
        schema_payload = self.state.schema_payload
        embedding_config = self.state.embedding_config or {}
        
        # Set to store UUIDs of nodes that need embeddings
        nodes_needing_embeddings = set()
        
        try:
            from app.lib.neo4j_client import neo4j_client
            import hashlib
            
            # Group nodes by label for batch querying
            nodes_by_label = {}
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                
                label = node.get("label")
                if not isinstance(label, str):
                    continue
                
                # Skip nodes that don't have embeddings configured
                if label not in embedding_config or not embedding_config[label]:
                    continue
                
                props = node.get("properties") or {}
                id_prop = get_id_prop_for_label(label, schema_payload)
                node_uuid = props.get(id_prop)
                
                if node_uuid and is_uuid(str(node_uuid)):
                    if label not in nodes_by_label:
                        nodes_by_label[label] = []
                    nodes_by_label[label].append({
                        "uuid": str(node_uuid),
                        "props": props,
                        "embedding_fields": embedding_config[label]
                    })
            
            # Query Neo4j for existing nodes with their text fields
            for label, node_list in nodes_by_label.items():
                if not node_list:
                    continue
                
                uuids = [n["uuid"] for n in node_list]
                id_prop = get_id_prop_for_label(label, schema_payload)
                
                # Get embedding source fields for this label
                embedding_fields = node_list[0]["embedding_fields"]
                
                # Build query to fetch text fields AND check if embeddings exist
                return_fields = [f"n.{id_prop} as id"]
                for field in embedding_fields:
                    return_fields.append(f"n.{field} as {field}")
                    return_fields.append(f"n.{field}_embedding IS NOT NULL as {field}_has_embedding")
                query = f"MATCH (n:`{label}`) WHERE n.{id_prop} IN $ids RETURN {', '.join(return_fields)}"
                
                try:
                    result = neo4j_client.execute_query(query, {"ids": uuids})
                    
                    # Build hash map of existing node text fields and embedding existence
                    existing_info = {}
                    for record in result:
                        node_id = str(record.get("id"))
                        if not node_id:
                            continue
                        
                        # Hash all text fields and track embedding existence
                        node_data = {"text_hashes": {}, "embeddings_exist": {}}
                        for field in embedding_fields:
                            text_value = record.get(field, "")
                            if text_value:
                                hash_obj = hashlib.sha256(str(text_value).encode('utf-8'))
                                node_data["text_hashes"][field] = hash_obj.hexdigest()
                            # Check if embedding exists
                            node_data["embeddings_exist"][field] = bool(record.get(f"{field}_has_embedding", False))
                        existing_info[node_id] = node_data
                    
                    # Compare with input nodes to determine which need new embeddings
                    for node_info in node_list:
                        node_uuid = node_info["uuid"]
                        props = node_info["props"]
                        
                        # If node doesn't exist in Neo4j, it needs embeddings
                        if node_uuid not in existing_info:
                            nodes_needing_embeddings.add(node_uuid)
                            logger.debug(f"Node {label}:{node_uuid} is new, needs embeddings")
                            continue
                        
                        # Compare hashes of text fields AND check embedding existence
                        existing = existing_info[node_uuid]
                        existing_hashes = existing["text_hashes"]
                        embeddings_exist = existing["embeddings_exist"]
                        needs_update = False
                        
                        for field in embedding_fields:
                            current_text = props.get(field, "")
                            if current_text:
                                # Check if embedding is missing
                                if not embeddings_exist.get(field, False):
                                    needs_update = True
                                    logger.debug(f"Node {label}:{node_uuid} field '{field}' missing embedding")
                                    break
                                # Check if text changed
                                current_hash = hashlib.sha256(str(current_text).encode('utf-8')).hexdigest()
                                if existing_hashes.get(field) != current_hash:
                                    needs_update = True
                                    logger.debug(f"Node {label}:{node_uuid} field '{field}' changed, needs embeddings")
                                    break
                        
                        if needs_update:
                            nodes_needing_embeddings.add(node_uuid)
                    
                    logger.info(f"Checked {len(node_list)} {label} nodes: {len([n for n in node_list if n['uuid'] in nodes_needing_embeddings])} need embeddings")
                    
                except Exception as e:
                    logger.warning(f"Failed to check existing {label} nodes for embeddings: {e}")
                    # On error, assume all nodes need embeddings
                    for node_info in node_list:
                        nodes_needing_embeddings.add(node_info["uuid"])
        
        except Exception as e:
            logger.warning(f"Failed to check existing nodes for embeddings: {e}")
            # On error, generate embeddings for all nodes (safe default)
            for node in nodes:
                if isinstance(node, dict):
                    label = node.get("label")
                    if label in embedding_config and embedding_config[label]:
                        props = node.get("properties") or {}
                        id_prop = get_id_prop_for_label(label, schema_payload)
                        node_uuid = props.get(id_prop)
                        if node_uuid:
                            nodes_needing_embeddings.add(str(node_uuid))
        
        # Store in state
        self.state.nodes_needing_embeddings = nodes_needing_embeddings
        logger.info(f"Total nodes needing embeddings: {len(nodes_needing_embeddings)}")
        
        data["nodes"] = nodes
        self.state.payload = data
        return data

    @listen(check_existing_for_embeddings)
    def compute_embeddings(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(ctx or {})
        nodes = list(data.get("nodes") or [])
        cfg = self.state.embedding_config or {}
        nodes_needing_embeddings = self.state.nodes_needing_embeddings or set()
        schema_payload = self.state.schema_payload

        for n in nodes:
            if not isinstance(n, dict):
                continue
            label = n.get("label")
            if not isinstance(label, str):
                continue
            props = dict(n.get("properties") or {})
            
            # Get node UUID to check if it needs embeddings
            id_prop = get_id_prop_for_label(label, schema_payload)
            node_uuid = props.get(id_prop)
            
            # Skip embedding generation if node doesn't need it
            if node_uuid and str(node_uuid) not in nodes_needing_embeddings:
                logger.debug(f"Skipping embeddings for {label}:{node_uuid} (unchanged)")
                n["properties"] = props
                continue
            
            targets = cfg.get(label, [])
            if not isinstance(targets, list) or not targets:
                n["properties"] = props
                continue
            
            embeddings_generated = 0
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
                    embeddings_generated += 1
                except Exception as e:
                    logger.warning(f"KGFlow: embedding failed for {label}.{prop_name}: {e}")
                    continue
            
            if embeddings_generated > 0:
                logger.debug(f"Generated {embeddings_generated} embeddings for {label}:{node_uuid}")
            
            n["properties"] = props

        data["nodes"] = nodes
        self.state.payload = data
        return data

    def _truncate_embeddings(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a copy of data with embedding properties truncated for logging."""
        import copy
        truncated = copy.deepcopy(data)
        
        nodes = truncated.get("nodes", [])
        for node in nodes:
            if not isinstance(node, dict):
                continue
            props = node.get("properties", {})
            if not isinstance(props, dict):
                continue
            for key, value in props.items():
                if key.endswith("_embedding") and isinstance(value, (list, tuple)):
                    # Truncate to first few elements and show length
                    truncated_list = list(value)[:3] if len(value) > 3 else list(value)
                    props[key] = f"<embedding: {len(value)} dimensions, first 3: {truncated_list}>"
                elif key.endswith("_embedding"):
                    # For non-list embeddings, just show first few chars
                    str_val = str(value)
                    props[key] = f"<embedding: {str_val[:50]}...>" if len(str_val) > 50 else f"<embedding: {str_val}>"
        
        edges = truncated.get("edges", [])
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            props = edge.get("properties", {})
            if not isinstance(props, dict):
                continue
            for key, value in props.items():
                if key.endswith("_embedding") and isinstance(value, (list, tuple)):
                    truncated_list = list(value)[:3] if len(value) > 3 else list(value)
                    props[key] = f"<embedding: {len(value)} dimensions, first 3: {truncated_list}>"
                elif key.endswith("_embedding"):
                    str_val = str(value)
                    props[key] = f"<embedding: {str_val[:50]}...>" if len(str_val) > 50 else f"<embedding: {str_val}>"
        
        return truncated

    @listen(compute_embeddings)
    def remove_temp_ids(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Remove temp_id from all nodes before Neo4j upload.
        
        The temp_id is only needed during transformation for ID mapping.
        It will be added back before Postgres save by copying from the node's *_id property.
        """
        data = dict(ctx or {})
        nodes = list(data.get("nodes") or [])
        
        for node in nodes:
            if isinstance(node, dict) and "temp_id" in node:
                del node["temp_id"]
        
        data["nodes"] = nodes
        self.state.payload = data
        logger.debug("Removed temp_id from all nodes before Neo4j upload")
        return data

    @listen(remove_temp_ids)
    def finish(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(ctx or {})
        # Log ReliefType.relief_type_id from final data
        nodes = data.get("nodes", [])
        for i, node in enumerate(nodes):
            if isinstance(node, dict) and node.get("label") == "ReliefType":
                props = node.get("properties", {})
                if isinstance(props, dict):
                    relief_type_id = props.get("relief_type_id")
                    logger.info("KGFlow final: ReliefType node %d has relief_type_id=%s", i, relief_type_id)
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
        catalog_references = self.state.catalog_node_references
        issues = self._validate_transformation(output_data, input_data, id_mapping, schema_payload, embedding_config, issues, stats, catalog_references)
        
        # Then validate against schema
        schema_issues = self._validate_against_schema(output_data, schema_payload)
        
        return output_data

    def _validate_transformation(self, output_data, input_data, id_mapping, schema_payload, embedding_config, issues, stats, catalog_references: Dict[str, str] = None):
        
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
        
        # Track UUID preservation per label
        uuid_preservation_by_label: Dict[str, Dict[str, int]] = {}  # label -> {preserved: int, total: int}
        
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
                    input_props = input_node.get("properties", {})
                    input_temp_id = input_node.get("temp_id")
                    
                    # Check if input had a UUID in its *_id property
                    input_existing_uuid = None
                    if isinstance(input_props, dict):
                        input_id_prop = get_id_prop_for_label(label, schema_payload)
                        input_existing_uuid_value = input_props.get(input_id_prop)
                        if input_existing_uuid_value and is_uuid(str(input_existing_uuid_value)):
                            input_existing_uuid = str(input_existing_uuid_value)
                    
                    # Determine the input UUID to check against
                    input_uuid_to_check = None
                    if input_existing_uuid:
                        # Input had UUID in *_id property
                        input_uuid_to_check = input_existing_uuid
                    elif input_temp_id and is_uuid(input_temp_id):
                        # Input had UUID in temp_id
                        # Map through id_mapping to get the final UUID
                        input_uuid_to_check = id_mapping.get(input_temp_id, input_temp_id)
                    
                    # Track UUID preservation
                    if input_uuid_to_check:
                        if label not in uuid_preservation_by_label:
                            uuid_preservation_by_label[label] = {"preserved": 0, "total": 0}
                        uuid_preservation_by_label[label]["total"] += 1
                        
                        # Verify UUID was preserved
                        if str(node_id) == input_uuid_to_check:
                            stats["uuids_preserved"] += 1
                            uuid_preservation_by_label[label]["preserved"] += 1
                        else:
                            issues.append(f"Node {i}: UUID not preserved (input={input_uuid_to_check}, output={node_id})")
        
        # Check 5: Embeddings count
        # Get the set of nodes that needed embeddings (skips unchanged catalog nodes)
        nodes_needing_embeddings = self.state.nodes_needing_embeddings or set()
        
        for node in output_nodes:
            if not isinstance(node, dict):
                continue
            label = node.get("label", "")
            props = node.get("properties", {})
            if not isinstance(props, dict):
                continue
            
            # Get the node UUID
            id_prop = get_id_prop_for_label(label, schema_payload)
            node_uuid = props.get(id_prop)
            
            # Count embedding properties
            embedding_count = sum(1 for k in props.keys() if k.endswith("_embedding"))
            if label not in stats["embeddings_by_label"]:
                stats["embeddings_by_label"][label] = {"expected": 0, "actual": embedding_count}
            else:
                stats["embeddings_by_label"][label]["actual"] = embedding_count
            
            # Check against expected count from config
            expected_fields = embedding_config.get(label, [])
            stats["embeddings_by_label"][label]["expected"] = len(expected_fields)
            
            # Only flag missing embeddings for nodes that SHOULD have had embeddings generated
            # Skip validation for unchanged catalog nodes (not in nodes_needing_embeddings)
            if embedding_count != len(expected_fields):
                if node_uuid and str(node_uuid) in nodes_needing_embeddings:
                    # This node was supposed to get embeddings but didn't get enough
                    issues.append(f"Node {label}: expected {len(expected_fields)} embeddings, found {embedding_count}")
                # else: unchanged catalog node - skip validation (it has embeddings in Neo4j already)
        
        # Check 6: Edge integrity
        if len(output_edges) != len(input_edges):
            issues.append(f"Edge count mismatch: input={len(input_edges)}, output={len(output_edges)}")
        
        # Collect catalog UUIDs from edges (these won't be in output nodes, and that's OK)
        catalog_uuids_in_edges = set()
        edge_to_catalog_config = {
            'IS_TYPE': {'type': 'ReliefType', 'end': 'to'},
            'HEARD_IN': {'type': 'Forum', 'end': 'to'},
            'PART_OF': {'type': 'Jurisdiction', 'end': 'to'},
            'CONTAINS': {'type': 'Domain', 'end': 'from'}
        }
        for edge in output_edges:
            if not isinstance(edge, dict):
                continue
            edge_label = edge.get("label")
            if edge_label in edge_to_catalog_config:
                config = edge_to_catalog_config[edge_label]
                end_field = config['end']
                catalog_uuid = edge.get(end_field)
                if catalog_uuid:
                    catalog_uuids_in_edges.add(str(catalog_uuid))
        
        for i, edge in enumerate(output_edges):
            if not isinstance(edge, dict):
                continue
            
            frm = edge.get("from")
            to = edge.get("to")
            edge_label = edge.get("label")
            
            # Check if this edge references a catalog node
            is_catalog_from = str(frm) in catalog_uuids_in_edges if frm else False
            is_catalog_to = str(to) in catalog_uuids_in_edges if to else False
            
            if not frm or not is_uuid(str(frm)):
                issues.append(f"Edge {i}: 'from' is not a valid UUID: {frm}")
            elif not is_catalog_from and str(frm) not in output_node_ids:
                issues.append(f"Edge {i}: 'from' UUID {frm} not found in output nodes")
            
            if not to or not is_uuid(str(to)):
                issues.append(f"Edge {i}: 'to' is not a valid UUID: {to}")
            elif not is_catalog_to and str(to) not in output_node_ids:
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
        
        # Check 8: Catalog node UUID preservation in edges
        # Verify that catalog node UUIDs referenced in input edges are preserved in output edges
        if catalog_references:
            # Build a set of all UUIDs referenced in output edges (for catalog nodes)
            edge_to_catalog_config = {
                'IS_TYPE': {'type': 'ReliefType', 'end': 'to'},
                'HEARD_IN': {'type': 'Forum', 'end': 'to'},
                'PART_OF': {'type': 'Jurisdiction', 'end': 'to'},
                'CONTAINS': {'type': 'Domain', 'end': 'from'}
            }
            
            output_catalog_uuids = set()
            for edge in output_edges:
                if not isinstance(edge, dict):
                    continue
                edge_label = edge.get("label")
                if edge_label not in edge_to_catalog_config:
                    continue
                config = edge_to_catalog_config[edge_label]
                end_field = config['end']
                catalog_uuid = edge.get(end_field)
                if catalog_uuid:
                    output_catalog_uuids.add(str(catalog_uuid))
            
            # Validate each catalog reference is preserved in output edges
            for ref_key, expected_uuid in catalog_references.items():
                if expected_uuid not in output_catalog_uuids:
                    issues.append(f"Catalog node reference '{ref_key}': UUID {expected_uuid} not preserved in output edges")
        
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
        
        # Log UUID preservation per label (similar format to validation logs)
        if uuid_preservation_by_label:
            for label in sorted(uuid_preservation_by_label.keys()):
                label_stats = uuid_preservation_by_label[label]
                preserved = label_stats["preserved"]
                total = label_stats["total"]
                logger.info(f"KGFlow: Preserved {preserved}/{total} {label} UUIDs")
        
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
        """Validate the output data against schema_v3.json definitions."""
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
        
        # Build node ID to label mapping for edge validation
        # After KG transformation, nodes have UUID in their *_id property, not temp_id
        node_id_to_label = {}
        for node in nodes:
            if isinstance(node, dict):
                node_label = node.get("label")
                if not node_label:
                    continue
                # Get the UUID from the node's properties (*_id field)
                props = node.get("properties", {})
                if isinstance(props, dict):
                    # Find the *_id property for this label
                    id_prop = get_id_prop_for_label(node_label, schema_payload)
                    node_id = props.get(id_prop)
                    if node_id:
                        node_id_to_label[node_id] = node_label
        
        # Map edge types to catalog node types (for both source and target)
        # Derive from schema_v3.json: catalog nodes are those with can_create_new=false
        # Build mapping dynamically from schema relationships
        catalog_edge_config = {}
        if isinstance(schema_payload, list):
            # First, identify catalog nodes (can_create_new=false)
            catalog_nodes = set()
            for node_def in schema_payload:
                if isinstance(node_def, dict):
                    label = node_def.get("label")
                    can_create_new = node_def.get("can_create_new", True)
                    if label and not can_create_new:
                        catalog_nodes.add(label)
            
            # Build edge config from relationships in schema
            for node_def in schema_payload:
                if not isinstance(node_def, dict):
                    continue
                source_label = node_def.get("label")
                relationships = node_def.get("relationships", {})
                if not isinstance(relationships, dict):
                    continue
                
                for edge_label, target_spec in relationships.items():
                    if not isinstance(edge_label, str):
                        continue
                    # Handle both string and dict format for target_spec
                    target_label = None
                    if isinstance(target_spec, str):
                        target_label = target_spec
                    elif isinstance(target_spec, dict):
                        target_label = target_spec.get("target")
                    
                    if not target_label:
                        continue
                    
                    # Determine if source or target is a catalog node
                    source_is_catalog = source_label in catalog_nodes
                    target_is_catalog = target_label in catalog_nodes
                    
                    # Only include edges where at least one end is a catalog node
                    if source_is_catalog or target_is_catalog:
                        catalog_edge_config[edge_label] = {
                            'source': source_label if source_is_catalog else None,
                            'target': target_label if target_is_catalog else None
                        }
        
        # Validate edges against schema relationships
        for i, edge in enumerate(edges):
            if not isinstance(edge, dict):
                continue
            
            edge_label = edge.get("label")
            if not edge_label:
                issues.append(f"Edge {i}: missing label")
                continue
            
            # Get the source node label to find the correct relationship definition
            source_id = edge.get("from")
            source_label = node_id_to_label.get(source_id) if source_id else None
            
            # If source_label is None, check if this edge type has a catalog node as source
            if not source_label and edge_label in catalog_edge_config:
                catalog_config = catalog_edge_config[edge_label]
                if catalog_config.get('source'):
                    source_label = catalog_config['source']
            
            # Find the relationship definition from the source node's schema
            found_in_schema = False
            expected_props = {}
            
            if source_label:
                # Look for the relationship in the source node's schema definition
                for schema_def in schema_payload:
                    if not isinstance(schema_def, dict):
                        continue
                    if schema_def.get("label") == source_label:
                        relationships = schema_def.get("relationships", {})
                        if isinstance(relationships, dict) and edge_label in relationships:
                            found_in_schema = True
                            rel_def = relationships[edge_label]
                            if isinstance(rel_def, dict):
                                expected_props = rel_def.get("properties", {})
                            break
            
            if not found_in_schema:
                issues.append(f"Edge {i}: relationship type '{edge_label}' not found in schema for source node type '{source_label}'")
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


