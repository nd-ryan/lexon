import os
from neo4j import GraphDatabase
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

class Neo4jClient:
    def __init__(self):
        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.username = os.getenv("NEO4J_USER", "neo4j")
        self.password = os.getenv("NEO4J_PASSWORD", "password")
        self.database = os.getenv("NEO4J_DATABASE", "neo4j")
        
        # Configure driver with proper settings for both local and AuraDB
        # Note: neo4j+s:// and bolt+s:// URIs already imply encryption, 
        # so we don't need to set encrypted=True for them
        driver_config = {
            "max_connection_lifetime": 3600,  # 1 hour
            "max_connection_pool_size": 50,
            "connection_acquisition_timeout": 120,  # 2 minutes
        }
        
        try:
            self.driver = GraphDatabase.driver(
                self.uri, 
                auth=(self.username, self.password),
                **driver_config
            )
            logger.info(f"Neo4j driver created for {self.uri}")
            
            # Try a simple connectivity test (less strict than verify_connectivity)
            try:
                with self.driver.session(database=self.database) as session:
                    session.run("RETURN 1").consume()
                logger.info(f"Neo4j connection verified successfully")
            except Exception as conn_error:
                logger.warning(f"Initial connectivity check failed (will retry on use): {conn_error}")
                # Don't set driver to None - let it fail lazily on actual use
                
        except Exception as e:
            logger.error(f"Failed to create Neo4j driver: {e}")
            self.driver = None
    
    def close(self):
        if self.driver:
            self.driver.close()
    
    def execute_query(self, query: str, parameters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Execute a Cypher query and return results as a list of dictionaries."""
        if not self.driver:
            raise Exception("Neo4j driver not initialized. Check connection settings.")
        
        with self.driver.session(database=self.database) as session:
            try:
                result = session.run(query, parameters or {})
                records = []
                for record in result:
                    record_dict = {}
                    for key in record.keys():
                        value = record[key]
                        # Convert Neo4j types to Python types
                        if hasattr(value, 'items'):  # Node or Relationship
                            record_dict[key] = dict(value.items())
                        elif hasattr(value, '__iter__') and not isinstance(value, str):  # Path or list
                            record_dict[key] = list(value)
                        else:
                            record_dict[key] = value
                    records.append(record_dict)
                return records
            except Exception as e:
                logger.error(f"Error executing query: {e}")
                raise
    
    def load_knowledge_graph(self, kg_data: Dict[str, Any]):
        """Load knowledge graph data into Neo4j."""
        if not self.driver:
            raise Exception("Neo4j driver not initialized. Check connection settings.")
        
        with self.driver.session(database=self.database) as session:
            try:
                # Clear existing data (optional - remove if you want to keep existing data)
                # session.run("MATCH (n) DETACH DELETE n")
                
                # Load nodes
                for case in kg_data.get('cases', []):
                    session.run(
                        "MERGE (c:Case {case_id: $case_id}) SET c += $properties",
                        case_id=case['case_id'],
                        properties=case
                    )
                
                for party in kg_data.get('parties', []):
                    session.run(
                        "MERGE (p:Party {party_id: $party_id}) SET p += $properties",
                        party_id=party['party_id'],
                        properties=party
                    )
                
                for provision in kg_data.get('provisions', []):
                    session.run(
                        "MERGE (p:Provision {provision_id: $provision_id}) SET p += $properties",
                        provision_id=provision['provision_id'],
                        properties=provision
                    )
                
                # Load relationships
                for rel in kg_data.get('caseParties', []):
                    session.run(
                        """
                        MATCH (c:Case {case_id: $case_id})
                        MATCH (p:Party {party_id: $party_id})
                        MERGE (c)-[:HAS_PARTY {role: $role}]->(p)
                        """,
                        case_id=rel['case_id'],
                        party_id=rel['party_id'],
                        role=rel.get('role')
                    )
                
                for rel in kg_data.get('caseProvisions', []):
                    session.run(
                        """
                        MATCH (c:Case {case_id: $case_id})
                        MATCH (p:Provision {provision_id: $provision_id})
                        MERGE (c)-[:CITES_PROVISION]->(p)
                        """,
                        case_id=rel['case_id'],
                        provision_id=rel['provision_id']
                    )
                
                logger.info("Knowledge graph data loaded successfully")
                return True
                
            except Exception as e:
                logger.error(f"Error loading knowledge graph: {e}")
                raise

# Global instance
neo4j_client = Neo4jClient() 