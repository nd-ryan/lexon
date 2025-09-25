import os
import asyncio
import logging
from typing import List, Dict, Any, Optional
from openai import OpenAI
from .neo4j_client import neo4j_client

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

def _load_embedding_config() -> Dict[str, List[str]]:
    """Derive embedding targets from schema.json.

    For each label, include STRING properties that have a corresponding
    `<property>_embedding` field declared in schema.json.
    """
    try:
        from app.lib.schema_runtime import derive_embedding_config_from_schema
        return derive_embedding_config_from_schema()
    except Exception as e:
        logger.warning(f"Embedding config: failed to derive from schema.json: {e}")
        return {}

def _determine_id_prop(label: str, sample_row: Dict[str, Any]) -> str:
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
        if isinstance(k, str) and k.endswith("_id"):
            return k
    return "id"

def generate_embeddings_for_nodes(
    nodes_by_label: Dict[str, List[Dict[str, Any]]],
    config: Optional[Dict[str, List[str]]] = None,
) -> bool:
    """Generate embeddings for selected properties on recently imported nodes.

    - For each label in nodes_by_label, look up properties to embed from `config`.
    - For each node instance, if the property exists and is non-empty, compute
      an OpenAI embedding and store it as `<property>_embedding` on the node in Neo4j.

    Returns True on success (best-effort; logs and continues on individual failures).
    """
    try:
        if client is None:
            logger.warning("Embeddings disabled: OPENAI_API_KEY is not set")
            return False
        if not nodes_by_label:
            logger.info("No nodes provided for embedding generation; skipping")
            return True

        cfg = config or _load_embedding_config()
        total_requests = 0
        total_updated = 0

        for label, nodes in nodes_by_label.items():
            if not nodes:
                continue

            target_props = cfg.get(label, [])
            if not target_props:
                logger.info(f"Embeddings: no configured properties for label '{label}', skipping {len(nodes)} nodes")
                continue

            # Determine id prop using first row as sample
            id_prop = _determine_id_prop(label, nodes[0])
            logger.debug(f"Embedding: label={label}, id_prop={id_prop}, target_props={target_props}")

            # Counters per property
            per_prop_attempts: Dict[str, int] = {p: 0 for p in target_props}
            per_prop_embedded: Dict[str, int] = {p: 0 for p in target_props}

            for node in nodes:
                node_id = node.get(id_prop)
                if not node_id:
                    continue

                for prop_name in target_props:
                    # Only use exact property from schema-derived config
                    raw_value = node.get(prop_name)
                    if not isinstance(raw_value, str):
                        continue
                    text = raw_value.strip()
                    if not text:
                        continue
                    per_prop_attempts[prop_name] += 1

                    try:
                        # Compute embedding for the property text
                        response = client.embeddings.create(
                            model="text-embedding-3-small",
                            input=text,
                        )
                        vector = response.data[0].embedding
                        total_requests += 1

                        # Persist to Neo4j on a per-property embedding field
                        # Use the original configured prop name for the embedding key
                        embedding_field = f"{prop_name}_embedding"
                        update_cypher = (
                            f"MATCH (n:{label} {{{id_prop}: $id}}) "
                            f"SET n.`{embedding_field}` = $vec"
                        )
                        neo4j_client.execute_query(update_cypher, {"id": node_id, "vec": vector})
                        total_updated += 1
                        per_prop_embedded[prop_name] += 1
                    except Exception as e:
                        logger.error(
                            f"Embedding failed for {label}({id_prop}={node_id}) property '{prop_name}': {e}"
                        )
                        # Continue with other properties/nodes
                        continue

            # Summarize per-label results
            for p in target_props:
                if per_prop_attempts[p] == 0:
                    logger.info(f"Embeddings: label='{label}' property='{p}' had no candidates in batch (check property names)")
                else:
                    logger.info(f"Embeddings: label='{label}' property='{p}' embedded {per_prop_embedded[p]}/{per_prop_attempts[p]} candidates")

        logger.info(
            f"Embedding generation complete: {total_updated}/{total_requests} properties updated"
        )
        return True
    except Exception as e:
        logger.error(f"Error in generate_embeddings_for_nodes: {e}")
        return False

async def generate_embeddings_for_cases(case_ids: List[str]) -> bool:
    """
    Generate embeddings for the given case IDs and store them in Neo4j.
    
    Args:
        case_ids: List of case IDs to generate embeddings for
        
    Returns:
        True if successful, False otherwise
    """
    try:
        if not case_ids:
            logger.warning("No case IDs provided for embedding generation")
            return True
        
        # Get case summaries from Neo4j
        query = """
        MATCH (c:Case) 
        WHERE c.case_id IN $case_ids 
        RETURN c.case_id AS id, c.summary AS txt
        """
        
        records = neo4j_client.execute_query(query, {"case_ids": case_ids})
        
        if not records:
            logger.warning(f"No cases found for IDs: {case_ids}")
            return True
        
        # Generate embeddings for each case
        for record in records:
            case_id = record.get('id')
            summary_text = record.get('txt')
            
            if not summary_text:
                logger.warning(f"No summary text found for case {case_id}")
                continue
            
            try:
                # Generate embedding using OpenAI
                response = client.embeddings.create(
                    model="text-embedding-3-small",
                    input=summary_text
                )
                
                embedding_vector = response.data[0].embedding
                
                # Store embedding in Neo4j
                update_query = """
                MATCH (c:Case {case_id: $case_id})
                SET c.summary_embedding = $embedding
                """
                
                neo4j_client.execute_query(update_query, {
                    "case_id": case_id,
                    "embedding": embedding_vector
                })
                
                logger.info(f"Generated and stored embedding for case {case_id}")
                
            except Exception as e:
                logger.error(f"Error generating embedding for case {case_id}: {e}")
                continue
        
        return True
        
    except Exception as e:
        logger.error(f"Error in generate_embeddings_for_cases: {e}")
        return False





def generate_embedding_sync(text: str) -> List[float]:
    """
    Synchronous function to generate an embedding for text.
    
    Args:
        text: Text to generate embedding for
        
    Returns:
        Embedding vector as list of floats
    """
    try:
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Error generating embedding: {e}")
        raise 