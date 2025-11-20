
import os
import sys
import asyncio
import logging
from typing import List, Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env file in ai-backend root
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)

# Ensure we can import from app
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.lib.neo4j_client import neo4j_client

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("debug_indices")

async def run_diagnostics():
    logger.info("--- Neo4j Vector Index Diagnostic ---")
    
    if not neo4j_client.driver:
        logger.error("Neo4j driver not initialized.")
        return

    # 1. List all vector indexes
    logger.info("1. Listing Vector Indexes:")
    try:
        query = "SHOW VECTOR INDEXES"
        indexes = neo4j_client.execute_query(query)
        if not indexes:
            logger.warning("No vector indexes found via SHOW VECTOR INDEXES.")
        for idx in indexes:
            name = idx.get("name")
            state = idx.get("state", "UNKNOWN")
            labels = idx.get("labelsOrTypes", [])
            props = idx.get("properties", [])
            provider = idx.get("indexProvider", "N/A")
            logger.info(f" - Index: {name} | State: {state} | Labels: {labels} | Props: {props}")
    except Exception as e:
        logger.error(f"Failed to list indexes: {e}")

    # 2. Check Data Counts for Key Labels
    labels_to_check = ["Case", "Issue", "FactPattern", "Doctrine"]
    logger.info("\n2. Checking Node Counts & Embeddings:")
    
    # We know the standard embedding props from schema or convention
    # Case -> summary_embedding
    # Issue -> text_embedding
    # FactPattern -> description_embedding
    # Doctrine -> description_embedding
    
    embedding_props = {
        "Case": "summary_embedding",
        "Issue": "text_embedding",
        "FactPattern": "description_embedding",
        "Doctrine": "description_embedding"
    }

    for label in labels_to_check:
        emb_prop = embedding_props.get(label, "embedding") # fallback
        
        try:
            # Count total nodes
            count_q = f"MATCH (n:{label}) RETURN count(n) as count"
            res = neo4j_client.execute_query(count_q)
            total = res[0]['count'] if res else 0
            
            # Count nodes with non-null embedding
            emb_count_q = f"MATCH (n:{label}) WHERE n.{emb_prop} IS NOT NULL RETURN count(n) as count"
            res_emb = neo4j_client.execute_query(emb_count_q)
            total_emb = res_emb[0]['count'] if res_emb else 0
            
            logger.info(f" - {label}: {total} nodes total, {total_emb} have property '{emb_prop}'")
            
            if total_emb > 0:
                # Check dimension of one embedding
                dim_q = f"MATCH (n:{label}) WHERE n.{emb_prop} IS NOT NULL RETURN size(n.{emb_prop}) as dim LIMIT 1"
                res_dim = neo4j_client.execute_query(dim_q)
                dim = res_dim[0]['dim'] if res_dim else "N/A"
                logger.info(f"   (Sample embedding dimension: {dim})")
                
        except Exception as e:
            logger.error(f"Failed to check label {label}: {e}")

    # 3. Test Vector Search (Case)
    logger.info("\n3. Test Vector Search on 'Case':")
    test_idx = "case_summary_embedding_index"
    # Create dummy 1536-dim vector
    dummy_vec = [0.001] * 1536
    
    query = f"""
    CALL db.index.vector.queryNodes($index_name, $limit, $embedding)
    YIELD node, score
    RETURN count(*) as match_count
    """
    try:
        res = neo4j_client.execute_query(query, {
            "index_name": test_idx,
            "limit": 5,
            "embedding": dummy_vec
        })
        count = res[0]['match_count'] if res else 0
        logger.info(f" - Querying {test_idx} with dummy vector returned {count} rows.")
    except Exception as e:
        logger.error(f"Test vector search failed: {e}")

if __name__ == "__main__":
    # Because neo4j_client.execute_query is synchronous/blocking (based on the file I read), 
    # we don't actually need asyncio unless we change the client. 
    # The file ai-backend/app/lib/neo4j_client.py shows execute_query is synchronous (def execute_query...).
    # So we can run main logic directly.
    
    # However, the surrounding code usually runs in async context. 
    # I'll just call the function synchronously since the client is sync.
    loop = asyncio.new_event_loop()
    loop.run_until_complete(run_diagnostics())
    loop.close()

