import os
from neo4j import GraphDatabase
from typing import List, Dict, Any, Optional, Iterator
import logging
from contextlib import contextmanager
import threading

from neo4j.exceptions import SessionExpired, ServiceUnavailable

logger = logging.getLogger(__name__)

class Neo4jClient:
    def __init__(self):
        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.username = os.getenv("NEO4J_USER", "neo4j")
        self.password = os.getenv("NEO4J_PASSWORD", "password")
        self.database = os.getenv("NEO4J_DATABASE", "neo4j")
        self._driver_lock = threading.Lock()
        
        # Configure driver with proper settings for both local and AuraDB
        # Note: neo4j+s:// and bolt+s:// URIs already imply encryption, 
        # so we don't need to set encrypted=True for them
        self._driver_config = {
            # Keep connections fresh; Aura can drop idle/long-lived connections.
            "max_connection_lifetime": 1800,  # 30 min
            "max_connection_pool_size": 50,
            "connection_acquisition_timeout": 120,  # 2 minutes
        }
        self.driver = None
        self._create_driver()

    def _create_driver(self):
        """Create a Neo4j driver (safe to call multiple times)."""
        try:
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.username, self.password),
                **self._driver_config
            )
            logger.info(f"Neo4j driver created for {self.uri}")

            # Try a simple connectivity test (less strict than verify_connectivity)
            try:
                with self.driver.session(database=self.database) as session:
                    session.run("RETURN 1").consume()
                logger.info("Neo4j connection verified successfully")
            except Exception as conn_error:
                logger.warning(f"Initial connectivity check failed (will retry on use): {conn_error}")
        except Exception as e:
            logger.error(f"Failed to create Neo4j driver: {e}")
            self.driver = None

    def _recreate_driver(self):
        """Recreate the driver after a defunct/expired connection."""
        with self._driver_lock:
            try:
                if self.driver:
                    try:
                        self.driver.close()
                    except Exception:
                        pass
            finally:
                self.driver = None
                self._create_driver()
    
    def close(self):
        if self.driver:
            self.driver.close()

    def _result_to_dicts(self, result) -> List[Dict[str, Any]]:
        """Convert a neo4j Result into a list of dictionaries."""
        records: List[Dict[str, Any]] = []
        for record in result:
            record_dict: Dict[str, Any] = {}
            for key in record.keys():
                value = record[key]
                # Convert Neo4j types to Python types
                if hasattr(value, "items"):  # Node or Relationship
                    record_dict[key] = dict(value.items())
                elif hasattr(value, "__iter__") and not isinstance(value, str):  # Path or list
                    record_dict[key] = list(value)
                else:
                    record_dict[key] = value
            records.append(record_dict)
        return records

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """Create an explicit Neo4j transaction.

        All writes executed on the returned transaction will either commit together,
        or roll back entirely if any exception is raised.
        """
        if not self.driver:
            raise Exception("Neo4j driver not initialized. Check connection settings.")

        with self.driver.session(database=self.database) as session:
            tx = session.begin_transaction()
            try:
                yield tx
            except Exception:
                try:
                    tx.rollback()
                finally:
                    # Preserve the original exception
                    pass
                raise
            else:
                tx.commit()
    
    def execute_query(self, query: str, parameters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Execute a Cypher query and return results as a list of dictionaries."""
        if not self.driver:
            raise Exception("Neo4j driver not initialized. Check connection settings.")

        params = parameters or {}
        last_err: Optional[Exception] = None

        # Aura/bolt connections can occasionally become defunct ("SessionExpired: Failed to read from defunct connection").
        # Retry once with a fresh driver.
        for attempt in range(2):
            try:
                with self.driver.session(database=self.database) as session:
                    try:
                        # neo4j-python-driver supports timeout in newer versions; if unsupported, fall back.
                        result = session.run(query, params, timeout=30)
                    except TypeError:
                        result = session.run(query, params)
                    return self._result_to_dicts(result)
            except (SessionExpired, ServiceUnavailable, OSError) as e:
                last_err = e
                logger.warning(f"Neo4j transient session error (attempt {attempt + 1}/2): {e}")
                self._recreate_driver()
            except Exception as e:
                logger.error(f"Error executing query: {e}")
                raise

        # If we exhausted retries, surface the original transient error.
        assert last_err is not None
        raise last_err

    def execute_query_in_tx(self, tx: Any, query: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Execute a Cypher query within an existing transaction."""
        try:
            result = tx.run(query, parameters or {})
            # Materialize results now, so errors surface before commit
            return self._result_to_dicts(result)
        except Exception as e:
            logger.error(f"Error executing query in transaction: {e}")
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