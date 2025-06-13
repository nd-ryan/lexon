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
        self.driver = GraphDatabase.driver(self.uri, auth=(self.username, self.password))
    
    def close(self):
        if self.driver:
            self.driver.close()
    
    def execute_query(self, query: str, parameters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Execute a Cypher query and return results as a list of dictionaries."""
        with self.driver.session() as session:
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
        with self.driver.session() as session:
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