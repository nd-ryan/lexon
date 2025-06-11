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

async def find_similar_cases(query_text: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Find cases similar to the given query text using vector similarity.
    
    Args:
        query_text: Text to find similar cases for
        limit: Maximum number of similar cases to return
        
    Returns:
        List of similar cases with similarity scores
    """
    try:
        # Generate embedding for the query text
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=query_text
        )
        
        query_embedding = response.data[0].embedding
        
        # Use Neo4j vector similarity (requires Neo4j 5.x with vector support)
        # Note: This requires Neo4j to have vector indexing enabled
        similarity_query = """
        MATCH (c:Case)
        WHERE c.embedding IS NOT NULL
        WITH c, gds.similarity.cosine(c.embedding, $query_embedding) AS similarity
        ORDER BY similarity DESC
        LIMIT $limit
        RETURN c.case_id, c.case_name, c.summary, similarity
        """
        
        try:
            results = neo4j_client.execute_query(similarity_query, {
                "query_embedding": query_embedding,
                "limit": limit
            })
            
            return results
            
        except Exception as neo4j_error:
            # Fallback: If Neo4j doesn't support vector operations, 
            # we can implement similarity calculation in Python
            logger.warning(f"Neo4j vector similarity not available: {neo4j_error}")
            return await _fallback_similarity_search(query_embedding, limit)
    
    except Exception as e:
        logger.error(f"Error in find_similar_cases: {e}")
        return []

async def _fallback_similarity_search(query_embedding: List[float], limit: int) -> List[Dict[str, Any]]:
    """
    Fallback similarity search using Python-based cosine similarity.
    
    Args:
        query_embedding: The query embedding vector
        limit: Maximum number of results to return
        
    Returns:
        List of similar cases with similarity scores
    """
    import numpy as np
    
    try:
        # Get all cases with embeddings
        query = """
        MATCH (c:Case)
        WHERE c.embedding IS NOT NULL
        RETURN c.case_id, c.case_name, c.summary, c.embedding
        """
        
        cases = neo4j_client.execute_query(query)
        
        if not cases:
            return []
        
        # Calculate similarities
        similarities = []
        query_vec = np.array(query_embedding)
        
        for case in cases:
            case_embedding = np.array(case['c.embedding'])
            
            # Calculate cosine similarity
            similarity = np.dot(query_vec, case_embedding) / (
                np.linalg.norm(query_vec) * np.linalg.norm(case_embedding)
            )
            
            similarities.append({
                'case_id': case['c.case_id'],
                'case_name': case['c.case_name'],
                'summary': case['c.summary'],
                'similarity': float(similarity)
            })
        
        # Sort by similarity and return top results
        similarities.sort(key=lambda x: x['similarity'], reverse=True)
        return similarities[:limit]
        
    except Exception as e:
        logger.error(f"Error in fallback similarity search: {e}")
        return []

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