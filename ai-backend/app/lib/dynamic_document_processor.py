import re
import json
import textwrap
import logging
import time
import uuid
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
5. Include identifying properties for each node type
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
        """Step 3: Identify ALL possible relationships in the document (canonical only)"""

        node_types = list(nodes.keys())

        prompt = textwrap.dedent(f"""
            DOCUMENT TO ANALYZE:
            {document_text}

            IDENTIFIED NODE TYPES:
            {', '.join(node_types)}

            TASK: Identify ALL possible relationships that exist between entities in this document.
            Return ONLY one canonical relationship direction and type per node-type pair. Do NOT include inverse variants.

            OUTPUT FORMAT (JSON only):
            {{
            "RELATIONSHIP_TYPE1": {{
                "from_node": "NodeType1",
                "to_node": "NodeType2",
                "properties": ["prop1", "prop2"]
            }},
            "ANOTHER_RELATIONSHIP": {{
                "from_node": "NodeTypeA",
                "to_node": "NodeTypeB",
                "properties": ["propX"]
            }}
            }}

            INSTRUCTIONS:
            1. Read through the document and identify HOW entities relate to each other
            2. Look for explicit connections, references, associations, and implicit relationships
            3. Use UPPER_CASE_WITH_UNDERSCORES for relationship types (e.g., "HAS_PARTY", "CITES_PROVISION")
            4. For each relationship, specify which node types it connects
            5. Choose a single canonical direction/type per node-type pair. Do NOT include inverse variants (e.g., use ADDRESSES, not ADDRESSED_BY).
            6. List any properties that the relationship itself might have (dates, roles, types, etc.)
            7. Be comprehensive - capture ALL relationships, not just obvious ones
            8. Return ONLY the JSON, no other text
        """).replace("{", "{{").replace("}", "}}")  # escape braces inside the f-string

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
            logger.warning("Returning empty relationships due to error")
            return {}
    

    def align_with_existing_schema(
        self,
        nodes: Dict[str, List[str]],
        relationships: Dict[str, Dict[str, Any]],
        schema_info: "SchemaInfo",
        relationship_constraints: Dict[str, List[str]] = None
    ) -> Tuple[Dict[str, List[str]], Dict[str, Dict[str, Any]]]:
        """Step 4: Compare with existing schema and align naming/structure (canonical only)"""

        # Build optional schema context
        existing_schema_context = ""
        if getattr(schema_info, "node_labels", None):
            existing_schema_context = textwrap.dedent(f"""
                EXISTING NEO4J SCHEMA:
                Node Labels: {', '.join(schema_info.node_labels)}
                Relationship Types: {', '.join(schema_info.relationship_types)}
            """).strip()

        # Build optional relationship constraints context
        constraints_context = ""
        if relationship_constraints:
            lines = ["RELATIONSHIP CONSTRAINTS (MUST USE THESE WHEN AVAILABLE):"]
            for node_pair, rel_types in relationship_constraints.items():
                lines.append(f"{node_pair}: {', '.join(rel_types)}")
            constraints_context = "\n".join(lines)

        # Keep the JSON example in a separate plain string to avoid f-string brace escaping
        output_format_block = """{
    "aligned_nodes": {
        "ExistingNodeType": ["prop1", "prop2"],
        "NewNodeType": ["prop1", "prop2"]
    },
    "aligned_relationships": {
        "EXISTING_RELATIONSHIP": {
        "from_node": "NodeType1",
        "to_node": "NodeType2",
        "properties": ["prop1"]
        },
        "NEW_RELATIONSHIP": {
        "from_node": "NodeType3",
        "to_node": "NodeType4",
        "properties": ["prop1"]
        }
    }
    }"""

        prompt = textwrap.dedent(f"""
            {existing_schema_context}

            {constraints_context}

            DOCUMENT-DERIVED METADATA:
            Nodes: {json.dumps(nodes, indent=2)}
            Relationships: {json.dumps(relationships, indent=2)}

            TASK: Align the document metadata with the existing schema while preserving new elements.

            CRITICAL: When creating relationships between node types, you MUST check the RELATIONSHIP CONSTRAINTS section above. If a constraint exists for the node type pair, you MUST use EXACTLY one of the listed relationship types and choose ONE canonical direction. Do NOT include inverse variants or create alternate names.

            OUTPUT FORMAT (JSON only):
            {output_format_block}

            ALIGNMENT RULES:
            1. If a document node type is similar to an existing schema node, use the existing name.
            2. MANDATORY: Check RELATIONSHIP CONSTRAINTS first. If a constraint exists for the node type pair, you MUST use EXACTLY one of the listed relationship types and a single canonical direction (no inverses).
            3. If a document relationship is similar to an existing schema relationship, use the existing name.
            4. Merge property lists - keep existing properties and add new ones from the document.
            5. Preserve any completely new node types or relationships that don't exist in the schema AND are not constrained by the RELATIONSHIP CONSTRAINTS.
            6. Ensure node type names match exactly with the existing schema where applicable.
            7. Ensure relationship type names match exactly with the existing schema where applicable.
            8. Maintain consistency in naming conventions.
            9. Return ONLY the JSON, no other text.
        """).strip()

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
            logger.warning("Returning original metadata due to alignment error")
            return (nodes, relationships)

    
    def _inject_inverse_relationships(self, relationships: List[Dict[str, Any]], aligned_relationships: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Deprecated: no longer generate inverse relationships. Return input as-is."""
        return relationships
    
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

    def _normalize_node_properties(self, node_type: str, node: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize node property keys by removing the node-type prefix.

        Rules:
        - If a property starts with "<label>_" (label in snake_case), strip the prefix.
        - EXCEPT if the suffix is exactly "id" or "upload_code"; keep the prefixed form
          (e.g., keep "case_id", "case_upload_code").
        - If the unprefixed key already exists, prefer the unprefixed key and drop the prefixed one.
        """
        try:
            import re
            # Convert label (e.g., "Case") to snake_case ("case") to compute the prefix
            snake_label = re.sub(r'(?<!^)(?=[A-Z])', '_', node_type).lower()
            prefix = f"{snake_label}_"

            # Work on a copy to avoid mutating while iterating
            updated_node: Dict[str, Any] = dict(node)

            for key, value in list(node.items()):
                if not isinstance(key, str):
                    continue
                if not key.startswith(prefix):
                    continue

                suffix = key[len(prefix):]
                # Preserve ids and upload_code with prefix
                if suffix in ("id", "upload_code"):
                    continue

                # Compute unprefixed key
                unprefixed_key = suffix

                # If unprefixed key already present, drop the prefixed duplicate
                if unprefixed_key in updated_node:
                    updated_node.pop(key, None)
                    continue

                # Move value to unprefixed key and drop prefixed key
                updated_node[unprefixed_key] = value
                updated_node.pop(key, None)

            return updated_node
        except Exception:
            # On any error, return original node unchanged
            return node

    def extract_document_content(
    self,
    document_text: str,
    aligned_nodes: Dict[str, List[str]],
    aligned_relationships: Dict[str, Dict[str, Any]],
    test_mode: bool = False
    ) -> "ExtractedData":
        """Step 6: Extract actual content based on the aligned metadata using document batching"""

        metadata_context = textwrap.dedent(f"""
            EXTRACTION SCHEMA:
            Nodes to extract: {json.dumps(aligned_nodes, indent=2)}
            Relationships to extract: {json.dumps(aligned_relationships, indent=2)}
        """).strip()

        # Predefine JSON example blocks to avoid f-string brace issues
        output_format_block = """{
    "nodes": {
        "EntityType1": [
        {"property1": "value1", "property2": "value2", "property3": "value3"},
        {"property1": "value1", "property2": "value2"}
        ],
        "EntityType2": [
        {"property1": "value1", "property2": "value2"}
        ]
    },
    "relationships": [
        {"type": "RELATIONSHIP_TYPE", "from_id": "identifying_value_of_source_entity", "from_type": "EntityType1", "to_id": "identifying_value_of_target_entity", "to_type": "EntityType2", "properties": {"rel_property": "value"}},
        {"type": "ANOTHER_RELATIONSHIP", "from_id": "another_identifying_value", "from_type": "EntityType1", "to_id": "target_identifying_value", "to_type": "EntityType2", "properties": {}}
    ]
    }"""

        example_block = """{
    "nodes": {
        "Case": [
        {"case_name": "Smith v. Jones", "case_citation": "123 F.3d 456", "year": "2020"},
        {"case_name": "Doe v. Roe", "court": "Supreme Court"}
        ],
        "Party": [
        {"party_name": "Smith", "role": "plaintiff"},
        {"party_name": "Jones", "role": "defendant"}
        ]
    },
    "relationships": [
        {"type": "INVOLVES", "from_id": "Smith v. Jones", "from_type": "Case", "to_id": "Smith", "to_type": "Party", "properties": {}},
        {"type": "INVOLVES", "from_id": "Smith v. Jones", "from_type": "Case", "to_id": "Jones", "to_type": "Party", "properties": {}}
    ]
    }"""

        # Split document into chunks
        chunks = self.chunk_document(document_text)

        # Limit chunks for testing
        if test_mode:
            chunks = chunks[:1]  # Only process first chunk in test mode
            print(f"      🧪 TEST MODE: Processing only the first chunk ({len(chunks[0])} chars)...")
        else:
            print(f"      📄 Processing document in {len(chunks)} chunks...")

        # Process each chunk
        all_nodes: Dict[str, List[Dict[str, Any]]] = {}
        all_relationships: List[Dict[str, Any]] = []

        for i, chunk in enumerate(chunks):
            print(f"      📝 Processing chunk {i+1}/{len(chunks)} ({len(chunk)} chars)...")

            prompt = textwrap.dedent(f"""
                {metadata_context}

                DOCUMENT CHUNK TO EXTRACT FROM (Chunk {i+1}/{len(chunks)}):
                {chunk}

                TASK: Extract ALL instances of the specified entities and relationships from this document chunk.

                OUTPUT FORMAT (JSON only):
                {output_format_block}

                EXAMPLE (for reference only - use actual document content):
                {example_block}

                EXTRACTION REQUIREMENTS:
                1. Extract EVERY instance of each node type from this chunk - don't miss any
                2. Include any document-provided ID/code fields present in the text (e.g., keys ending with "_id" or exactly "id"/"_id"). Do NOT invent IDs; only include IDs that appear in the document content.
                3. Extract ALL available properties for each node based on document content - property names should match what's actually in the document
                4. For relationships, use identifying values (like names, titles, citations, or document-provided IDs) as from_id and to_id values - these will be automatically mapped to UUIDs later
                5. Create ALL relationships between nodes as specified in the schema
                6. Only create relationships between nodes that exist in THIS chunk
                7. Use exact node type names and relationship types from the schema (canonical only; do NOT output inverse variants)
                8. If a property value is not available, use null
                9. Ensure relationship from_id/to_id values match actual identifying properties of the referenced nodes
                10. CRITICAL: Output ALL relationships completely - do not truncate or add comments
                11. Return ONLY complete, valid JSON with no comments or truncation
            """).strip()

            try:
                print(f"         🤖 Calling AI model for chunk {i+1}...")
                response = self.llm.call([{"role": "user", "content": prompt}])

                if not response:
                    print(f"         ⚠️ Empty response for chunk {i+1}, skipping...")
                    continue

                content_json = self._strip_json_codeblock(response)

                try:
                    content_dict = json.loads(content_json)
                except json.JSONDecodeError:
                    print(f"         ❌ JSON parsing failed for chunk {i+1}, skipping...")
                    logger.error(f"JSON parsing failed for chunk {i+1}. Raw response: {content_json}")
                    continue

                # Merge nodes from this chunk (normalizing property keys)
                chunk_nodes = content_dict.get("nodes", {})
                for node_type, node_list in chunk_nodes.items():
                    if node_type not in all_nodes:
                        all_nodes[node_type] = []
                    for node in node_list:
                        normalized_node = self._normalize_node_properties(node_type, node)
                        all_nodes[node_type].append(normalized_node)

                # Add relationships from this chunk
                chunk_relationships = content_dict.get("relationships", [])
                all_relationships.extend(chunk_relationships)

                print(f"         ✅ Chunk {i+1}: {sum(len(v) for v in chunk_nodes.values())} nodes, {len(chunk_relationships)} relationships")

            except Exception as e:
                print(f"         ❌ Error processing chunk {i+1}: {e}")
                logger.error(f"Error processing chunk {i+1}: {e}")
                continue

        # Summarize relationship types detected (canonical only)
        rel_types_summary: Dict[str, int] = {}
        for rel in all_relationships:
            rel_type = rel.get("type", "UNKNOWN")
            rel_types_summary[rel_type] = rel_types_summary.get(rel_type, 0) + 1
        print(f"      📋 Relationship types (canonical): {dict(sorted(rel_types_summary.items()))}")

        # First deduplicate within document to avoid duplicate work
        print(f"      🔄 Deduplicating nodes within document...")
        deduplicated_nodes = self._deduplicate_nodes_by_properties(all_nodes)

        # Assign UUIDs to all nodes with upload_code-based deduplication
        print(f"      🔑 Assigning UUIDs with upload_code deduplication...")

        # Track deduplication stats
        self._reused_count = 0
        self._new_count = 0

        id_mapping = self._assign_uuids_to_nodes(deduplicated_nodes)

        # Count reused vs new UUIDs
        total_nodes = sum(len(v) for v in deduplicated_nodes.values())
        print(f"      📊 UUID Assignment Summary: {total_nodes} nodes processed ({self._reused_count} reused, {self._new_count} new)")
        print(f"      📋 ID Mapping contains {len(id_mapping)} entries for relationship processing")

        # Update relationships to use UUID references
        print(f"      🔗 Mapping relationships to use UUID references...")
        print(f"      📋 Processing {len(all_relationships)} relationships:")
        for j, rel in enumerate(all_relationships[:3]):  # Show first 3 relationships
            print(f"         Rel {j+1}: {rel.get('type')} from_id='{rel.get('from_id')}' to_id='{rel.get('to_id')}'")
        if len(all_relationships) > 3:
            print(f"         ... and {len(all_relationships) - 3} more")

        updated_relationships = self._map_relationships_to_uuids(all_relationships, id_mapping)

        # Deduplicate relationships within document and against Neo4j
        print(f"      🔄 Deduplicating relationships...")
        unique_relationships = self._deduplicate_relationships(updated_relationships, deduplicated_nodes)

        total_nodes = sum(len(v) for v in deduplicated_nodes.values())
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
        # Track created relationships when falling back
        try:
            self._rel_created_count
        except AttributeError:
            self._rel_created_count = 0

        print(f"      📝 Executing {total} Cypher queries (individual mode)...")

        for i, (query, params) in enumerate(queries):
            max_retries = 3
            retry_delay = 1
            for attempt in range(max_retries):
                try:
                    neo4j_client.execute_query(query, params)
                    successful_queries += 1
                    # Heuristic: count relationship merges (dedup ensures new)
                    if "MERGE (a)-[r:" in query:
                        self._rel_created_count += 1
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
            # Track counts for summary
            self._node_created_total = 0
            self._node_matched_total = 0
            self._rel_created_count = 0
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
                ON CREATE SET n += row, n.__created__ = true
                ON MATCH  SET n += row
                WITH n, coalesce(n.__created__, false) AS was_created
                REMOVE n.__created__
                RETURN sum(CASE WHEN was_created THEN 1 ELSE 0 END) AS created,
                       sum(CASE WHEN was_created THEN 0 ELSE 1 END) AS matched
                """

                # Debug: Show sample data being inserted
                if valid_rows:
                    sample = valid_rows[0]
                    print(f"      🔍 Sample {node_type} data: {id_prop}={sample.get(id_prop, 'MISSING')}, keys={list(sample.keys())}")
                
                try:
                    result = neo4j_client.execute_query(batch_query, {"rows": valid_rows})
                    created = result[0]["created"] if result else 0
                    matched = result[0]["matched"] if result else 0
                    self._node_created_total += created
                    self._node_matched_total += matched
                    print(f"      ✅ Node MERGE results for {node_type}: created={created}, matched={matched} (attempted {len(valid_rows)})")
                    
                    # Verify a sample node exists
                    if valid_rows and created > 0:
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
            print(f"\n      📋 DEBUG: Actual node IDs created:")
            for node_type, nodes in extracted_data.nodes.items():
                if nodes:
                    id_prop = self._determine_id_prop(node_type, nodes[0])
                    sample_ids = [node.get(id_prop, 'MISSING') for node in nodes[:3]]  # First 3 IDs
                    print(f"      • {node_type}({id_prop}): {sample_ids}{'...' if len(nodes) > 3 else ''}")
            
            print(f"\n      🔗 DEBUG: Relationship IDs being searched for:")
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

            rel_created_total = 0
            rel_matched_total = 0
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
                ON CREATE SET r.__created__ = true
                WITH r, row, coalesce(r.__created__, false) AS was_created
                FOREACH (k IN keys(row.properties) | SET r[k] = row.properties[k])
                REMOVE r.__created__
                RETURN sum(CASE WHEN was_created THEN 1 ELSE 0 END) AS created,
                       sum(CASE WHEN was_created THEN 0 ELSE 1 END) AS matched
                """
                
                result = neo4j_client.execute_query(enhanced_query, {"rows": rows})
                created = result[0]["created"] if result else 0
                matched = result[0]["matched"] if result else 0
                print(f"      ✅ Relationship MERGE results for {rel_type}: created={created}, matched={matched} (attempted {len(rows)})")
                rel_created_total += created
                rel_matched_total += matched

            # Save for summary reporting
            self._rel_created_count = rel_created_total
            self._rel_matched_count = rel_matched_total

            return True

        except Exception as e:
            logger.error(f"Batched query execution failed: {e}")
            return False

    def process_document(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """Main processing pipeline with improved multi-step approach"""
        # Optional quiet mode to suppress verbose prints and only log summaries
        quiet = False
        try:
            import os
            quiet_env = os.getenv("LEXON_UPLOAD_QUIET", "0")
            quiet = str(quiet_env).lower() in ("1", "true", "yes", "on")
        except Exception:
            quiet = False

        original_print = None
        try:
            import builtins  # type: ignore
            original_print = builtins.print
            if quiet:
                # Suppress output entirely when explicitly requested
                builtins.print = lambda *args, **kwargs: None  # type: ignore
            else:
                # Ensure all prints flush immediately for real-time IDE output
                def _realtime_print(*args, **kwargs):  # type: ignore
                    kwargs.setdefault("flush", True)
                    return original_print(*args, **kwargs)
                builtins.print = _realtime_print  # type: ignore

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
                total_reused = total_new = 0
                for case_name, case_body in cases:
                    # Refresh schema before each case to ensure alignment is always current
                    print(f"\n🔄 Refreshing Neo4j schema before processing '{case_name}'...")
                    current_schema_info = self.get_neo4j_schema()
                    case_result = self._process_single_case(case_body, case_name, current_schema_info)
                    total_nodes += case_result["nodes_added"]
                    total_rels += case_result["relationships_added"]
                    total_reused += case_result.get("reused_count", 0)
                    total_new += case_result.get("new_count", 0)

                # Update property mappings after successful multi-case import
                self._update_property_mappings_after_import()

                summary = {
                    "success": True,
                    "filename": filename,
                    "cases_processed": len(cases),
                    "total_nodes_added": total_nodes,
                    "total_relationships_added": total_rels,
                    "uuid_reused": total_reused,
                    "uuid_new": total_new,
                    "message": f"Processed {len(cases)} cases successfully"
                }

                # Log concise summary
                logger.info(
                    f"Upload summary: cases={summary['cases_processed']} nodes_added={summary['total_nodes_added']} "
                    f"rels_added={summary['total_relationships_added']} uuid_reused={summary['uuid_reused']} uuid_new={summary['uuid_new']}"
                )
                return summary
            
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
            
            # Step 5: Extract relationship constraints from existing data
            print("🔗 Step 5/8: Extracting relationship constraints from Neo4j...")
            relationship_constraints = self._extract_relationship_constraints()
            
            # Step 6: Align with existing schema using constraints
            print("⚖️  Step 6/8: Aligning with existing Neo4j schema...")
            logger.info("Step 6: Aligning with existing Neo4j schema...")
            aligned_nodes, aligned_relationships = self.align_with_existing_schema(
                document_nodes, document_relationships, schema_info, relationship_constraints
            )
            print(f"   Schema alignment complete - {len(aligned_nodes)} node types, {len(aligned_relationships)} relationship types")

            # Persist relationship constraints for future runs
            try:
                self._save_relationship_constraints(relationship_constraints)
            except Exception as e:
                logger.warning(f"Could not persist relationship constraints: {e}")
            
            # Step 7: Extract actual content using aligned metadata
            print("📝 Step 7/8: Using AI to extract actual content from document...")
            logger.info("Step 6: Extracting document content...")
            extracted_data = self.extract_document_content(document_text, aligned_nodes, aligned_relationships, test_mode=False)
            total_nodes = sum(len(v) for v in extracted_data.nodes.values())
            print(f"   Extracted {total_nodes} total nodes and {len(extracted_data.relationships)} relationships")
            
            # Step 7: Generate Cypher queries
            print("🔧 Step 8/9: Generating Cypher queries for Neo4j...")
            logger.info("Step 7: Generating Cypher queries...")
            queries = self.generate_cypher_queries(extracted_data)
            print(f"   Generated {len(queries)} Cypher queries")
            
            # Step 8: Execute queries
            print("💾 Step 9/9: Executing queries to import into Neo4j...")
            logger.info("Step 8: Executing Cypher queries using batched approach...")

            # Prefer the new batched execution path for performance & reliability
            success = self.execute_batched_queries(extracted_data)

            # Fallback to legacy per-query execution if batching fails for any reason
            if not success:
                logger.warning("Batched execution failed – falling back to individual queries")
                success = self.execute_individual_queries(queries)
            
            print(f"   {'✅ Successfully' if success else '❌ Failed to'} import data into Neo4j")
            
            # Concise summary logging (nodes new vs reused captured from _assign_uuids_to_nodes)
            logger.info(
                f"Upload summary: file='{filename}' nodes_total={total_nodes} rels_total={len(extracted_data.relationships)} "
                f"uuid_reused={getattr(self, '_reused_count', 0)} uuid_new={getattr(self, '_new_count', 0)} "
                f"nodes_created={getattr(self, '_node_created_total', 0)} nodes_matched={getattr(self, '_node_matched_total', 0)} "
                f"rels_created={getattr(self, '_rel_created_count', 0)} rels_matched={getattr(self, '_rel_matched_count', 0)} "
                f"success={success}"
            )
            
            # Update property mappings and generate embeddings after successful import
            if success:
                try:
                    # 1) Update property mappings (existing behavior)
                    self._update_property_mappings_after_import()
                except Exception as e:
                    logger.warning(f"Property mappings update failed: {e}")

                try:
                    # 2) Generate embeddings for selected properties on imported nodes
                    print("🧠 Generating embeddings for imported nodes...")
                    from app.lib.embeddings import generate_embeddings_for_nodes
                    embedding_ok = generate_embeddings_for_nodes(extracted_data.nodes)
                    print(
                        f"   • Embeddings generation: {'SUCCESS' if embedding_ok else 'FAILED'}"
                    )
                except Exception as e:
                    logger.warning(f"Embedding generation step failed: {e}")
            
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
                "queries_executed": len(queries),
                "uuid_reused": getattr(self, "_reused_count", 0),
                "uuid_new": getattr(self, "_new_count", 0),
            }
            
        except Exception as e:
            logger.error(f"Error processing document {filename}: {e}")
            return {
                "success": False,
                "filename": filename,
                "error": str(e)
            }
        finally:
            # Restore printing behavior
            if original_print is not None:
                try:
                    import builtins  # type: ignore
                    builtins.print = original_print  # type: ignore
                except Exception:
                    pass

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

        # Extract relationship constraints from existing data
        relationship_constraints = self._extract_relationship_constraints()
        
        aligned_nodes, aligned_relationships = self.align_with_existing_schema(
            document_nodes, document_relationships, schema_info, relationship_constraints
        )
        # Persist relationship constraints for future runs
        try:
            self._save_relationship_constraints(relationship_constraints)
        except Exception as e:
            logger.warning(f"Could not persist relationship constraints: {e}")

        extracted_data = self.extract_document_content(case_body, aligned_nodes, aligned_relationships, test_mode=False)
        node_count = sum(len(v) for v in extracted_data.nodes.values())
        rel_count = len(extracted_data.relationships)
        print(f"      • Case extraction: {node_count} nodes, {rel_count} relationships")

        # Generate and write queries (batched → fallback).
        success = self.execute_batched_queries(extracted_data)
        if not success:
            queries = self.generate_cypher_queries(extracted_data)
            success = self.execute_individual_queries(queries)

        # Post-insert: generate embeddings for selected properties for this case only
        if success:
            try:
                print("      🧠 Generating embeddings for this case's nodes...")
                from app.lib.embeddings import generate_embeddings_for_nodes
                embedding_ok = generate_embeddings_for_nodes(extracted_data.nodes)
                print(f"      • Embeddings generation: {'SUCCESS' if embedding_ok else 'FAILED'}")
            except Exception as e:
                logger.warning(f"Embedding generation for case '{case_name}' failed: {e}")

        # Run verification after database insertion
        verification_report = self._verify_case_upload(case_name, extracted_data)
        
        # Determine overall success (both import and verification must pass)
        overall_success = success and verification_report["success"]
        
        # Log results with verification status
        status = "✅" if overall_success else "❌"
        print(f"{status} {case_name} case processed (nodes={node_count}, rels={rel_count})")
        
        if verification_report["success"]:
            print(f"      ✅ Verification passed")
            if verification_report["warnings"]:
                print(f"      ⚠️  {len(verification_report['warnings'])} warnings:")
                for warning in verification_report["warnings"]:
                    print(f"         • {warning}")
        else:
            print(f"      ❌ Verification failed:")
            for error in verification_report["errors"]:
                print(f"         • {error}")
        
        return {
            "success": overall_success,
            "nodes_added": node_count,
            "relationships_added": rel_count,
            "verification": verification_report
        }



    def _assign_uuids_to_nodes(self, all_nodes: Dict[str, List[Dict[str, Any]]]) -> Dict[str, str]:
        """Assign UUIDs to all nodes using document-provided IDs as upload_code when available.

        If a document-provided ID (endswith("_id")/"id"/"_id") is present, reuse the
        existing node UUID in Neo4j if found; otherwise create a new one. This ensures
        stable node identity across re-uploads.
        """
        id_mapping = {}
        
        for label, nodes in all_nodes.items():
            id_prop = self._label_id_prop(label, {label: nodes})
            
            for node in nodes:
                # Extract upload_code from document ID fields (verbatim from document)
                upload_code = None
                for key, value in node.items():
                    if isinstance(value, str) and value.strip():
                        if key.endswith("_id") or key == "id" or key == "_id":
                            upload_code = value.strip()
                            break
                
                print(f"         🔍 Node {label}: upload_code='{upload_code}' from keys={list(node.keys())}")
                
                # Get or create UUID based on upload_code (with deduplication)
                final_uuid = self._get_or_create_uuid(label, upload_code)
                print(f"         🎯 Final UUID for {label}({upload_code}): {final_uuid}")
                
                # Store specific upload_code property (e.g., case_upload_code, fact_pattern_upload_code)
                if upload_code:
                    # Convert CamelCase to snake_case for upload code property
                    import re
                    snake_case = re.sub(r'(?<!^)(?=[A-Z])', '_', label).lower()
                    upload_code_prop = f"{snake_case}_upload_code"
                    node[upload_code_prop] = upload_code
                
                # Build ID mapping for relationship processing (map document IDs and names)
                if upload_code:
                    id_mapping[upload_code] = final_uuid
                    print(f"         📋 ID Mapping: '{upload_code}' -> {final_uuid}")
                
                # Also map by name/title fields for fallback identification
                for key, value in node.items():
                    if isinstance(value, str) and value.strip():
                        if key in ["name", "title", "citation"] or key.endswith("_name"):
                            id_mapping[value.strip()] = final_uuid
                            print(f"         📋 Name Mapping: '{value.strip()}' -> {final_uuid}")
                
                # Remove any existing ID fields that came from the document
                node.pop("_id", None)
                node.pop("id", None)
                
                # Set the semantic ID property (e.g., case_id, party_id)
                node[id_prop] = final_uuid
        
        return id_mapping

    def _get_or_create_uuid(self, node_type: str, upload_code: str) -> str:
        """Get existing UUID for upload_code or create a new one. Uses schema-based deduplication."""
        self._uuid_was_reused = False  # Track for logging
        
        if not upload_code:
            # No upload_code means no deduplication possible
            return str(uuid.uuid4())
        
        try:
            # Use specific upload code property (e.g., case_upload_code, fact_pattern_upload_code) 
            import re
            snake_case = re.sub(r'(?<!^)(?=[A-Z])', '_', node_type).lower()
            upload_code_prop = f"{snake_case}_upload_code"
            
            # Dynamically determine ID property from Neo4j schema
            id_prop = self._get_id_property_from_schema(node_type)
            
            print(f"         🔍 Checking for existing {node_type} with {upload_code_prop}='{upload_code}' -> {id_prop}")
            
            query = f"""
            MATCH (n:{node_type} {{{upload_code_prop}: $upload_code}})
            RETURN n.{id_prop} as existing_uuid
            LIMIT 1
            """
            
            result = neo4j_client.execute_query(query, {"upload_code": upload_code})
            
            if result and len(result) > 0:
                existing_uuid = result[0].get("existing_uuid")
                if existing_uuid:
                    self._uuid_was_reused = True
                    self._reused_count += 1
                    print(f"         ♻️ Found existing {node_type}: {upload_code} -> {existing_uuid}")
                    return str(existing_uuid)
            
            # No existing node found, create new UUID
            new_uuid = str(uuid.uuid4())
            self._new_count += 1
            print(f"         ✨ Creating new {node_type}: {upload_code} -> {new_uuid}")
            return new_uuid
            
        except Exception as e:
            logger.warning(f"Error checking for existing {node_type} with upload_code {upload_code}: {e}")
            # On error, create new UUID (fail-safe)
            return str(uuid.uuid4())

    def _get_id_property_from_schema(self, node_type: str) -> str:
        """Dynamically determine the ID property for a node type from Neo4j schema."""
        try:
            # Query Neo4j for property keys of this node type
            query = f"""
            MATCH (n:{node_type})
            WITH keys(n) as props
            UNWIND props as prop
            WITH DISTINCT prop
            WHERE prop ENDS WITH '_id'
            RETURN prop
            ORDER BY 
                CASE 
                    WHEN prop = $preferred_prop THEN 1
                    WHEN prop ENDS WITH '_id' THEN 2
                    ELSE 3
                END
            LIMIT 1
            """
            
            # Convert node type to snake_case for preferred property
            import re
            snake_case = re.sub(r'(?<!^)(?=[A-Z])', '_', node_type).lower()
            preferred_prop = f"{snake_case}_id"
            
            result = neo4j_client.execute_query(query, {"preferred_prop": preferred_prop})
            
            if result and len(result) > 0:
                id_prop = result[0].get("prop")
                if id_prop:
                    return id_prop
            
            # Fallback: use the preferred property name
            return preferred_prop
            
        except Exception as e:
            logger.warning(f"Error getting ID property for {node_type} from schema: {e}")
            # Fallback to conventional naming
            import re
            snake_case = re.sub(r'(?<!^)(?=[A-Z])', '_', node_type).lower()
            return f"{snake_case}_id"

    def _deduplicate_nodes_by_properties(self, all_nodes: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
        """Deduplicate nodes by matching on key properties instead of IDs."""
        deduplicated_nodes = {}
        
        for node_type, nodes in all_nodes.items():
            if not nodes:
                deduplicated_nodes[node_type] = []
                continue
                
            unique_nodes = []
            seen_signatures = set()
            
            # Determine the ID property name for this node type
            id_prop = f"{node_type.lower()}_id"
            
            # Helper to canonicalize arbitrary values to hashable, deterministic forms
            def _canon(value: Any) -> Any:
                try:
                    if isinstance(value, dict):
                        # Sort by key to be deterministic
                        return tuple((k, _canon(v)) for k, v in sorted(value.items(), key=lambda kv: kv[0]))
                    if isinstance(value, list):
                        return tuple(_canon(v) for v in value)
                    if isinstance(value, set):
                        return tuple(sorted(_canon(v) for v in value))
                    # Primitives/others
                    hash(value)  # type: ignore[arg-type]
                    return value
                except Exception:
                    # Fallback to string representation
                    try:
                        return str(value)
                    except Exception:
                        return "<unserializable>"
            
            for node in nodes:
                # Create a signature based on key properties (excluding the UUID ID field)
                signature_props = {k: v for k, v in node.items() if k != id_prop}
                
                # Use name-like properties for deduplication if available
                name_keys = [k for k in signature_props.keys() if 'name' in k.lower() or 'title' in k.lower()]
                if name_keys:
                    # Use the first name-like property as primary deduplication key
                    primary_key = name_keys[0]
                    primary_val = signature_props.get(primary_key, "")
                    if not isinstance(primary_val, str):
                        primary_val = str(primary_val)
                    signature = (node_type, primary_val.lower().strip())
                else:
                    # Fall back to a hash of all non-id properties
                    canonical_items = tuple(sorted(((k, _canon(v)) for k, v in signature_props.items()), key=lambda kv: kv[0]))
                    signature = (node_type, canonical_items)
                
                if signature not in seen_signatures:
                    seen_signatures.add(signature)
                    unique_nodes.append(node)
                else:
                    print(f"         🔄 Removing duplicate {node_type}: {signature}")
            
            deduplicated_nodes[node_type] = unique_nodes
            
        return deduplicated_nodes

    def _map_relationships_to_uuids(self, relationships: List[Dict[str, Any]], id_mapping: Dict[str, str]) -> List[Dict[str, Any]]:
        """Map relationship from_id and to_id values from identifying properties to generated UUIDs."""
        updated_relationships = []
        
        for rel in relationships:
            # Create a copy of the relationship
            updated_rel = rel.copy()
            
            # Map from_id to UUID if available
            from_id = str(rel.get("from_id", ""))
            if from_id in id_mapping:
                updated_rel["from_id"] = id_mapping[from_id]
            else:
                print(f"         ⚠️ No UUID mapping found for from_id: '{from_id}' - skipping relationship")
                continue  # Skip relationships with unmapped identifiers
            
            # Map to_id to UUID if available
            to_id = str(rel.get("to_id", ""))
            if to_id in id_mapping:
                updated_rel["to_id"] = id_mapping[to_id]
            else:
                print(f"         ⚠️ No UUID mapping found for to_id: '{to_id}' - skipping relationship")
                continue  # Skip relationships with unmapped identifiers
            
            updated_relationships.append(updated_rel)
        
        print(f"         📊 Mapped {len(updated_relationships)} relationships (from {len(relationships)} original)")
        return updated_relationships

    def _deduplicate_relationships(self, relationships: List[Dict[str, Any]], extracted_nodes: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        Deduplicates relationships by checking if a connection already exists between
        any two nodes. If a connection exists, ALL relationships for that pair
        (both direct and inverse) are skipped. If no connection exists, ALL
        relationships for that pair are added.
        """
        if not relationships:
            return []

        final_relationships = []
        
        # Group relationships by the pair of nodes they connect
        rels_by_pair = {}
        for rel in relationships:
            from_id = rel.get("from_id")
            to_id = rel.get("to_id")
            if not from_id or not to_id:
                continue
            
            pair_key = frozenset([from_id, to_id])
            if pair_key not in rels_by_pair:
                rels_by_pair[pair_key] = []
            rels_by_pair[pair_key].append(rel)

        # Check each pair for existing connections in Neo4j
        for pair_key, pair_relationships in rels_by_pair.items():
            # Get details from the first relationship in the group to perform the check
            sample_rel = pair_relationships[0]
            from_id = sample_rel.get("from_id")
            to_id = sample_rel.get("to_id")
            from_type = sample_rel.get("from_type")
            to_type = sample_rel.get("to_type")

            if not all([from_id, to_id, from_type, to_type]):
                continue

            from_id_prop = self._label_id_prop(from_type, extracted_nodes)
            to_id_prop = self._label_id_prop(to_type, extracted_nodes)
            
            query = f"""
            MATCH (a:{from_type} {{{from_id_prop}: $from_id}})
            MATCH (b:{to_type} {{{to_id_prop}: $to_id}})
            RETURN EXISTS((a)-[]-(b)) as connection_exists
            """
            params = {"from_id": from_id, "to_id": to_id}

            try:
                result = neo4j_client.execute_query(query, params)
                connection_exists = result[0]["connection_exists"] if result else False

                if connection_exists:
                    print(f"         ♻️ Connection already exists in Neo4j between nodes {from_id} and {to_id}. Skipping {len(pair_relationships)} relationships.")
                    continue
                else:
                    # If no connection exists, add all relationships for this pair
                    print(f"         ➕ Adding {len(pair_relationships)} new relationships for pair {from_id}-{to_id}")
                    final_relationships.extend(pair_relationships)

            except Exception as e:
                logger.error(f"Error checking relationship existence for {from_id}-{to_id}: {e}")
                # Fallback: assume it doesn't exist to avoid dropping data on query failure.
                final_relationships.extend(pair_relationships)

        print(f"         📊 Deduplication complete: {len(relationships)} → {len(final_relationships)} relationships")
        return final_relationships

    def _extract_relationship_constraints(self) -> Dict[str, List[str]]:
        """Extract relationship types between node type pairs.

        Strategy:
        1) Load cached mappings from static file if present (best-effort).
        2) Query Neo4j live constraints and merge with cached (live takes precedence).
        3) Return merged constraints.
        """
        merged: Dict[str, List[str]] = {}

        # 1) Load cached file if present
        try:
            import os, json
            static_path = os.path.join(os.path.dirname(__file__), "..", "..", "relationship_mappings.json")
            static_path = os.path.abspath(static_path)
            if os.path.exists(static_path):
                with open(static_path, "r") as f:
                    cached = json.load(f)
                    if isinstance(cached, dict):
                        for k, v in cached.items():
                            if isinstance(v, list):
                                merged[k] = list(sorted(set(v)))
                print(f"      💾 Loaded cached relationship mappings from {static_path} ({len(merged)} pairs)")
        except Exception as e:
            logger.warning(f"Could not load cached relationship mappings: {e}")

        # 2) Query Neo4j live constraints
        try:
            query = """
            MATCH (a)-[r]->(b)
            UNWIND labels(a) as from_type
            UNWIND labels(b) as to_type
            WITH from_type, to_type, type(r) as rel_type
            RETURN from_type, to_type, collect(DISTINCT rel_type) as relationship_types
            ORDER BY from_type, to_type
            """
            result = neo4j_client.execute_query(query)
            live = {}
            for record in result:
                from_type = record.get("from_type")
                to_type = record.get("to_type")
                rel_types = record.get("relationship_types", [])
                if from_type and to_type and rel_types:
                    key = f"{from_type}->{to_type}"
                    live[key] = rel_types
                    print(f"      📋 Found {len(rel_types)} relationship types: {from_type} -> {to_type}: {rel_types}")

            # Merge, preferring live
            for k, v in live.items():
                merged[k] = list(sorted(set(v)))

            print(f"      📊 Extracted merged constraints for {len(merged)} node type pairs")
            return merged
        except Exception as e:
            logger.warning(f"Error extracting relationship constraints: {e}")
            return merged

    def _save_relationship_constraints(self, constraints: Dict[str, List[str]]) -> None:
        """Persist relationship type mappings to a static file for future runs."""
        try:
            import os, json
            static_path = os.path.join(os.path.dirname(__file__), "..", "..", "relationship_mappings.json")
            static_path = os.path.abspath(static_path)
            os.makedirs(os.path.dirname(static_path), exist_ok=True)
            # Normalize and sort for stability
            normalized = {k: list(sorted(set(v))) for k, v in constraints.items()}
            with open(static_path, "w") as f:
                json.dump(normalized, f, indent=2)
            print(f"      💾 Saved relationship mappings to {static_path} ({len(normalized)} pairs)")
        except Exception as e:
            logger.warning(f"Could not save relationship mappings: {e}")

    def _verify_case_upload(self, case_name: str, extracted_data: ExtractedData) -> Dict[str, Any]:
        """
        Verify that case upload was successful and data quality is good.
        
        Focuses on reliable checks:
        1. Database integrity - extracted data actually exists in Neo4j
        2. Data quality - UUIDs, required fields, relationship integrity
        
        Returns verification report with any issues found.
        """
        verification_report = {
            "case_name": case_name,
            "success": True,
            "warnings": [],
            "errors": [],
            "stats": {
                "nodes_expected": sum(len(nodes) for nodes in extracted_data.nodes.values()),
                "relationships_expected": len(extracted_data.relationships),
                "nodes_verified": 0,
                "relationships_verified": 0
            }
        }
        
        # 1. Data Quality Check
        quality_issues = self._check_data_quality(extracted_data)
        verification_report["warnings"].extend(quality_issues)
        
        # 2. Database Integrity Check
        integrity_issues, verified_counts = self._check_database_integrity(extracted_data)
        verification_report["errors"].extend(integrity_issues)
        verification_report["stats"]["nodes_verified"] = verified_counts["nodes"]
        verification_report["stats"]["relationships_verified"] = verified_counts["relationships"]
        
        # Mark as failed if any errors found
        if verification_report["errors"]:
            verification_report["success"] = False
        
        return verification_report

    def _check_data_quality(self, extracted_data: ExtractedData) -> List[str]:
        """Check for data quality issues in extracted data."""
        warnings = []
        
        # Check nodes for quality issues
        for node_type, nodes in extracted_data.nodes.items():
            id_prop = f"{node_type.lower()}_id"
            
            for i, node in enumerate(nodes):
                # UUID format validation
                node_id = node.get(id_prop)
                if not node_id:
                    warnings.append(f"{node_type} node {i+1} missing {id_prop}")
                elif not self._is_valid_uuid(str(node_id)):
                    warnings.append(f"{node_type} node {i+1} has invalid UUID format: {node_id}")
                
                # Check for required fields (name-like properties)
                name_fields = [k for k in node.keys() if 'name' in k.lower() or 'title' in k.lower()]
                if not name_fields:
                    warnings.append(f"{node_type} node {i+1} has no identifying name/title fields")
                else:
                    # Check if name fields are empty
                    for field in name_fields:
                        if not node.get(field) or str(node.get(field)).strip() == "":
                            warnings.append(f"{node_type} node {i+1} has empty {field}")
        
        # Check relationships for quality issues
        for i, rel in enumerate(extracted_data.relationships):
            # Check required relationship fields
            required_fields = ["type", "from_id", "to_id", "from_type", "to_type"]
            for field in required_fields:
                if not rel.get(field):
                    warnings.append(f"Relationship {i+1} missing required field: {field}")
            
            # Validate UUIDs in relationships
            if rel.get("from_id") and not self._is_valid_uuid(str(rel["from_id"])):
                warnings.append(f"Relationship {i+1} has invalid from_id UUID: {rel['from_id']}")
            if rel.get("to_id") and not self._is_valid_uuid(str(rel["to_id"])):
                warnings.append(f"Relationship {i+1} has invalid to_id UUID: {rel['to_id']}")
        
        return warnings

    def _check_database_integrity(self, extracted_data: ExtractedData) -> Tuple[List[str], Dict[str, int]]:
        """Verify that extracted data was properly stored in Neo4j database."""
        errors = []
        verified_counts = {"nodes": 0, "relationships": 0}
        
        # Debug: Show what we're verifying
        print(f"      🔍 Verification Debug - Node types in extracted_data: {list(extracted_data.nodes.keys())}")
        print(f"      🔍 Verification Debug - Checking {len(extracted_data.relationships)} relationships")
        
        # Debug: Check what node types actually exist in database
        try:
            db_labels = neo4j_client.execute_query("CALL db.labels() YIELD label RETURN label ORDER BY label")
            actual_labels = [record["label"] for record in db_labels]
            print(f"      🔍 Verification Debug - Actual node types in database: {actual_labels}")
        except:
            print(f"      🔍 Verification Debug - Could not retrieve database labels")
        
        # Verify node insertion
        for node_type, nodes in extracted_data.nodes.items():
            id_prop = f"{node_type.lower()}_id"
            
            for node in nodes:
                node_id = node.get(id_prop)
                if not node_id:
                    continue  # Skip nodes without IDs (already flagged in quality check)
                
                # Check if node exists in database
                try:
                    query = f"MATCH (n:{node_type} {{{id_prop}: $node_id}}) RETURN count(n) as count"
                    result = neo4j_client.execute_query(query, {"node_id": node_id})
                    
                    if result and result[0]["count"] > 0:
                        verified_counts["nodes"] += 1
                    else:
                        errors.append(f"Node not found in database: {node_type} {id_prop}={node_id}")
                        
                except Exception as e:
                    errors.append(f"Database error checking {node_type} {node_id}: {str(e)}")
        
        # Verify relationship insertion
        for i, rel in enumerate(extracted_data.relationships):
            if not all(rel.get(field) for field in ["from_id", "to_id", "from_type", "to_type", "type"]):
                continue  # Skip incomplete relationships (already flagged in quality check)
            
            from_type = rel["from_type"]
            to_type = rel["to_type"]
            rel_type = rel["type"]
            from_id = rel["from_id"]
            to_id = rel["to_id"]
            
            # Use the same logic as creation to determine ID properties
            from_id_prop = self._label_id_prop(from_type, extracted_data.nodes)
            to_id_prop = self._label_id_prop(to_type, extracted_data.nodes)
            
            # Debug the first few failing relationships
            if i < 3:
                print(f"      🔍 Checking rel {i+1}: {from_type}({from_id}) -{rel_type}-> {to_type}({to_id})")
                print(f"      🔍 Looking for: {from_type}.{from_id_prop} and {to_type}.{to_id_prop}")
            
            try:
                # Check if relationship exists in database
                query = f"""
                MATCH (a:{from_type} {{{from_id_prop}: $from_id}})
                MATCH (b:{to_type} {{{to_id_prop}: $to_id}})
                MATCH (a)-[r:{rel_type}]->(b)
                RETURN count(r) as count
                """
                
                result = neo4j_client.execute_query(query, {
                    "from_id": from_id,
                    "to_id": to_id
                })
                
                if result and result[0]["count"] > 0:
                    verified_counts["relationships"] += 1
                else:
                    # Debug: Check if the nodes exist separately
                    node_check_a = neo4j_client.execute_query(f"MATCH (n:{from_type} {{{from_id_prop}: $id}}) RETURN count(n) as count", {"id": from_id})
                    node_check_b = neo4j_client.execute_query(f"MATCH (n:{to_type} {{{to_id_prop}: $id}}) RETURN count(n) as count", {"id": to_id})
                    
                    node_a_exists = node_check_a and node_check_a[0]["count"] > 0
                    node_b_exists = node_check_b and node_check_b[0]["count"] > 0
                    
                    error_msg = f"Relationship not found: {from_type}({from_id}) -{rel_type}-> {to_type}({to_id})"
                    if not node_a_exists:
                        error_msg += f" [FROM node {from_type} not found]"
                    if not node_b_exists:
                        error_msg += f" [TO node {to_type} not found]"
                    
                    errors.append(error_msg)
                    
            except Exception as e:
                errors.append(f"Database error checking relationship {rel_type}: {str(e)}")
        
        return errors, verified_counts

    def _is_valid_uuid(self, uuid_string: str) -> bool:
        """Check if a string is a valid UUID format."""
        try:
            uuid.UUID(uuid_string)
            return True
        except (ValueError, TypeError):
            return False

    def _determine_id_prop(self, label: str, sample_row: Dict[str, Any]) -> str:
        """Return the property key that uniquely identifies a node.

        Preference order:
        1. <label_lower>_id  (e.g. case_id, party_id)
        2. First key ending with '_id'
        3. 'id' as fallback
        """
        preferred = f"{label.lower()}_id"
        if preferred in sample_row:
            return preferred
        for k in sample_row.keys():
            if k.endswith("_id"):
                return k
        return "id"

    def _label_id_prop(self, label: str, data_nodes: Dict[str, List[Dict[str, Any]]]) -> str:
        """Return the identifier property for a label using available data or convention."""
        if label in data_nodes and data_nodes[label]:
            return self._determine_id_prop(label, data_nodes[label][0])
        default_prop = f"{label.lower()}_id"
        return default_prop

    def _update_property_mappings_after_import(self):
        """Update property mappings from Neo4j schema using MCP server after successful import."""
        try:
            print("🔄 Updating property mappings from Neo4j schema...")
            from app.lib.mcp_integration import MCPEnabledAgents, get_mcp_tools
            import json
            import os
            
            with MCPEnabledAgents() as mcp_context:
                if not mcp_context.mcp_adapter:
                    logger.warning("MCP tools not available for schema update")
                    return

                neo4j_tools = get_mcp_tools()
                schema_tool = next((t for t in neo4j_tools if 'schema' in t.name.lower()), None)

                if not schema_tool:
                    logger.warning("Neo4j schema tool not found in MCP tools")
                    return
                
                # Get schema from Neo4j using MCP
                schema_result = schema_tool.run({})
                
                # Parse schema to extract property names
                property_mappings = self._parse_schema_for_properties(schema_result)
                
                # Save to static file
                static_file_path = os.path.join(os.path.dirname(__file__), "..", "..", "property_mappings.json")
                os.makedirs(os.path.dirname(static_file_path), exist_ok=True)
                
                with open(static_file_path, 'w') as f:
                    json.dump(property_mappings, f, indent=2)
                
                print(f"✅ Updated property mappings: {len(property_mappings.get('id_properties', []))} ID properties, {len(property_mappings.get('name_properties', []))} name properties")
                logger.info(f"Property mappings updated to {static_file_path}")
                
        except Exception as e:
            logger.warning(f"Could not update property mappings after import: {e}")

    def _parse_schema_for_properties(self, schema_result) -> dict:
        """Parse Neo4j schema result using AI and categorize properties."""
        try:
            print("🤖 Using AI to parse Neo4j schema for property extraction...")
            print(f"🔍 Schema result type: {type(schema_result)}")
            
                         # Prepare prompt for AI
            prompt = f"""
