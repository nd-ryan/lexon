import os
import sys
import logging
import asyncio
from typing import List, Dict, Any

# Add the parent directory to sys.path to allow imports from app
# Assumes this script is in ai-backend/scripts/
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.lib.logging_config import setup_logger
from app.lib.neo4j_client import neo4j_client
from app.lib.embeddings import generate_embedding_sync
from app.lib.schema_runtime import derive_embedding_config_from_schema, load_schema_payload
# Reuse ID logic from uploader to ensure we match nodes correctly
from app.lib.neo4j_uploader import get_id_prop_for_label

logger = setup_logger("backfill-embeddings")

async def backfill_embeddings():
    logger.info("Starting embedding backfill...")
    
    # 1. Derive configuration
    try:
        config = derive_embedding_config_from_schema()
        schema_payload = load_schema_payload()
    except Exception as e:
        logger.error(f"Failed to load schema/config: {e}")
        return {"success": False, "error": str(e)}

    if not config:
        logger.info("No embedding configurations found in schema.")
        return {"success": True, "total_updated": 0, "message": "No config found"}

    logger.info(f"Found embedding configuration for labels: {list(config.keys())}")

    total_updated = 0
    details = []

    # 2. Iterate over each label and its configured embedding properties
    for label, target_props in config.items():
        logger.info(f"Processing label: {label}")
        
        # Get the unique ID property for this label (e.g. case_id, party_id)
        id_prop = get_id_prop_for_label(label, schema_payload)
        
        for prop_name in target_props:
            embedding_field = f"{prop_name}_embedding"
            
            # 3. Find nodes missing this embedding
            # We look for nodes where:
            # - The source text property exists and is not empty
            # - The embedding property is NULL
            query = f"""
            MATCH (n:`{label}`)
            WHERE n.{prop_name} IS NOT NULL 
              AND toString(n.{prop_name}) <> ""
              AND n.{embedding_field} IS NULL
            RETURN n.{id_prop} as id, n.{prop_name} as text
            """
            
            try:
                results = neo4j_client.execute_query(query)
                count = len(results)
                if count == 0:
                    # logger.info(f"  - {prop_name} -> {embedding_field}: All caught up (0 missing)")
                    continue
                
                logger.info(f"  - {prop_name} -> {embedding_field}: Found {count} nodes missing embeddings")
                details.append(f"{label}.{prop_name}: {count} missing")

                for i, record in enumerate(results):
                    node_id = record.get("id")
                    text = record.get("text")
                    
                    if not node_id:
                        logger.warning(f"    Skipping node with missing ID")
                        continue
                    if not isinstance(text, str) or not text.strip():
                        logger.warning(f"    Skipping node {node_id} with empty text")
                        continue
                        
                    try:
                        # Generate embedding
                        # logger.info(f"    Generating embedding for {label}:{node_id} ({len(text)} chars)")
                        # Run sync function in thread pool to not block async loop if called from async context
                        embedding = await asyncio.to_thread(generate_embedding_sync, text)
                        
                        # Update node in Neo4j
                        update_query = f"""
                        MATCH (n:`{label}` {{{id_prop}: $id}})
                        SET n.`{embedding_field}` = $embedding
                        """
                        neo4j_client.execute_query(update_query, {"id": node_id, "embedding": embedding})
                        total_updated += 1
                        
                        # Progress log every 10 items
                        if (i + 1) % 10 == 0:
                            logger.info(f"    Updated {i + 1}/{count}...")
                            
                    except Exception as e:
                        logger.error(f"    Failed to process node {label}({node_id}): {e}")
                        
            except Exception as e:
                logger.error(f"Error querying/processing {label}.{prop_name}: {e}")
                return {"success": False, "error": str(e)}

    logger.info(f"Backfill complete. Total properties updated: {total_updated}")
    return {
        "success": True, 
        "total_updated": total_updated, 
        "details": details
    }

def main():
    # Helper for running from command line
    asyncio.run(backfill_embeddings())

if __name__ == "__main__":
    main()
