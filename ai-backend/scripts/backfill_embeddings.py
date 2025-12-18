import os
import sys
import logging
import asyncio
from typing import List, Dict, Any, Optional, Set

from dotenv import load_dotenv

# Add the parent directory to sys.path to allow imports from app
# Assumes this script is in ai-backend/scripts/
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Load backend env vars (Neo4j/OpenAI/etc.) when running as a standalone script.
# This mirrors `app/main.py` behavior and prevents accidental fallback to localhost defaults.
_DOTENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(_DOTENV_PATH)

from app.lib.logging_config import setup_logger
from app.lib.neo4j_client import neo4j_client
from app.lib.embeddings import generate_embedding_sync
from app.lib.schema_runtime import derive_embedding_config_from_schema, load_schema_payload
# Reuse ID logic from uploader to ensure we match nodes correctly
from app.lib.neo4j_uploader import get_id_prop_for_label

logger = setup_logger("backfill-embeddings")

def _sample_one_node_keys(label: str) -> List[str]:
    """Return keys(n) for a single node of the label (for diagnostics)."""
    query = f"MATCH (n:`{label}`) RETURN keys(n) as k LIMIT 1"
    rows = neo4j_client.execute_query(query)
    if not rows:
        return []
    k = rows[0].get("k")
    return [x for x in k if isinstance(x, str)] if isinstance(k, list) else []

def _count_label_nodes(label: str) -> int:
    query = f"MATCH (n:`{label}`) RETURN count(n) as c"
    rows = neo4j_client.execute_query(query)
    c = rows[0].get("c") if rows else 0
    return int(c or 0)

def _count_nodes_with_key(label: str, key: str) -> int:
    """Count nodes where the property key exists on the node (not just non-null)."""
    query = f"""
    MATCH (n:`{label}`)
    WHERE $key IN keys(n)
    RETURN count(n) as c
    """
    rows = neo4j_client.execute_query(query, {"key": key})
    c = rows[0].get("c") if rows else 0
    return int(c or 0)

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

        # Canonical schema validation: if schema_v3.json is the source of truth, then
        # the DB should contain those keys. If it doesn't, we want a loud, actionable error.
        total_nodes = _count_label_nodes(label)
        if total_nodes == 0:
            logger.info(f"  - No nodes found for label '{label}', skipping")
            continue

        missing_keys: List[str] = []
        if _count_nodes_with_key(label, id_prop) == 0:
            missing_keys.append(id_prop)
        for p in target_props:
            # Only validate text props; embeddings may legitimately be absent pre-backfill.
            if _count_nodes_with_key(label, p) == 0:
                missing_keys.append(p)

        if missing_keys and os.getenv("ALLOW_SCHEMA_MISMATCH", "0") not in {"1", "true", "TRUE", "yes", "YES"}:
            sample_keys = _sample_one_node_keys(label)
            logger.error(
                f"Schema mismatch for label '{label}'. Connected DB has {total_nodes} '{label}' nodes, "
                f"but none of them contain canonical keys: {sorted(set(missing_keys))}. "
                f"Sample keys(n) from one '{label}' node: {sample_keys}.\n"
                f"This usually means you're pointing at the wrong Neo4j database/instance, or the data was imported with an older schema.\n"
                f"Fix by connecting to the correct Aura DB (check NEO4J_URI/NEO4J_DATABASE) or re-import/migrate to schema_v3.json.\n"
                f"If you *intentionally* want to proceed despite mismatches, set ALLOW_SCHEMA_MISMATCH=1."
            )
            return {"success": False, "error": f"Schema mismatch for label '{label}' (see logs)."}
        
        for prop_name in target_props:
            embedding_field = f"{prop_name}_embedding"
            
            # 3. Find nodes missing this embedding.
            # Use dynamic property access (n[$prop]) to avoid "unknown property" warnings
            # when schemas drift between environments.
            count_query = f"""
            MATCH (n:`{label}`)
            WHERE $prop IN keys(n)
              AND n[$prop] IS NOT NULL
              AND toString(n[$prop]) <> ""
              AND (n[$embedding_field] IS NULL OR size(n[$embedding_field]) = 0)
            RETURN count(n) as c
            """
            query = f"""
            MATCH (n:`{label}`)
            WHERE $prop IN keys(n)
              AND n[$prop] IS NOT NULL
              AND toString(n[$prop]) <> ""
              AND (n[$embedding_field] IS NULL OR size(n[$embedding_field]) = 0)
            RETURN
              n[$id_prop] as id,
              n[$prop] as text
            LIMIT $limit
            """
            
            try:
                batch_limit = int(os.getenv("BACKFILL_BATCH_SIZE", "250"))
                updated_for_prop = 0
                total_missing = 0

                try:
                    rows = neo4j_client.execute_query(
                        count_query,
                        {"prop": prop_name, "embedding_field": embedding_field},
                    )
                    total_missing = int((rows[0].get("c") if rows else 0) or 0)
                except Exception as e:
                    logger.warning(f"  - {label}.{prop_name}: failed to count missing embeddings: {e}")

                if total_missing == 0:
                    logger.info(f"  - {label}.{prop_name}: 0 missing embeddings")
                    continue

                while True:
                    results = neo4j_client.execute_query(
                        query,
                        {"prop": prop_name, "embedding_field": embedding_field, "id_prop": id_prop, "limit": batch_limit},
                    )
                    if not results:
                        break

                    if updated_for_prop == 0:
                        logger.info(
                            f"  - {label}.{prop_name} -> {embedding_field}: {total_missing} missing "
                            f"(processing in batches of {batch_limit})"
                        )

                    for i, record in enumerate(results):
                        node_id = record.get("id")
                        text = record.get("text")

                        if not node_id:
                            logger.warning("    Skipping node with missing ID")
                            continue
                        if not isinstance(text, str) or not text.strip():
                            logger.warning(f"    Skipping node {label}({node_id}) with empty text")
                            continue

                        try:
                            # Run sync function in thread pool to not block async loop if called from async context
                            embedding = await asyncio.to_thread(generate_embedding_sync, text)

                            update_query = f"""
                            MATCH (n:`{label}` {{{id_prop}: $id}})
                            SET n[$embedding_field] = $embedding
                            """
                            neo4j_client.execute_query(
                                update_query, {"id": node_id, "embedding": embedding, "embedding_field": embedding_field}
                            )

                            total_updated += 1
                            updated_for_prop += 1

                            if updated_for_prop % 25 == 0:
                                logger.info(f"    Updated {updated_for_prop} embeddings for {label}.{prop_name} so far...")
                        except Exception as e:
                            logger.error(f"    Failed to process node {label}({node_id}) for '{prop_name}': {e}")

                if updated_for_prop:
                    details.append(f"{label}.{prop_name}: updated {updated_for_prop}")
                        
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