TASK: Extract and categorize all Neo4j property names from the following schema result.

SCHEMA RESULT:
{str(schema_result)}

INSTRUCTIONS:
1. Find ALL property names mentioned in this Neo4j schema
2. Categorize them into two groups:
   - ID Properties: Properties that are identifiers (end with "_id", or are exactly "id" or "citation")
   - Name Properties: Properties that are name fields - ONLY properties ending with "_name" or exactly "name"
3. Property names should be valid identifiers (letters, numbers, underscores only)
4. Return the result as JSON with this exact structure:

{{
  "id_properties": ["case_id", "party_id", "id"],
  "name_properties": ["case_name", "party_name"],
  "all_properties": ["case_id", "party_id", "case_name", "party_name", "description", "year", "court"]
}}

IMPORTANT: For name_properties, ONLY include properties that end with "_name" or are exactly "name". 
Do NOT include properties ending with "_description", "_text", "_type", etc.

Be thorough - extract every property name you can find in the schema.
"""

            # Use AI to extract properties
            response = self.llm.call([{"role": "user", "content": prompt}])
            
            # Parse AI response as JSON
            try:
                import json
                # Clean up response
                response_text = response.strip()
                if response_text.startswith('```json'):
                    response_text = response_text.replace('```json', '').replace('```', '').strip()
                elif response_text.startswith('```'):
                    response_text = response_text.replace('```', '').strip()
                
                parsed_response = json.loads(response_text)
                
                # Extract properties from AI response
                id_properties = parsed_response.get("id_properties", [])
                name_properties = parsed_response.get("name_properties", [])
                all_properties = parsed_response.get("all_properties", [])
                
                # Validate and clean property names
                import re
                def clean_properties(props):
                    return [prop.strip() for prop in props 
                           if isinstance(prop, str) and prop.strip() 
                           and re.match(r'^[a-zA-Z_][a-zA-Z0-9_]{0,50}$', prop.strip())]
                
                id_properties = clean_properties(id_properties)
                name_properties = clean_properties(name_properties)
                all_properties = clean_properties(all_properties)
                
                # Sort for consistency
                id_properties.sort()
                name_properties.sort()
                
                print(f"✅ AI extracted {len(all_properties)} total properties")
                print(f"   📋 ID properties ({len(id_properties)}): {id_properties[:5]}{'...' if len(id_properties) > 5 else ''}")
                print(f"   📋 Name properties ({len(name_properties)}): {name_properties[:5]}{'...' if len(name_properties) > 5 else ''}")
                
                return {
                    "id_properties": id_properties,
                    "name_properties": name_properties,
                    "last_updated": str(int(time.time())),
                    "total_properties": len(all_properties),
                    "schema_source": "ai_mcp_neo4j"
                }
                
            except json.JSONDecodeError as e:
                logger.error(f"AI response was not valid JSON: {e}")
                print(f"❌ AI response parsing failed. Response: {response[:200]}...")
                # Fallback to direct query
                return self._fallback_to_direct_query()
                
        except Exception as e:
            logger.error(f"Error in AI schema parsing: {e}")
            # Fallback to direct query
            return self._fallback_to_direct_query()

    def _fallback_to_direct_query(self) -> dict:
        """Fallback: Get properties using direct Neo4j queries."""
        try:
            print("🔄 Falling back to direct Neo4j property query...")
            query = "CALL db.propertyKeys() YIELD propertyKey RETURN collect(propertyKey) as keys"
            result = neo4j_client.execute_query(query)
            
            if result and len(result) > 0:
                all_properties = result[0].get('keys', [])
                
                # Categorize using simple rules
                id_properties = []
                name_properties = []
                
                for prop in all_properties:
                    if isinstance(prop, str):
                        prop_lower = prop.lower()
                        if (prop_lower.endswith('_id') or prop_lower == 'id' or prop_lower == 'citation'):
                            id_properties.append(prop)
                        elif (prop_lower.endswith('_name') or prop_lower == 'name'):
                            name_properties.append(prop)
                
                id_properties.sort()
                name_properties.sort()
                
                print(f"✅ Direct query found {len(all_properties)} properties")
                print(f"   📋 ID properties ({len(id_properties)}): {id_properties[:5]}{'...' if len(id_properties) > 5 else ''}")
                print(f"   📋 Name properties ({len(name_properties)}): {name_properties[:5]}{'...' if len(name_properties) > 5 else ''}")
                
                return {
                    "id_properties": id_properties,
                    "name_properties": name_properties,
                    "last_updated": str(int(time.time())),
                    "total_properties": len(all_properties),
                    "schema_source": "direct_neo4j_fallback"
                }
            else:
                print("❌ Direct query returned no results")
                return self._get_default_mappings()
                
        except Exception as e:
            logger.error(f"Direct query fallback failed: {e}")
            return self._get_default_mappings()

    def _get_default_mappings(self) -> dict:
        """Return default property mappings when all else fails."""
        print("🔄 Using default property mappings")
        return {
            "id_properties": ["id", "case_id", "party_id", "citation"],
            "name_properties": ["name", "case_name", "party_name"],
            "last_updated": str(int(time.time())),
            "total_properties": 7,
            "schema_source": "default_fallback"
        }

# Removed old _extract_properties_from_schema_data - now using AI parsing

# Global instance
dynamic_processor = DynamicDocumentProcessor() 