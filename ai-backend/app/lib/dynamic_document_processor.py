import re
import json
import logging
import time
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from io import BytesIO
import mammoth
from crewai import LLM
from .neo4j_client import neo4j_client

logger = logging.getLogger(__name__)

@dataclass
class SchemaInfo:
    """Neo4j schema information"""
    node_labels: List[str]
    relationship_types: List[str]
    node_properties: Dict[str, List[str]]  # node_label -> [property_names]
    relationship_properties: Dict[str, List[str]]  # rel_type -> [property_names]
    property_keys: List[str]

@dataclass
class DocumentMetadata:
    """Metadata extracted from document analysis"""
    nodes: Dict[str, List[str]]  # node_type -> [property_names]
    relationships: Dict[str, Dict[str, Any]]  # rel_type -> {from_node, to_node, properties}

@dataclass
class ExtractedData:
    """Actual data extracted from document"""
    nodes: Dict[str, List[Dict[str, Any]]]  # node_type -> [node_instances]
    relationships: List[Dict[str, Any]]  # relationship instances

class DynamicDocumentProcessor:
    """AI-powered dynamic document processor"""
    
    def __init__(self):
        """Initialize the dynamic document processor with direct Neo4j integration"""
        self.llm = LLM(model="gpt-4o", temperature=0)
        logger.info("Dynamic document processor initialized with direct Neo4j integration")
    
    def get_neo4j_schema(self) -> SchemaInfo:
        """Query Neo4j to get existing schema information using direct Neo4j queries"""
        logger.info("Retrieving Neo4j schema using direct queries")
        
        try:
            # Use direct Neo4j queries for reliable schema retrieval
            logger.info("Using direct Neo4j queries for schema retrieval")
            
            # Get node labels
            node_labels_query = "CALL db.labels() YIELD label RETURN collect(label) as labels"
            node_result = neo4j_client.execute_query(node_labels_query)
            node_labels = node_result[0]['labels'] if node_result else []
            
            # Get relationship types  
            rel_types_query = "CALL db.relationshipTypes() YIELD relationshipType RETURN collect(relationshipType) as types"
            rel_result = neo4j_client.execute_query(rel_types_query)
            relationship_types = rel_result[0]['types'] if rel_result else []
            
            # Get property keys
            prop_keys_query = "CALL db.propertyKeys() YIELD propertyKey RETURN collect(propertyKey) as keys"
            prop_result = neo4j_client.execute_query(prop_keys_query)
            property_keys = prop_result[0]['keys'] if prop_result else []
            
            schema_info = SchemaInfo(
                node_labels=node_labels,
                relationship_types=relationship_types,
                node_properties={},  # Empty for now - could be populated later if needed
                relationship_properties={},  # Empty for now - could be populated later if needed
                property_keys=property_keys
            )
            
            logger.info(f"Schema retrieved: {len(node_labels)} node types, {len(relationship_types)} relationship types, {len(property_keys)} properties")
            return schema_info
            
        except Exception as e:
            logger.error(f"Error retrieving Neo4j schema: {e}")
            # Return empty schema as fallback
            return SchemaInfo(
                node_labels=[], 
                relationship_types=[], 
                node_properties={}, 
                relationship_properties={}, 
                property_keys=[]
            )
    
    def extract_document_text(self, file_content: bytes) -> str:
        """Extract text from DOCX file"""
        try:
            with BytesIO(file_content) as docx_stream:
                result = mammoth.extract_raw_text(docx_stream)
                return result.value
        except Exception as e:
            logger.error(f"Error extracting document text: {e}")
            raise
    
    def identify_document_nodes(self, document_text: str) -> Dict[str, List[str]]:
        """Step 2: Identify ALL possible nodes in the document"""
        
        prompt = f"""
DOCUMENT TO ANALYZE:
{document_text}

TASK: Identify ALL possible entity types (nodes) that exist in this document.

OUTPUT FORMAT (JSON only):
{{
  "NodeType1": ["property1", "property2", "property3"],
  "NodeType2": ["property1", "property2", "property3"],
  "NodeType3": ["property1", "property2"]
}}

INSTRUCTIONS:
1. Read through the ENTIRE document carefully
2. Identify EVERY distinct type of entity/object mentioned
3. For each entity type, list ALL properties/attributes that are mentioned for that type
4. Use PascalCase for node type names (e.g., "LegalCase", "Party", "LegalProvision")
5. Include an ID property for each node type (e.g., "case_id", "party_id", "provision_id")
6. Be comprehensive - don't miss any entity types, even if they seem minor
7. Examples of entity types might include: Cases, Parties, Provisions, Doctrines, Arguments, Allegations, Rulings, Relief, Evidence, Courts, Judges, Dates, Citations, etc.
8. Return ONLY the JSON, no other text
"""

        try:
            print("      🤖 Calling AI model for node identification...")
            logger.info("Calling LLM for node identification...")
            response = self.llm.call([{"role": "user", "content": prompt}])
            
            if not response:
                raise ValueError("Empty response from LLM for node identification")
                
            nodes_json = self._strip_json_codeblock(response)
            logger.debug(f"Nodes JSON preview: {nodes_json[:300]}...")
            
            try:
                result = json.loads(nodes_json)
                logger.info(f"Successfully identified {len(result)} node types")
                return result
            except json.JSONDecodeError as json_err:
                logger.error(f"JSON parsing failed for nodes. Raw response: {nodes_json}")
                raise ValueError(f"Invalid JSON response for nodes: {json_err}")
                
        except Exception as e:
            logger.error(f"Error identifying document nodes: {e}")
            # Return empty dict instead of raising
            logger.warning("Returning empty nodes due to error")
            return {}
    
    def identify_document_relationships(self, document_text: str, nodes: Dict[str, List[str]]) -> Dict[str, Dict[str, Any]]:
        """Step 3: Identify ALL possible relationships in the document"""
        
        node_types = list(nodes.keys())
        
        prompt = f"""
DOCUMENT TO ANALYZE:
{document_text}

IDENTIFIED NODE TYPES:
{', '.join(node_types)}

TASK: Identify ALL possible relationships that exist between entities in this document.

OUTPUT FORMAT (JSON only):
{{
  "RELATIONSHIP_TYPE1": {{
    "from_node": "NodeType1",
    "to_node": "NodeType2",
    "properties": ["prop1", "prop2"]
  }},
  "RELATIONSHIP_TYPE2": {{
    "from_node": "NodeType2", 
    "to_node": "NodeType3",
    "properties": ["prop1"]
  }}
}}

INSTRUCTIONS:
1. Read through the document and identify HOW entities relate to each other
2. Look for explicit connections, references, associations, and implicit relationships
3. Use UPPER_CASE_WITH_UNDERSCORES for relationship types (e.g., "HAS_PARTY", "CITES_PROVISION", "ALLEGES_AGAINST")
4. For each relationship, specify which node types it connects
5. List any properties that the relationship itself might have (dates, roles, types, etc.)
6. Be comprehensive - capture ALL relationships, not just obvious ones
7. Examples might include: HAS_PARTY, CITES_PROVISION, FILED_BY, DECIDED_BY, APPEALS_TO, REFERENCES, SUPPORTS, CONTRADICTS, etc.
8. Return ONLY the JSON, no other text
"""

        try:
            print("      🤖 Calling AI model for relationship identification...")
            logger.info("Calling LLM for relationship identification...")
            response = self.llm.call([{"role": "user", "content": prompt}])
            
            if not response:
                raise ValueError("Empty response from LLM for relationship identification")
                
            relationships_json = self._strip_json_codeblock(response)
            logger.debug(f"Relationships JSON preview: {relationships_json[:300]}...")
            
            try:
                result = json.loads(relationships_json)
                logger.info(f"Successfully identified {len(result)} relationship types")
                return result
            except json.JSONDecodeError as json_err:
                logger.error(f"JSON parsing failed for relationships. Raw response: {relationships_json}")
                raise ValueError(f"Invalid JSON response for relationships: {json_err}")
                
        except Exception as e:
            logger.error(f"Error identifying document relationships: {e}")
            # Return empty dict instead of raising
            logger.warning("Returning empty relationships due to error")
            return {}
    
    def align_with_existing_schema(self, nodes: Dict[str, List[str]], relationships: Dict[str, Dict[str, Any]], schema_info: SchemaInfo) -> Tuple[Dict[str, List[str]], Dict[str, Dict[str, Any]]]:
        """Step 4: Compare with existing schema and align naming/structure"""
        
        existing_schema_context = ""
        if schema_info.node_labels:
            existing_schema_context = f"""
EXISTING NEO4J SCHEMA:
Node Labels: {', '.join(schema_info.node_labels)}
Relationship Types: {', '.join(schema_info.relationship_types)}

Node Properties:
{json.dumps(schema_info.node_properties, indent=2)}

Relationship Properties:
{json.dumps(schema_info.relationship_properties, indent=2)}
"""
        
        prompt = f"""
{existing_schema_context}

DOCUMENT-DERIVED METADATA:
Nodes: {json.dumps(nodes, indent=2)}
Relationships: {json.dumps(relationships, indent=2)}

TASK: Align the document metadata with the existing schema while preserving new elements.

OUTPUT FORMAT (JSON only):
{{
  "aligned_nodes": {{
    "ExistingNodeType": ["prop1", "prop2"],
    "NewNodeType": ["prop1", "prop2"]
  }},
  "aligned_relationships": {{
    "EXISTING_RELATIONSHIP": {{
      "from_node": "NodeType1",
      "to_node": "NodeType2",
      "properties": ["prop1"]
    }},
    "NEW_RELATIONSHIP": {{
      "from_node": "NodeType3",
      "to_node": "NodeType4", 
      "properties": ["prop1"]
    }}
  }}
}}

ALIGNMENT RULES:
1. If a document node type is similar to an existing schema node, use the existing name
2. If a document relationship is similar to an existing schema relationship, use the existing name
3. Merge property lists - keep existing properties and add new ones from document
4. Preserve any completely new node types or relationships that don't exist in schema
5. Ensure node type names match exactly with existing schema where applicable
6. Ensure relationship type names match exactly with existing schema where applicable
7. Maintain consistency in naming conventions
8. Return ONLY the JSON, no other text
"""

        try:
            print("      🤖 Calling AI model for schema alignment...")
            logger.info("Calling LLM for schema alignment...")
            response = self.llm.call([{"role": "user", "content": prompt}])
            
            if not response:
                raise ValueError("Empty response from LLM for schema alignment")
                
            aligned_json = self._strip_json_codeblock(response)
            logger.debug(f"Alignment JSON preview: {aligned_json[:300]}...")
            
            try:
                aligned_dict = json.loads(aligned_json)
                logger.info("Successfully aligned schema with existing Neo4j structure")
            except json.JSONDecodeError as json_err:
                logger.error(f"JSON parsing failed for alignment. Raw response: {aligned_json}")
                raise ValueError(f"Invalid JSON response for alignment: {json_err}")
            
            return (
                aligned_dict.get("aligned_nodes", {}),
                aligned_dict.get("aligned_relationships", {})
            )
        except Exception as e:
            logger.error(f"Error aligning with existing schema: {e}")
            # Return original nodes/relationships instead of raising
            logger.warning("Returning original metadata due to alignment error")
            return (nodes, relationships)
    
    def chunk_document(self, document_text: str, chunk_size: int = 12000, overlap: int = 1000) -> List[str]:
        """Split document into overlapping chunks for processing"""
        if len(document_text) <= chunk_size:
            return [document_text]
        
        chunks = []
        start = 0
        
        while start < len(document_text):
            end = start + chunk_size
            
            # If this isn't the last chunk, try to break at a sentence or paragraph
            if end < len(document_text):
                # Look for a good break point (sentence ending)
                for i in range(end, max(start + chunk_size - 500, start), -1):
                    if document_text[i:i+2] in ['. ', '.\n', '!\n', '?\n']:
                        end = i + 1
                        break
            
            chunk = document_text[start:end]
            chunks.append(chunk)
            
            # Move start forward, accounting for overlap
            start = end - overlap
            if start >= len(document_text):
                break
                
        return chunks

    def extract_document_content(self, document_text: str, aligned_nodes: Dict[str, List[str]], aligned_relationships: Dict[str, Dict[str, Any]], test_mode: bool = False) -> ExtractedData:
        """Step 6: Extract actual content based on the aligned metadata using document batching"""
        
        metadata_context = f"""
EXTRACTION SCHEMA:
Nodes to extract: {json.dumps(aligned_nodes, indent=2)}
Relationships to extract: {json.dumps(aligned_relationships, indent=2)}
"""
        
        # Split document into chunks
        chunks = self.chunk_document(document_text)
        
        # Limit chunks for testing
        if test_mode:
            chunks = chunks[:1]  # Only process first chunk in test mode
            print(f"      🧪 TEST MODE: Processing only the first chunk ({len(chunks[0])} chars)...")
        else:
            print(f"      📄 Processing document in {len(chunks)} chunks...")
        
        # Process each chunk
        all_nodes = {}
        all_relationships = []
        
        for i, chunk in enumerate(chunks):
            print(f"      📝 Processing chunk {i+1}/{len(chunks)} ({len(chunk)} chars)...")
            
            prompt = f"""
{metadata_context}

DOCUMENT CHUNK TO EXTRACT FROM (Chunk {i+1}/{len(chunks)}):
{chunk}

TASK: Extract ALL instances of the specified entities and relationships from this document chunk.

OUTPUT FORMAT (JSON only):
{{
  "nodes": {{
    "NodeType1": [
      {{"case_id": "C0001", "case_name": "Example Case", "case_citation": "123 U.S. 456"}},
      {{"party_id": "P0001", "party_name": "Plaintiff Name", "role": "plaintiff"}}
    ],
    "NodeType2": [
      {{"forum_id": "F0001", "forum_name": "Supreme Court", "forum_type": "appellate"}}
    ]
  }},
  "relationships": [
    {{"type": "HEARD_IN", "from_id": "C0001", "from_type": "Case", "to_id": "F0001", "to_type": "Forum", "properties": {{}}}},
    {{"type": "INVOLVES", "from_id": "C0001", "from_type": "Case", "to_id": "P0001", "to_type": "Party", "properties": {{}}}}
  ]
}}

EXTRACTION REQUIREMENTS:
1. Extract EVERY instance of each node type from this chunk - don't miss any
2. CRITICAL: Use the EXACT IDs that appear in the document (e.g., C0001, F0001, P0001, etc.) - DO NOT generate new IDs
3. If the document shows relationships like "C0001 → F0001", use "C0001" and "F0001" as the actual node IDs
4. Fill in ALL available properties for each node based on document content
5. Create ALL relationships between nodes as specified in the schema
6. Only create relationships between nodes that exist in THIS chunk
7. Use exact node type names and relationship types from the schema
8. If a property value is not available, use null
9. Ensure all relationships reference valid node IDs that exist in the nodes section
10. CRITICAL: Output ALL relationships completely - do not truncate or add comments
11. Return ONLY complete, valid JSON with no comments or truncation
"""

            try:
                print(f"         🤖 Calling AI model for chunk {i+1}...")
                response = self.llm.call([{"role": "user", "content": prompt}])
                
                if not response:
                    print(f"         ⚠️ Empty response for chunk {i+1}, skipping...")
                    continue
                    
                content_json = self._strip_json_codeblock(response)
                
                try:
                    content_dict = json.loads(content_json)
                except json.JSONDecodeError as json_err:
                    print(f"         ❌ JSON parsing failed for chunk {i+1}, skipping...")
                    logger.error(f"JSON parsing failed for chunk {i+1}. Raw response: {content_json}")
                    continue
                
                # Merge nodes from this chunk
                chunk_nodes = content_dict.get("nodes", {})
                for node_type, nodes in chunk_nodes.items():
                    if node_type not in all_nodes:
                        all_nodes[node_type] = []
                    all_nodes[node_type].extend(nodes)
                
                # Add relationships from this chunk
                chunk_relationships = content_dict.get("relationships", [])
                all_relationships.extend(chunk_relationships)
                
                print(f"         ✅ Chunk {i+1}: {sum(len(nodes) for nodes in chunk_nodes.values())} nodes, {len(chunk_relationships)} relationships")
                
            except Exception as e:
                print(f"         ❌ Error processing chunk {i+1}: {e}")
                logger.error(f"Error processing chunk {i+1}: {e}")
                continue
        
        # Deduplicate nodes by ID
        print(f"      🔄 Deduplicating nodes across chunks...")
        deduplicated_nodes = {}
        for node_type, nodes in all_nodes.items():
            seen_ids = set()
            unique_nodes = []
            for node in nodes:
                node_id = node.get("node_id") or node.get(f"{node_type.lower()}_id", "unknown")
                if node_id not in seen_ids:
                    seen_ids.add(node_id)
                    unique_nodes.append(node)
            deduplicated_nodes[node_type] = unique_nodes
        
        # Deduplicate relationships
        print(f"      🔄 Deduplicating relationships across chunks...")
        seen_relationships = set()
        unique_relationships = []
        for rel in all_relationships:
            # Create a tuple for comparison
            rel_key = (rel.get("type"), rel.get("from_id"), rel.get("to_id"))
            if rel_key not in seen_relationships:
                seen_relationships.add(rel_key)
                unique_relationships.append(rel)
        
        total_nodes = sum(len(nodes) for nodes in deduplicated_nodes.values())
        print(f"      ✅ Final results: {total_nodes} unique nodes, {len(unique_relationships)} unique relationships")
        
        return ExtractedData(
            nodes=deduplicated_nodes,
            relationships=unique_relationships
        )
    
    def generate_cypher_queries(self, extracted_data: ExtractedData) -> List[str]:
        """Generate Cypher queries to import the extracted data"""
        queries = []
        
        # Generate node creation queries
        for node_type, nodes in extracted_data.nodes.items():
            if not nodes:
                continue
                
            # Determine the id property deterministically
            id_prop = self._determine_id_prop(node_type, nodes[0]) if nodes[0] else "id"
            
            for node in nodes:
                # Create MERGE query for each node
                properties = ", ".join([f"{k}: ${k}" for k in node.keys()])
                query = f"""
                MERGE (n:{node_type} {{{id_prop}: ${id_prop}}})
                SET n += {{{properties}}}
                """
                queries.append((query, node))
        
        # Generate relationship creation queries  
        for rel in extracted_data.relationships:
            rel_type = rel["type"]
            from_type = rel["from_type"]
            to_type = rel["to_type"]
            from_id = rel["from_id"]
            to_id = rel["to_id"]
            rel_props = rel.get("properties", {})
            
            # Try to find actual ID property names from the nodes
            from_id_prop = self._label_id_prop(from_type, extracted_data.nodes)
            to_id_prop = self._label_id_prop(to_type, extracted_data.nodes)
            
            query = f"""
            MATCH (a:{from_type} {{{from_id_prop}: $from_id}})
            MATCH (b:{to_type} {{{to_id_prop}: $to_id}})
            MERGE (a)-[r:{rel_type}]->(b)
            """
            
            params = {"from_id": from_id, "to_id": to_id}
            
            if rel_props:
                prop_sets = ", ".join([f"r.{k} = ${k}" for k in rel_props.keys()])
                query += f"\nSET {prop_sets}"
                params.update(rel_props)
            
            queries.append((query, params))
        
        return queries
    
    def test_neo4j_connection(self) -> bool:
        """Test Neo4j connectivity before executing queries"""
        try:
            print("      🔌 Testing Neo4j connection...")
            with neo4j_client.driver.session() as session:
                result = session.run("RETURN 1 as test")
                test_value = result.single()["test"]
                if test_value == 1:
                    print("      ✅ Neo4j connection successful")
                    return True
            return False
        except Exception as e:
            print(f"      ❌ Neo4j connection failed: {e}")
            logger.error(f"Neo4j connection test failed: {e}")
            return False

    def execute_individual_queries(self, queries: List[Tuple[str, Dict]]) -> bool:
        """Legacy execution: run one query per Cypher statement (kept for fallback)."""

        logger.info("Executing Cypher queries using individual execution (legacy)")

        # Connection test
        if not self.test_neo4j_connection():
            return False

        successful_queries = 0
        failed_queries = 0
        total = len(queries)

        print(f"      📝 Executing {total} Cypher queries (individual mode)...")

        for i, (query, params) in enumerate(queries):
            max_retries = 3
            retry_delay = 1
            for attempt in range(max_retries):
                try:
                    neo4j_client.execute_query(query, params)
                    successful_queries += 1
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Query {i+1} failed (attempt {attempt+1}), retrying in {retry_delay}s: {e}")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        logger.error(f"Query {i+1} failed after {max_retries} attempts: {e}")
                        failed_queries += 1

            if (i + 1) % 10 == 0:
                print(f"         📊 Progress: {i+1}/{total} queries executed")

        print(f"      ✅ Individual execution complete: {successful_queries} successful, {failed_queries} failed")
        logger.info(f"Individual execution completed: {successful_queries} successful, {failed_queries} failed")

        return failed_queries == 0

    # Maintain backwards-compatibility for existing callers
    execute_cypher_queries = execute_individual_queries  # type: ignore

    def execute_batched_queries(self, extracted_data: "ExtractedData") -> bool:
        """Execute Cypher write operations in efficient batches.

        Nodes are merged per label via UNWIND so that a single query can create/update
        hundreds of nodes at once.  Relationships are merged in groups keyed by
        (rel_type, from_type, to_type) to avoid large query strings while still
        leveraging batching.  Each MERGE/SET uses the `+=` operator so that only
        the supplied properties are updated – existing properties that are *not*
        in the incoming map remain untouched, satisfying the partial-update
        requirement.
        """
        # Ensure Neo4j is reachable first.
        if not self.test_neo4j_connection():
            return False

        try:
            # ------------------------
            # 1) Batch all node merges
            # ------------------------
            for node_type, nodes in extracted_data.nodes.items():
                if not nodes:
                    continue

                # Determine the id property deterministically
                id_prop = self._determine_id_prop(node_type, nodes[0]) if nodes[0] else "id"

                # Filter out any malformed rows missing the id property to prevent
                # ParameterMissing errors that previously occurred.
                valid_rows = [n for n in nodes if n.get(id_prop) is not None]
                if not valid_rows:
                    continue  # nothing to insert for this label

                print(f"      📝 Batching {len(valid_rows)} {node_type} nodes using {id_prop} property")
                batch_query = f"""
                UNWIND $rows AS row
                MERGE (n:{node_type} {{{id_prop}: row.{id_prop}}})
                SET   n += row
                RETURN count(n) as nodes_created
                """

                # Debug: Show sample data being inserted
                if valid_rows:
                    sample = valid_rows[0]
                    print(f"      🔍 Sample {node_type} data: {id_prop}={sample.get(id_prop, 'MISSING')}, keys={list(sample.keys())}")
                
                try:
                    result = neo4j_client.execute_query(batch_query, {"rows": valid_rows})
                    actual_count = result[0]["nodes_created"] if result else 0
                    print(f"      ✅ Actually created {actual_count} {node_type} nodes (attempted {len(valid_rows)})")
                    
                    # Verify a sample node exists
                    if valid_rows and actual_count > 0:
                        sample = valid_rows[0]
                        check_query = f"MATCH (n:{node_type} {{{id_prop}: $id_val}}) RETURN count(n) as count"
                        check_result = neo4j_client.execute_query(check_query, {"id_val": sample[id_prop]})
                        exists_count = check_result[0]["count"] if check_result else 0
                        print(f"      🔍 Verification: {node_type}({id_prop}={sample[id_prop]}) exists: {exists_count > 0}")
                except Exception as e:
                    print(f"      ❌ Failed to create {node_type} nodes: {e}")
                    logger.error(f"Node batch failed: {e}")
                    logger.error(f"Query: {batch_query}")
                    logger.error(f"Sample row: {valid_rows[0] if valid_rows else 'No rows'}")
                    raise

            # ---------------------------------
            # 2) Batch all relationship merges
            # ---------------------------------
            # Group relationships to keep each individual query manageable and to
            # guarantee that parameter names are consistent within a batch.
            print(f"\\n      📋 DEBUG: Actual node IDs created:")
            for node_type, nodes in extracted_data.nodes.items():
                if nodes:
                    id_prop = self._determine_id_prop(node_type, nodes[0])
                    sample_ids = [node.get(id_prop, 'MISSING') for node in nodes[:3]]  # First 3 IDs
                    print(f"      • {node_type}({id_prop}): {sample_ids}{'...' if len(nodes) > 3 else ''}")
            
            print(f"\\n      🔗 DEBUG: Relationship IDs being searched for:")
            rel_batches = {}
            for rel in extracted_data.relationships:
                if not rel.get("from_id") or not rel.get("to_id"):
                    print(f"      ⚠️ Skipping relationship with missing IDs: {rel}")
                    continue
                    
                # Debug: Show what relationship IDs we're trying to connect
                print(f"      🔗 Processing rel: {rel['type']} from_id={rel['from_id']} to_id={rel['to_id']}")
                    
                rel_type = rel["type"]
                from_type = rel["from_type"]
                to_type = rel["to_type"]

                # Resolve id properties for from/to nodes.
                from_id_prop = self._label_id_prop(from_type, extracted_data.nodes)
                to_id_prop = self._label_id_prop(to_type, extracted_data.nodes)

                key = (rel_type, from_type, to_type, from_id_prop, to_id_prop)
                if key not in rel_batches:
                    rel_batches[key] = []

                rel_batches[key].append({
                    "from_id":     rel["from_id"],
                    "to_id":       rel["to_id"],
                    "properties":  rel.get("properties", {})
                })

            for (rel_type, from_type, to_type, from_id_prop, to_id_prop), rows in rel_batches.items():
                if not rows:
                    continue

                print(f"      🔗 Batching {len(rows)} {rel_type} relationships ({from_type}.{from_id_prop} -> {to_type}.{to_id_prop})")
                logger.info(f"Relationship batch: {rel_type}, from_prop={from_id_prop}, to_prop={to_id_prop}, count={len(rows)}")

                # First, let's verify the nodes exist that we're trying to connect
                sample_row = rows[0]
                check_from_query = f"MATCH (a:{from_type} {{{from_id_prop}: $from_id}}) RETURN count(a) as count"
                check_to_query = f"MATCH (b:{to_type} {{{to_id_prop}: $to_id}}) RETURN count(b) as count"
                
                from_exists = neo4j_client.execute_query(check_from_query, {"from_id": sample_row["from_id"]})
                to_exists = neo4j_client.execute_query(check_to_query, {"to_id": sample_row["to_id"]})
                
                from_count = from_exists[0]["count"] if from_exists else 0
                to_count = to_exists[0]["count"] if to_exists else 0
                
                print(f"      🔍 Node check: {from_type}({from_id_prop}={sample_row['from_id']}) exists: {from_count > 0}")
                print(f"      🔍 Node check: {to_type}({to_id_prop}={sample_row['to_id']}) exists: {to_count > 0}")
                
                if from_count == 0 or to_count == 0:
                    print(f"      ❌ Cannot create {rel_type} relationships - missing nodes!")
                    continue
                
                # Execute the relationship creation with result counting
                enhanced_query = f"""
                UNWIND $rows AS row
                MATCH (a:{from_type} {{{from_id_prop}: row.from_id}})
                MATCH (b:{to_type}   {{{to_id_prop}:   row.to_id}})
                MERGE (a)-[r:{rel_type}]->(b)
                WITH r, row
                FOREACH (k IN keys(row.properties) | SET r[k] = row.properties[k])
                RETURN count(r) as relationships_created
                """
                
                result = neo4j_client.execute_query(enhanced_query, {"rows": rows})
                actual_count = result[0]["relationships_created"] if result else 0
                print(f"      ✅ Actually created {actual_count} {rel_type} relationships (attempted {len(rows)})")

            return True

        except Exception as e:
            logger.error(f"Batched query execution failed: {e}")
            return False

    def process_document(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """Main processing pipeline with improved multi-step approach"""
        try:
            print(f"\n🚀 Starting AI-powered document processing for: {filename}")
            
            # Step 1: Get existing Neo4j schema
            print("📊 Step 1/8: Analyzing existing Neo4j schema...")
            logger.info("Step 1: Getting Neo4j schema...")
            schema_info = self.get_neo4j_schema()
            print(f"   Found {len(schema_info.node_labels)} node types, {len(schema_info.relationship_types)} relationship types")
            
            # Step 2: Extract document text
            print("📄 Step 2/8: Extracting document text...")
            logger.info("Step 2: Extracting document text...")
            document_text = self.extract_document_text(file_content)
            print(f"   Extracted {len(document_text)} characters from document")
            
            # Detect case-structured document
            cases = self._split_into_cases(document_text)
            if cases:
                print(f"🏛️  Detected {len(cases)} cases in document, processing one at a time...")
                total_nodes = total_rels = 0
                for case_name, case_body in cases:
                    # Refresh schema before each case to ensure alignment is always current
                    print(f"\n🔄 Refreshing Neo4j schema before processing '{case_name}'...")
                    current_schema_info = self.get_neo4j_schema()
                    case_result = self._process_single_case(case_body, case_name, current_schema_info)
                    total_nodes += case_result["nodes_added"]
                    total_rels += case_result["relationships_added"]

                return {
                    "success": True,
                    "filename": filename,
                    "cases_processed": len(cases),
                    "total_nodes_added": total_nodes,
                    "total_relationships_added": total_rels,
                    "message": f"Processed {len(cases)} cases successfully"
                }
            
            # Step 3: Identify ALL possible nodes in document
            print("🔍 Step 3/8: Using AI to identify all possible nodes...")
            logger.info("Step 3: Identifying all possible nodes...")
            document_nodes = self.identify_document_nodes(document_text)
            print(f"   AI identified {len(document_nodes)} different node types")
            
            # Step 4: Identify ALL possible relationships in document
            print("🔗 Step 4/8: Using AI to identify all possible relationships...")
            logger.info("Step 4: Identifying all possible relationships...")
            document_relationships = self.identify_document_relationships(document_text, document_nodes)
            print(f"   AI identified {len(document_relationships)} different relationship types")
            
            # Step 5: Align with existing schema
            print("⚖️  Step 5/8: Aligning with existing Neo4j schema...")
            logger.info("Step 5: Aligning with existing Neo4j schema...")
            aligned_nodes, aligned_relationships = self.align_with_existing_schema(
                document_nodes, document_relationships, schema_info
            )
            print(f"   Schema alignment complete - {len(aligned_nodes)} node types, {len(aligned_relationships)} relationship types")
            
            # Step 6: Extract actual content using aligned metadata
            print("📝 Step 6/8: Using AI to extract actual content from document...")
            logger.info("Step 6: Extracting document content...")
            extracted_data = self.extract_document_content(document_text, aligned_nodes, aligned_relationships, test_mode=False)
            total_nodes = sum(len(nodes) for nodes in extracted_data.nodes.values())
            print(f"   Extracted {total_nodes} total nodes and {len(extracted_data.relationships)} relationships")
            
            # Step 7: Generate Cypher queries
            print("🔧 Step 7/8: Generating Cypher queries for Neo4j...")
            logger.info("Step 7: Generating Cypher queries...")
            queries = self.generate_cypher_queries(extracted_data)
            print(f"   Generated {len(queries)} Cypher queries")
            
            # Step 8: Execute queries
            print("💾 Step 8/8: Executing queries to import into Neo4j...")
            logger.info("Step 8: Executing Cypher queries using batched approach...")

            # Prefer the new batched execution path for performance & reliability
            success = self.execute_batched_queries(extracted_data)

            # Fallback to legacy per-query execution if batching fails for any reason
            if not success:
                logger.warning("Batched execution failed – falling back to individual queries")
                success = self.execute_individual_queries(queries)
            
            print(f"   {'✅ Successfully' if success else '❌ Failed to'} import data into Neo4j")
            
            print(f"\n🎉 Document processing complete for {filename}!")
            print(f"📊 Final Summary:")
            print(f"   • Total nodes extracted: {total_nodes}")
            print(f"   • Total relationships extracted: {len(extracted_data.relationships)}")
            print(f"   • Cypher queries executed: {len(queries)}")
            print(f"   • Processing status: {'SUCCESS' if success else 'FAILED'}")
            
            # Return processing results
            return {
                "success": success,
                "filename": filename,
                "schema_info": {
                    "existing_nodes": schema_info.node_labels,
                    "existing_relationships": schema_info.relationship_types
                },
                "document_analysis": {
                    "identified_nodes": document_nodes,
                    "identified_relationships": document_relationships,
                    "aligned_nodes": aligned_nodes,
                    "aligned_relationships": aligned_relationships
                },
                "extracted_counts": {
                    "nodes": {k: len(v) for k, v in extracted_data.nodes.items()},
                    "relationships": len(extracted_data.relationships)
                },
                "queries_executed": len(queries)
            }
            
        except Exception as e:
            logger.error(f"Error processing document {filename}: {e}")
            return {
                "success": False,
                "filename": filename,
                "error": str(e)
            }

    def _strip_json_codeblock(self, text: str) -> str:
        """Remove markdown ```json ... ``` and ``` ... ``` wrappers if present."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            # Remove first line (``` or ```json)
            lines = cleaned.split('\n')
            # Drop the opening delimiter
            if lines[0].strip().startswith("```"):
                lines = lines[1:]
            # Drop trailing delimiter if exists on last line
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        return cleaned

    def _split_into_cases(self, document_text: str) -> List[Tuple[str, str]]:
        """Return list of (case_name, case_text).

        The function looks for headings that start with "Case:" or "CASE:" on
        their own line.  Everything until the next heading (or EOF) is treated
        as that case's section.  If no headings are found, returns an empty
        list so the caller can fall back to whole-document processing.
        """
        pattern = re.compile(r"^\s*(?:Case|CASE)\s*[:\-]\s*(.+)$", re.MULTILINE)
        matches = list(pattern.finditer(document_text))
        if not matches:
            return []

        cases: List[Tuple[str, str]] = []
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(document_text)
            case_name = m.group(1).strip()
            case_body = document_text[start:end].strip()
            cases.append((case_name, case_body))
        return cases

    def _process_single_case(self, case_body: str, case_name: str, schema_info: "SchemaInfo") -> Dict[str, Any]:
        """Run the full 8-step pipeline on a single case body."""
        print(f"\n📂 Processing case: {case_name}")
        # Steps 3-6 are redone per case using the existing helpers.
        # Identify nodes & relationships in this case only.
        document_nodes = self.identify_document_nodes(case_body)
        document_relationships = self.identify_document_relationships(case_body, document_nodes)

        aligned_nodes, aligned_relationships = self.align_with_existing_schema(
            document_nodes, document_relationships, schema_info
        )

        extracted_data = self.extract_document_content(case_body, aligned_nodes, aligned_relationships, test_mode=False)
        node_count = sum(len(v) for v in extracted_data.nodes.values())
        rel_count = len(extracted_data.relationships)
        print(f"      • Case extraction: {node_count} nodes, {rel_count} relationships")

        # Generate and write queries (batched → fallback).
        success = self.execute_batched_queries(extracted_data)
        if not success:
            queries = self.generate_cypher_queries(extracted_data)
            success = self.execute_individual_queries(queries)

        status = "✅" if success else "❌"
        print(f"{status} {case_name} case processed and added to Neo4j successfully!  (nodes={node_count}, rels={rel_count})")
        return {"success": success, "nodes_added": node_count, "relationships_added": rel_count}

    def _determine_id_prop(self, label: str, sample_row: Dict[str, Any]) -> str:
        """Return the property key that uniquely identifies a node.

        Preference order:
        1. <label_lower>_id  (e.g. doctrine_id)
        2. First key ending with '_id'
        3. First key in the dict (fallback – maintains previous behaviour)
        """
        preferred = f"{label.lower()}_id"
        if preferred in sample_row:
            return preferred
        for k in sample_row.keys():
            if k.endswith("_id"):
                return k
        return next(iter(sample_row))

    def _label_id_prop(self, label: str, data_nodes: Dict[str, List[Dict[str, Any]]]) -> str:
        """Return the identifier property for a label using available data or convention."""
        if label in data_nodes and data_nodes[label]:
            return self._determine_id_prop(label, data_nodes[label][0])
        default_prop = f"{label.lower()}_id"
        return default_prop

# Global instance
dynamic_processor = DynamicDocumentProcessor() 