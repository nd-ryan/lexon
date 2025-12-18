"""Neo4j uploader for KG Flow - schema-driven graph data upload."""

import logging
import hashlib
from typing import Dict, Any, List, Set, Tuple, Optional
from app.lib.logging_config import setup_logger

logger = setup_logger("neo4j-uploader")


def to_snake_case(label: str) -> str:
    """Convert CamelCase to snake_case."""
    import re
    if not isinstance(label, str):
        return str(label)
    if label == "":
        return ""
    # Handle acronyms properly: URLValue -> url_value (not u_r_l_value)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", label)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


def get_id_prop_for_label(label: str, schema_payload: Any) -> str:
    """Return the *_id property name for a label based on schema.
    
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


class Neo4jUploader:
    """Upload case graph data to Neo4j with schema-driven Cypher generation."""
    
    def __init__(self, schema_payload: Any, neo4j_client: Any):
        """Initialize uploader with schema and Neo4j client.
        
        Args:
            schema_payload: Parsed schema_v3.json (list of node definitions)
            neo4j_client: Neo4j client instance with execute_query method
        """
        self.schema_payload = schema_payload
        self.neo4j_client = neo4j_client
        self.catalog_labels = self._identify_catalog_labels()
        self.schema_by_label = self._build_schema_lookup()
        
    def _identify_catalog_labels(self) -> Set[str]:
        """Identify catalog node labels (can_create_new=false)."""
        catalog_labels = set()
        if isinstance(self.schema_payload, list):
            for node_def in self.schema_payload:
                if isinstance(node_def, dict):
                    label = node_def.get("label")
                    can_create_new = node_def.get("can_create_new", True)
                    if label and not can_create_new:
                        catalog_labels.add(label)
        logger.info(f"Identified catalog labels: {catalog_labels}")
        return catalog_labels
    
    def _build_schema_lookup(self) -> Dict[str, Dict[str, Any]]:
        """Build label -> schema definition mapping."""
        schema_by_label = {}
        if isinstance(self.schema_payload, list):
            for node_def in self.schema_payload:
                if isinstance(node_def, dict) and "label" in node_def:
                    schema_by_label[node_def["label"]] = node_def
        return schema_by_label
    
    def upload_graph_data(self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Upload nodes and edges to Neo4j, returning updated data with _ids.
        
        Args:
            nodes: List of node dicts with {label, properties, is_existing}
            edges: List of edge dicts with {from, to, label, properties}
            
        Returns:
            Dict with updated nodes and edges including Neo4j-generated _ids
        """
        logger.info(f"Starting Neo4j upload: {len(nodes)} nodes, {len(edges)} edges")
        
        # Check which nodes already exist in Neo4j
        existing_nodes = self._check_existing_nodes(nodes)
        logger.info(f"Found {len(existing_nodes)} existing nodes in Neo4j")
        
        # Generate Cypher queries for nodes and edges
        node_queries = []
        node_id_mapping = {}  # temp tracking: label -> [(uuid, index)]
        
        for idx, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            
            label = node.get("label")
            
            # Skip catalog nodes - they already exist
            if label in self.catalog_labels:
                logger.debug(f"Skipping catalog node: {label}")
                continue
            
            props = node.get("properties") or {}
            id_prop = get_id_prop_for_label(label, self.schema_payload)
            node_uuid = props.get(id_prop)
            
            is_existing = node_uuid and str(node_uuid) in existing_nodes.get(label, set())
            
            query, params = self._generate_node_cypher(node, is_existing)
            node_queries.append((query, params, idx, label, id_prop))
            
        # Generate Cypher queries for edges
        edge_queries = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            query, params = self._generate_edge_cypher(edge)
            if query:
                edge_queries.append((query, params))
        
        # Execute all queries in a single transaction
        updated_nodes, updated_edges = self._execute_in_transaction(
            node_queries, edge_queries, nodes, edges
        )
        
        logger.info(f"Neo4j upload complete: {len(updated_nodes)} nodes, {len(updated_edges)} edges")
        
        return {
            "nodes": updated_nodes,
            "edges": updated_edges
        }
    
    def _check_existing_nodes(self, nodes: List[Dict[str, Any]]) -> Dict[str, Set[str]]:
        """Query Neo4j for existing nodes by their _id properties.
        
        Returns:
            Dict mapping label -> set of existing UUIDs
        """
        existing_by_label = {}
        
        # Group nodes by label for batch querying
        nodes_by_label = {}
        for node in nodes:
            if not isinstance(node, dict):
                continue
            label = node.get("label")
            if label in self.catalog_labels:
                continue  # Skip catalog nodes
            
            props = node.get("properties") or {}
            id_prop = get_id_prop_for_label(label, self.schema_payload)
            node_uuid = props.get(id_prop)
            
            if node_uuid:
                if label not in nodes_by_label:
                    nodes_by_label[label] = []
                nodes_by_label[label].append(str(node_uuid))
        
        # Query Neo4j for each label
        for label, uuids in nodes_by_label.items():
            if not uuids:
                continue
            
            id_prop = get_id_prop_for_label(label, self.schema_payload)
            query = f"MATCH (n:`{label}`) WHERE n.{id_prop} IN $ids RETURN n.{id_prop} as id"
            
            try:
                result = self.neo4j_client.execute_query(query, {"ids": uuids})
                found_uuids = {str(record.get("id")) for record in result if record.get("id")}
                existing_by_label[label] = found_uuids
                logger.debug(f"Found {len(found_uuids)}/{len(uuids)} existing {label} nodes")
            except Exception as e:
                logger.warning(f"Failed to check existing {label} nodes: {e}")
                existing_by_label[label] = set()
        
        return existing_by_label
    
    def _generate_node_cypher(self, node: Dict[str, Any], is_existing: bool) -> Tuple[str, Dict[str, Any]]:
        """Generate Cypher query for creating/updating a node.
        
        Args:
            node: Node dict with label and properties
            is_existing: Whether node exists in Neo4j
            
        Returns:
            Tuple of (cypher_query, parameters)
        """
        label = node.get("label")
        properties = node.get("properties") or {}
        
        if not label:
            return "", {}
        
        id_prop = get_id_prop_for_label(label, self.schema_payload)
        node_uuid = properties.get(id_prop)
        
        # Build parameters dict with type conversion
        params = {}
        set_clauses = []
        
        schema_def = self.schema_by_label.get(label, {})
        schema_props = schema_def.get("properties", {})
        
        for prop_name, value in properties.items():
            if value is None:
                continue  # Skip null values
            
            # Skip upload codes (hidden fields)
            # Note: Embeddings are allowed and expected (generated by KGFlow)
            if prop_name.endswith("_upload_code"):
                continue
            
            # Get property schema definition
            prop_def = schema_props.get(prop_name, {})
            prop_type = prop_def.get("type", "STRING")
            
            # Convert value based on type
            converted_value = self._convert_property_value(value, prop_type)

            # If conversion failed (e.g., invalid DATE like '1942-00-00'), skip setting it.
            # This avoids generating Cypher that either errors (date()) or unintentionally
            # overwrites/removes existing properties on MERGE.
            if converted_value is None:
                continue
            
            # Build SET clause
            if prop_type == "DATE" and converted_value is not None:
                # For dates, use date() function in Cypher
                param_name = f"{prop_name}"
                params[param_name] = converted_value
                set_clauses.append(f"n.{prop_name} = date(${param_name})")
            elif prop_type == "FLOAT" and converted_value is not None:
                # For floats, use toFloat() in Cypher
                param_name = f"{prop_name}"
                params[param_name] = converted_value
                set_clauses.append(f"n.{prop_name} = toFloat(${param_name})")
            else:
                # For other types, set directly
                param_name = f"{prop_name}"
                params[param_name] = converted_value
                set_clauses.append(f"n.{prop_name} = ${param_name}")
        
        # Generate query based on whether node exists
        if is_existing and node_uuid:
            # MERGE existing node
            params[id_prop] = str(node_uuid)
            query = f"MERGE (n:`{label}` {{{id_prop}: ${id_prop}}})\n"
            if set_clauses:
                query += "SET " + ",\n    ".join(set_clauses) + "\n"
            query += f"RETURN n.{id_prop} as id"
        else:
            # CREATE new node
            query = f"CREATE (n:`{label}`)\n"
            # Add UUID generation
            set_clauses.insert(0, f"n.{id_prop} = randomUUID()")
            query += "SET " + ",\n    ".join(set_clauses) + "\n"
            query += f"RETURN n.{id_prop} as id"
        
        return query, params
    
    def _generate_edge_cypher(self, edge: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """Generate Cypher query for creating/updating a relationship.
        
        Args:
            edge: Edge dict with from, to, label, properties
            
        Returns:
            Tuple of (cypher_query, parameters)
        """
        from_uuid = edge.get("from")
        to_uuid = edge.get("to")
        edge_label = edge.get("label")
        properties = edge.get("properties") or {}
        
        if not all([from_uuid, to_uuid, edge_label]):
            logger.warning(f"Incomplete edge data: {edge}")
            return "", {}
        
        # Find source and target labels by looking up in nodes
        # We'll use a dynamic approach since we don't have node context here
        # The query will match any nodes with matching UUIDs
        
        # Build parameters
        params = {
            "from_uuid": str(from_uuid),
            "to_uuid": str(to_uuid)
        }
        
        # Build property SET clauses
        set_clauses = []
        for prop_name, value in properties.items():
            if value is None:
                continue
            param_name = f"prop_{prop_name}"
            params[param_name] = value
            set_clauses.append(f"r.{prop_name} = ${param_name}")
        
        # Generate MERGE query
        # We match nodes by any *_id property since we don't know label beforehand
        query = """
        MATCH (from)
        WHERE any(key IN keys(from) WHERE key ENDS WITH '_id' AND from[key] = $from_uuid)
        MATCH (to)
        WHERE any(key IN keys(to) WHERE key ENDS WITH '_id' AND to[key] = $to_uuid)
        MERGE (from)-[r:`""" + edge_label + """`]->(to)
        """
        
        if set_clauses:
            query += "\nSET " + ",\n    ".join(set_clauses)
        
        return query, params
    
    def _convert_property_value(self, value: Any, prop_type: str) -> Any:
        """Convert property value based on schema type.
        
        Args:
            value: Raw property value
            prop_type: Schema type (STRING, DATE, FLOAT, LIST)
            
        Returns:
            Converted value suitable for Neo4j
        """
        if value is None:
            return None
        
        if prop_type == "DATE":
            # Validate *real* date values.
            # We see upstream sources emit placeholders like '1942-00-00' to represent unknown
            # month/day. Neo4j's date() rejects these, so treat them as missing.
            if not isinstance(value, str):
                return None

            import re
            from datetime import date

            if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
                logger.warning(f"Invalid date format: {value}")
                return None

            year_s, month_s, day_s = value.split("-")

            # Reject placeholder values like 00 month/day
            if month_s == "00" or day_s == "00":
                return None

            # Validate calendar correctness (catches 13th month, Feb 30, etc.)
            try:
                date.fromisoformat(value)
            except ValueError:
                return None

            return value
        
        elif prop_type == "FLOAT":
            # Convert to float
            try:
                return float(value)
            except (ValueError, TypeError):
                logger.warning(f"Cannot convert to float: {value}")
                return None
        
        elif prop_type == "LIST":
            # Ensure it's a list
            if isinstance(value, list):
                return value
            return [value]
        
        else:  # STRING or unknown
            return value
    
    def _execute_in_transaction(
        self,
        node_queries: List[Tuple[str, Dict, int, str, str]],
        edge_queries: List[Tuple[str, Dict]],
        original_nodes: List[Dict[str, Any]],
        original_edges: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Execute all queries in a single transaction.
        
        Args:
            node_queries: List of (query, params, node_index, label, id_prop) tuples
            edge_queries: List of (query, params) tuples
            original_nodes: Original node list to update
            original_edges: Original edge list to return
            
        Returns:
            Tuple of (updated_nodes, edges)
        """
        import copy
        updated_nodes = copy.deepcopy(original_nodes)
        
        try:
            # Execute node and edge writes inside a REAL Neo4j transaction.
            # This guarantees atomicity: if any node/edge write fails, nothing is committed.
            with self.neo4j_client.transaction() as tx:
                # Execute node queries and capture generated UUIDs
                for query, params, idx, label, id_prop in node_queries:
                    try:
                        result = self.neo4j_client.execute_query_in_tx(tx, query, params)
                        if result and len(result) > 0:
                            generated_id = result[0].get("id")
                            if generated_id and idx < len(updated_nodes):
                                # Update node with generated UUID
                                if "properties" not in updated_nodes[idx]:
                                    updated_nodes[idx]["properties"] = {}
                                updated_nodes[idx]["properties"][id_prop] = str(generated_id)
                                logger.debug(f"Node {label}[{idx}] assigned {id_prop}={generated_id}")
                    except Exception as e:
                        logger.error(f"Failed to execute node query: {e}")
                        logger.error(f"Query: {query}")
                        logger.error(f"Params: {params}")
                        raise

                # Execute edge queries
                for query, params in edge_queries:
                    try:
                        self.neo4j_client.execute_query_in_tx(tx, query, params)
                    except Exception as e:
                        logger.error(f"Failed to execute edge query: {e}")
                        logger.error(f"Query: {query}")
                        logger.error(f"Params: {params}")
                        raise

            logger.info("Transaction completed successfully")
            return updated_nodes, original_edges
            
        except Exception as e:
            logger.error(f"Transaction failed: {e}")
            raise

    def check_node_isolation(self, label: str, node_id: str, case_node_ids: Set[str]) -> bool:
        """Check if a node only connects to nodes within the case.
        
        Args:
            label: Node label
            node_id: The node's *_id property value
            case_node_ids: Set of *_id values for all nodes in this case
            
        Returns:
            True if node only connects to case nodes (safe to delete), False otherwise
        """
        id_prop = get_id_prop_for_label(label, self.schema_payload)
        
        # Query all connected nodes
        query = f"""
        MATCH (n:`{label}` {{{id_prop}: $node_id}})-[r]-(connected)
        RETURN connected, keys(connected) as props
        """
        
        try:
            results = self.neo4j_client.execute_query(query, {"node_id": node_id})
            
            for record in results:
                connected = record.get("connected", {})
                props = record.get("props", [])
                
                # Check if any *_id property is in case_node_ids
                is_case_node = False
                for prop in props:
                    if prop.endswith("_id"):
                        connected_id = connected.get(prop)
                        if connected_id and str(connected_id) in case_node_ids:
                            is_case_node = True
                            break
                
                if not is_case_node:
                    # Found a connection outside the case
                    logger.info(f"Node {label}:{node_id} has external connections")
                    return False
            
            return True
            
        except Exception as e:
            logger.warning(f"Failed to check node isolation for {label}:{node_id}: {e}")
            # Default to False (not isolated) to be safe
            return False

    def delete_node(self, label: str, node_id: str) -> bool:
        """Delete a node from Neo4j.
        
        Args:
            label: Node label
            node_id: The node's *_id property value
            
        Returns:
            True if deleted successfully, False otherwise
        """
        id_prop = get_id_prop_for_label(label, self.schema_payload)
        
        query = f"MATCH (n:`{label}` {{{id_prop}: $node_id}}) DETACH DELETE n"
        
        try:
            self.neo4j_client.execute_query(query, {"node_id": node_id})
            logger.info(f"Deleted node {label}:{node_id} from Neo4j")
            return True
        except Exception as e:
            logger.error(f"Failed to delete node {label}:{node_id}: {e}")
            return False

    def detach_node_from_case(self, label: str, node_id: str, case_node_ids: Set[str]) -> int:
        """Detach a node from all case-related nodes (delete relationships only).
        
        This removes relationships between the target node and any nodes belonging
        to the case, without deleting the node itself. Used for non-case-unique
        nodes that may be shared across multiple cases.
        
        Args:
            label: Node label
            node_id: The node's *_id property value
            case_node_ids: Set of *_id values for all nodes in this case
            
        Returns:
            Number of relationships deleted
        """
        id_prop = get_id_prop_for_label(label, self.schema_payload)
        
        # Find and delete relationships to case nodes
        # We match the target node and any connected node whose *_id is in case_node_ids
        query = f"""
        MATCH (n:`{label}` {{{id_prop}: $node_id}})-[r]-(connected)
        WHERE any(key IN keys(connected) WHERE key ENDS WITH '_id' AND connected[key] IN $case_node_ids)
        DELETE r
        RETURN count(r) as deleted_count
        """
        
        try:
            results = self.neo4j_client.execute_query(query, {
                "node_id": node_id,
                "case_node_ids": list(case_node_ids)
            })
            
            deleted_count = 0
            if results and len(results) > 0:
                deleted_count = results[0].get("deleted_count", 0)
            
            logger.info(f"Detached node {label}:{node_id} from case - deleted {deleted_count} relationships")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to detach node {label}:{node_id} from case: {e}")
            return 0

    def check_node_has_connections(self, label: str, node_id: str) -> bool:
        """Check if a node has any remaining connections in the KG.
        
        Args:
            label: Node label
            node_id: The node's *_id property value
            
        Returns:
            True if node has connections, False if orphaned
        """
        id_prop = get_id_prop_for_label(label, self.schema_payload)
        
        query = f"""
        MATCH (n:`{label}` {{{id_prop}: $node_id}})-[r]-()
        RETURN count(r) as connection_count
        """
        
        try:
            results = self.neo4j_client.execute_query(query, {"node_id": node_id})
            if results and len(results) > 0:
                return results[0].get("connection_count", 0) > 0
            return False
        except Exception as e:
            logger.warning(f"Failed to check connections for {label}:{node_id}: {e}")
            return True  # Assume connected to be safe

