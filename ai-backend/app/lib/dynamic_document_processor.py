import re
import json
import logging
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
        self.llm = LLM(model="o3-mini", temperature=0)
        self.mcp_tools = None
    
    def set_mcp_tools(self, mcp_tools):
        """Set MCP tools for enhanced Neo4j operations"""
        self.mcp_tools = mcp_tools
    
    def get_neo4j_schema(self) -> SchemaInfo:
        """Query Neo4j to get existing schema information using MCP tools when available"""
        try:
            # Try to use MCP get-neo4j-schema tool first
            if self.mcp_tools:
                for tool in self.mcp_tools:
                    if tool.name == "get-neo4j-schema":
                        logger.info("Using Neo4j MCP get-neo4j-schema tool")
                        schema_result = tool.run({})
                        
                        # Parse MCP schema result
                        if isinstance(schema_result, dict):
                            return SchemaInfo(
                                node_labels=schema_result.get("node_labels", []),
                                relationship_types=schema_result.get("relationship_types", []),
                                node_properties=schema_result.get("node_properties", {}),
                                relationship_properties=schema_result.get("relationship_properties", {})
                            )
                        else:
                            logger.warning(f"Unexpected MCP schema result format: {type(schema_result)}")
            
            # Fallback to direct Neo4j queries if MCP not available
            logger.info("Using direct Neo4j queries for schema (MCP not available)")
            with neo4j_client.driver.session() as session:
                # Get node labels
                result = session.run("CALL db.labels()")
                node_labels = [record["label"] for record in result]
                
                # Get relationship types  
                result = session.run("CALL db.relationshipTypes()")
                relationship_types = [record["relationshipType"] for record in result]
                
                # Get node properties for each label
                node_properties = {}
                for label in node_labels:
                    result = session.run(f"MATCH (n:{label}) RETURN keys(n) as props LIMIT 10")
                    all_props = set()
                    for record in result:
                        all_props.update(record["props"])
                    node_properties[label] = list(all_props)
                
                # Get relationship properties for each type
                relationship_properties = {}
                for rel_type in relationship_types:
                    result = session.run(f"MATCH ()-[r:{rel_type}]-() RETURN keys(r) as props LIMIT 10")
                    all_props = set()
                    for record in result:
                        all_props.update(record["props"])
                    relationship_properties[rel_type] = list(all_props)
                
                return SchemaInfo(
                    node_labels=node_labels,
                    relationship_types=relationship_types, 
                    node_properties=node_properties,
                    relationship_properties=relationship_properties
                )
                
        except Exception as e:
            logger.warning(f"Could not get Neo4j schema: {e}")
            return SchemaInfo([], [], {}, {})
    
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
            logger.info("Calling LLM for node identification...")
            response = self.llm.call([{"role": "user", "content": prompt}])
            
            if not response:
                raise ValueError("Empty response from LLM for node identification")
                
            nodes_json = response.strip()
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
            logger.info("Calling LLM for relationship identification...")
            response = self.llm.call([{"role": "user", "content": prompt}])
            
            if not response:
                raise ValueError("Empty response from LLM for relationship identification")
                
            relationships_json = response.strip()
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
            logger.info("Calling LLM for schema alignment...")
            response = self.llm.call([{"role": "user", "content": prompt}])
            
            if not response:
                raise ValueError("Empty response from LLM for schema alignment")
                
            aligned_json = response.strip()
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
    
    def extract_document_content(self, document_text: str, aligned_nodes: Dict[str, List[str]], aligned_relationships: Dict[str, Dict[str, Any]]) -> ExtractedData:
        """Step 5: Extract actual content based on the aligned metadata"""
        
        metadata_context = f"""
EXTRACTION SCHEMA:
Nodes to extract: {json.dumps(aligned_nodes, indent=2)}
Relationships to extract: {json.dumps(aligned_relationships, indent=2)}
"""
        
        prompt = f"""
{metadata_context}

DOCUMENT TO EXTRACT FROM:
{document_text}

TASK: Extract ALL instances of the specified entities and relationships from this document.

OUTPUT FORMAT (JSON only):
{{
  "nodes": {{
    "NodeType1": [
      {{"node_id": "unique_id1", "property1": "value1", "property2": "value2"}},
      {{"node_id": "unique_id2", "property1": "value3", "property2": "value4"}}
    ],
    "NodeType2": [
      {{"node_id": "unique_id3", "property1": "value5"}}
    ]
  }},
  "relationships": [
    {{"type": "RELATIONSHIP_TYPE1", "from_id": "unique_id1", "from_type": "NodeType1", "to_id": "unique_id3", "to_type": "NodeType2", "properties": {{"prop1": "value"}}}},
    {{"type": "RELATIONSHIP_TYPE2", "from_id": "unique_id2", "from_type": "NodeType1", "to_id": "unique_id3", "to_type": "NodeType2", "properties": {{}}}}
  ]
}}

EXTRACTION REQUIREMENTS:
1. Extract EVERY instance of each node type from the document - don't miss any
2. Generate meaningful, unique IDs for each node instance (e.g., "case_001", "party_plaintiff", "provision_14th_amendment")
3. Fill in ALL available properties for each node based on document content
4. Create ALL relationships between nodes as specified in the schema
5. Be thorough - capture every entity and every connection mentioned in the document
6. Use exact node type names and relationship types from the schema
7. If a property value is not available, use null
8. Ensure all relationships reference valid node IDs that exist in the nodes section
9. Return ONLY the JSON, no other text
"""

        try:
            logger.info("Calling LLM for content extraction...")
            response = self.llm.call([{"role": "user", "content": prompt}])
            logger.info(f"LLM response received, length: {len(response) if response else 0}")
            
            if not response:
                raise ValueError("Empty response from LLM")
                
            content_json = response.strip()
            logger.debug(f"Content JSON preview: {content_json[:500]}...")
            
            # Parse the JSON response
            try:
                content_dict = json.loads(content_json)
            except json.JSONDecodeError as json_err:
                logger.error(f"JSON parsing failed. Raw response: {content_json}")
                raise ValueError(f"Invalid JSON response from LLM: {json_err}")
            
            logger.info(f"Successfully parsed extraction results: {len(content_dict.get('nodes', {}))} node types, {len(content_dict.get('relationships', []))} relationships")
            
            return ExtractedData(
                nodes=content_dict.get("nodes", {}),
                relationships=content_dict.get("relationships", [])
            )
            
        except Exception as e:
            logger.error(f"Error extracting document content: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            # Return empty data instead of raising to allow process to continue
            logger.warning("Returning empty extraction data due to error")
            return ExtractedData(nodes={}, relationships=[])
    
    def generate_cypher_queries(self, extracted_data: ExtractedData) -> List[str]:
        """Generate Cypher queries to import the extracted data"""
        queries = []
        
        # Generate node creation queries
        for node_type, nodes in extracted_data.nodes.items():
            if not nodes:
                continue
                
            # Assume first property is the ID property
            id_prop = list(nodes[0].keys())[0] if nodes[0] else "id"
            
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
            
            # Find ID property names (assume first property is ID)
            from_id_prop = "id"  # Default
            to_id_prop = "id"    # Default
            
            # Try to find actual ID property names from the nodes
            if from_type in extracted_data.nodes and extracted_data.nodes[from_type]:
                from_id_prop = list(extracted_data.nodes[from_type][0].keys())[0]
            if to_type in extracted_data.nodes and extracted_data.nodes[to_type]:
                to_id_prop = list(extracted_data.nodes[to_type][0].keys())[0]
            
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
    
    def execute_cypher_queries(self, queries: List[Tuple[str, Dict]]) -> bool:
        """Execute the generated Cypher queries using MCP tools when available"""
        try:
            # Try to use MCP write-neo4j-cypher tool first
            if self.mcp_tools:
                write_tool = None
                for tool in self.mcp_tools:
                    if tool.name == "write-neo4j-cypher":
                        write_tool = tool
                        break
                
                if write_tool:
                    logger.info("Using Neo4j MCP write-neo4j-cypher tool")
                    for query, params in queries:
                        try:
                            result = write_tool.run({
                                "query": query,
                                "parameters": params
                            })
                            logger.debug(f"MCP query result: {result}")
                        except Exception as e:
                            logger.error(f"MCP query execution failed: {e}")
                            # Fall back to direct execution for this query
                            with neo4j_client.driver.session() as session:
                                session.run(query, params)
                    
                    logger.info(f"Successfully executed {len(queries)} Cypher queries via MCP")
                    return True
            
            # Fallback to direct Neo4j execution
            logger.info("Using direct Neo4j execution (MCP not available)")
            with neo4j_client.driver.session() as session:
                for query, params in queries:
                    session.run(query, params)
                    
            logger.info(f"Successfully executed {len(queries)} Cypher queries")
            return True
            
        except Exception as e:
            logger.error(f"Error executing Cypher queries: {e}")
            raise
    
    def process_document(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """Main processing pipeline with improved multi-step approach"""
        try:
            # Step 1: Get existing Neo4j schema
            logger.info("Step 1: Getting Neo4j schema...")
            schema_info = self.get_neo4j_schema()
            
            # Step 2: Extract document text
            logger.info("Step 2: Extracting document text...")
            document_text = self.extract_document_text(file_content)
            
            # Step 3: Identify ALL possible nodes in document
            logger.info("Step 3: Identifying all possible nodes...")
            document_nodes = self.identify_document_nodes(document_text)
            
            # Step 4: Identify ALL possible relationships in document
            logger.info("Step 4: Identifying all possible relationships...")
            document_relationships = self.identify_document_relationships(document_text, document_nodes)
            
            # Step 5: Align with existing schema
            logger.info("Step 5: Aligning with existing Neo4j schema...")
            aligned_nodes, aligned_relationships = self.align_with_existing_schema(
                document_nodes, document_relationships, schema_info
            )
            
            # Step 6: Extract actual content using aligned metadata
            logger.info("Step 6: Extracting document content...")
            extracted_data = self.extract_document_content(document_text, aligned_nodes, aligned_relationships)
            
            # Step 7: Generate Cypher queries
            logger.info("Step 7: Generating Cypher queries...")
            queries = self.generate_cypher_queries(extracted_data)
            
            # Step 8: Execute queries
            logger.info("Step 8: Executing Cypher queries...")
            success = self.execute_cypher_queries(queries)
            
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

# Global instance
dynamic_processor = DynamicDocumentProcessor() 