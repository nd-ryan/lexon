"""API routes for retroactive concept linking - AI-powered linking of shared nodes to case data.

This module provides endpoints to:
1. Get schema info about linkable concepts
2. List concepts by type
3. Run AI analysis to find matches
4. Commit approved matches to Postgres and Neo4j

Completely separate from case extraction flows.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.lib.security import get_api_key
from app.lib.db import get_db
from app.lib.logging_config import setup_logger
from app.lib.concept_linking import (
    get_schema_info,
    get_linkable_concepts,
    analyze_concept_matches,
    list_concepts_by_label,
    fetch_concept_details,
    commit_matches,
    ApprovedMatch,
)


logger = setup_logger("concept-linking")
router = APIRouter(prefix="/concept-linking", dependencies=[Depends(get_api_key)])


def get_user_id(request: Request) -> str:
    """Extract user ID from X-User-Id header (set by Next.js API routes)."""
    return request.headers.get("X-User-Id", "admin")


# ============================================================================
# Schema Endpoint
# ============================================================================

@router.get("/schema")
def get_linking_schema():
    """Get schema information for concept linking.
    
    Returns the list of linkable concept types (Doctrine, Policy, etc.)
    and which source labels can link to each concept type.
    All data is derived from schema_v3.json.
    """
    try:
        schema_info = get_schema_info()
        
        return {
            "success": True,
            "linkableConcepts": schema_info["linkable_concepts"],
            "conceptProperties": schema_info["concept_properties"],
            "relationships": schema_info["relationships"],
        }
    except Exception as e:
        logger.error(f"Failed to get linking schema: {e}")
        raise HTTPException(500, f"Failed to get schema info: {e}")


# ============================================================================
# Concepts List Endpoint
# ============================================================================

@router.get("/concepts/{label}")
def list_concepts(
    label: str,
    limit: int = Query(100, le=500),
):
    """List all concepts of a given type.
    
    Args:
        label: The concept type (e.g., "Doctrine", "Policy", "FactPattern", "Law")
        limit: Maximum concepts to return
        
    Returns:
        List of concepts with their properties and connection counts.
    """
    linkable = get_linkable_concepts()
    
    if label not in linkable:
        valid_labels = list(linkable.keys())
        raise HTTPException(
            400, 
            f"'{label}' is not a linkable concept type. Valid types: {valid_labels}"
        )
    
    try:
        concepts = list_concepts_by_label(label, limit=limit)
        
        return {
            "success": True,
            "label": label,
            "concepts": concepts,
            "targets": linkable[label],  # e.g., ["Issue", "Argument"]
        }
    except Exception as e:
        logger.error(f"Failed to list {label} concepts: {e}")
        raise HTTPException(500, f"Failed to list concepts: {e}")


# ============================================================================
# Concept Detail Endpoint
# ============================================================================

@router.get("/concepts/{label}/{concept_id}")
def get_concept(label: str, concept_id: str):
    """Get a single concept's details.
    
    Args:
        label: The concept type
        concept_id: The concept's ID
        
    Returns:
        Concept properties and metadata.
    """
    linkable = get_linkable_concepts()
    
    if label not in linkable:
        valid_labels = list(linkable.keys())
        raise HTTPException(
            400,
            f"'{label}' is not a linkable concept type. Valid types: {valid_labels}"
        )
    
    try:
        props = fetch_concept_details(label, concept_id)
        if not props:
            raise HTTPException(404, f"Concept not found: {label}:{concept_id}")
        
        # Filter out embeddings
        filtered_props = {
            k: v for k, v in props.items()
            if not k.endswith("_embedding") and not k.endswith("_upload_code")
        }
        
        return {
            "success": True,
            "label": label,
            "id": concept_id,
            "name": filtered_props.get("name", ""),
            "description": filtered_props.get("description", filtered_props.get("text", "")),
            "properties": filtered_props,
            "targets": linkable[label],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get concept {label}:{concept_id}: {e}")
        raise HTTPException(500, f"Failed to get concept: {e}")


# ============================================================================
# Analysis Endpoint
# ============================================================================

class AnalyzeRequest(BaseModel):
    conceptLabel: str
    conceptId: str
    batchSize: int = 100
    maxNodes: int = 1000


@router.post("/analyze")
def analyze_matches(body: AnalyzeRequest, request: Request):
    """Run AI analysis to find matching nodes for a concept.
    
    This analyzes all target nodes (Arguments, Issues, etc.) that don't already
    have a relationship to the specified concept, and returns suggested matches.
    
    Args:
        conceptLabel: The concept type (e.g., "Doctrine")
        conceptId: The concept's ID
        batchSize: Number of nodes per OpenAI call (default 20)
        maxNodes: Maximum total nodes to analyze (default 1000)
        
    Returns:
        List of suggested matches.
    """
    user_id = get_user_id(request)
    logger.info(f"Starting concept analysis for {body.conceptLabel}:{body.conceptId} by {user_id}")
    
    linkable = get_linkable_concepts()
    
    if body.conceptLabel not in linkable:
        valid_labels = list(linkable.keys())
        raise HTTPException(
            400,
            f"'{body.conceptLabel}' is not a linkable concept type. Valid types: {valid_labels}"
        )
    
    try:
        result = analyze_concept_matches(
            concept_label=body.conceptLabel,
            concept_id=body.conceptId,
            batch_size=body.batchSize,
            max_nodes=body.maxNodes,
        )
        
        # Convert dataclass matches to dicts
        matches = [
            {
                "nodeId": m.node_id,
                "nodeLabel": m.node_label,
                "caseId": m.case_id,
                "caseName": m.case_name,
                "nodeTextPreview": m.node_text_preview,
            }
            for m in result.matches
        ]
        
        logger.info(f"Analysis complete: {result.total_analyzed} analyzed, {len(matches)} matches")
        
        return {
            "success": True,
            "conceptLabel": result.concept_label,
            "conceptId": result.concept_id,
            "conceptName": result.concept_name,
            "totalAnalyzed": result.total_analyzed,
            "matches": matches,
            "matchCount": len(matches),
        }
    
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise HTTPException(500, f"Analysis failed: {e}")


# ============================================================================
# Commit Endpoint
# ============================================================================

class CommitMatchRequest(BaseModel):
    nodeId: str
    nodeLabel: str
    caseId: str


class CommitRequest(BaseModel):
    conceptLabel: str
    conceptId: str
    matches: List[CommitMatchRequest]


@router.post("/commit")
def commit_approved_matches(
    body: CommitRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Commit approved matches to Postgres and Neo4j.
    
    Creates relationships between the concept and the selected target nodes
    in both Neo4j (knowledge graph) and Postgres (case extracted data).
    
    Args:
        conceptLabel: The concept type (e.g., "Doctrine")
        conceptId: The concept's ID
        matches: List of approved matches to commit
        
    Returns:
        Commit result with counts of created relationships.
    """
    user_id = get_user_id(request)
    logger.info(
        f"Committing {len(body.matches)} matches for "
        f"{body.conceptLabel}:{body.conceptId} by {user_id}"
    )
    
    linkable = get_linkable_concepts()
    
    if body.conceptLabel not in linkable:
        valid_labels = list(linkable.keys())
        raise HTTPException(
            400,
            f"'{body.conceptLabel}' is not a linkable concept type. Valid types: {valid_labels}"
        )
    
    if not body.matches:
        raise HTTPException(400, "No matches provided")
    
    try:
        # Convert to ApprovedMatch objects
        approved = [
            ApprovedMatch(
                node_id=m.nodeId,
                node_label=m.nodeLabel,
                case_id=m.caseId,
            )
            for m in body.matches
        ]
        
        result = commit_matches(
            concept_label=body.conceptLabel,
            concept_id=body.conceptId,
            matches=approved,
            user_id=user_id,
            db=db,
        )
        
        logger.info(
            f"Commit complete: {result.neo4j_relationships_created} Neo4j, "
            f"{result.postgres_cases_updated} Postgres, {len(result.errors)} errors"
        )
        
        return {
            "success": result.success,
            "neo4jRelationshipsCreated": result.neo4j_relationships_created,
            "postgresCasesUpdated": result.postgres_cases_updated,
            "errors": result.errors if result.errors else None,
        }
    
    except Exception as e:
        logger.error(f"Commit failed: {e}")
        raise HTTPException(500, f"Commit failed: {e}")


