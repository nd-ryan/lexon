import os
import asyncio
import logging
from typing import List, Dict, Any, Optional
from openai import OpenAI
from .neo4j_client import neo4j_client

logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
                SET c.embedding = $embedding
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