# ============================================================================
# Count Targets Endpoint (for UI preview)
# ============================================================================

@router.get("/concepts/{label}/{concept_id}/target-counts")
def get_target_counts(label: str, concept_id: str):
    """Get counts of potential targets for analysis.
    
    Returns the number of Arguments, Issues, etc. that don't yet have
    a relationship to this concept. Useful for showing the admin how
    many nodes will be analyzed before running the full analysis.
    """
    from app.lib.neo4j_client import neo4j_client
    from app.lib.concept_linking.schema_parser import (
        get_concept_targets,
        get_relationship_label,
        get_concept_id_property,
        get_target_id_property,
    )
    
    linkable = get_linkable_concepts()
    
    if label not in linkable:
        valid_labels = list(linkable.keys())
        raise HTTPException(
            400,
            f"'{label}' is not a linkable concept type. Valid types: {valid_labels}"
        )
    
    try:
        concept_id_prop = get_concept_id_property(label)
        targets = get_concept_targets(label)
        
        counts = {}
        
        for target_label in targets:
            relationship_label = get_relationship_label(target_label, label)
            if not relationship_label:
                counts[target_label] = 0
                continue
            
            target_id_prop = get_target_id_property(target_label)
            
            # Count nodes without this specific relationship
            query = f"""
                MATCH (n:{target_label})
                WHERE NOT EXISTS {{
                    MATCH (n)-[:{relationship_label}]->(c:{label} {{{concept_id_prop}: $concept_id}})
                }}
                RETURN count(n) as count
            """
            
            results = neo4j_client.execute_query(query, {"concept_id": concept_id})
            counts[target_label] = results[0]["count"] if results else 0
        
        total = sum(counts.values())
        
        return {
            "success": True,
            "conceptLabel": label,
            "conceptId": concept_id,
            "targetCounts": counts,
            "totalTargets": total,
        }
    
    except Exception as e:
        logger.error(f"Failed to get target counts for {label}:{concept_id}: {e}")
        raise HTTPException(500, f"Failed to get target counts: {e}")
