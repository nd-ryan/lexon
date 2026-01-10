"""Commit service for concept linking - writes approved matches to Postgres and Neo4j.

This service handles the persistence of concept links after admin approval:
1. Creates relationship edges in Neo4j
2. Updates cases.extracted JSON in Postgres to include the new edges
3. Optionally updates cases.kg_extracted if the case has been published

Completely separate from case extraction - independent persistence logic.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.lib.neo4j_client import neo4j_client
from app.lib.logging_config import setup_logger

from .schema_parser import (
    get_concept_id_property,
    get_relationship_label,
)


logger = setup_logger("concept-linking-commit")


@dataclass
class ApprovedMatch:
    """A single approved match to commit."""
    node_id: str
    node_label: str
    case_id: str


@dataclass
class CommitResult:
    """Result of committing matches."""
    success: bool
    neo4j_relationships_created: int
    postgres_cases_updated: int
    errors: List[str]


def _get_target_id_property(target_label: str) -> str:
    """Get the ID property name for a target label."""
    import re
    snake = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", target_label)
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", snake)
    return f"{snake.lower()}_id"


def _create_neo4j_relationship(
    source_label: str,
    source_id: str,
    target_label: str,
    target_id: str,
    relationship_label: str,
) -> bool:
    """Create a relationship in Neo4j.
    
    Args:
        source_label: The source node type (e.g., "Argument")
        source_id: The source node's ID
        target_label: The target concept type (e.g., "Doctrine")
        target_id: The target concept's ID
        relationship_label: The relationship type (e.g., "RELATES_TO_DOCTRINE")
        
    Returns:
        True if successful, False otherwise.
    """
    source_id_prop = _get_target_id_property(source_label)
    target_id_prop = get_concept_id_property(target_label)
    
    query = f"""
        MATCH (source:{source_label} {{{source_id_prop}: $source_id}})
        MATCH (target:{target_label} {{{target_id_prop}: $target_id}})
        MERGE (source)-[r:{relationship_label}]->(target)
        RETURN count(r) as created
    """
    
    try:
        results = neo4j_client.execute_query(query, {
            "source_id": source_id,
            "target_id": target_id,
        })
        return len(results) > 0
    except Exception as e:
        logger.error(f"Failed to create Neo4j relationship {source_label}:{source_id} -> {target_label}:{target_id}: {e}")
        return False


def _find_case_for_node(db: Session, node_id: str, node_label: str) -> Optional[Dict[str, Any]]:
    """Find the case that contains a specific node.
    
    Searches Postgres cases.extracted JSON for the node.
    
    Args:
        db: SQLAlchemy session
        node_id: The node's ID
        node_label: The node type
        
    Returns:
        Dict with case_id and extracted data, or None if not found.
    """
    import os
    import re
    
    _SCHEMA_RAW = os.getenv("POSTGRES_SCHEMA", "public")
    POSTGRES_SCHEMA = _SCHEMA_RAW if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", _SCHEMA_RAW or "") else "public"
    
    id_prop = _get_target_id_property(node_label)
    
    # Search for the node in cases.extracted JSON
    query = text(f"""
        SELECT id, extracted, kg_extracted
        FROM {POSTGRES_SCHEMA}.cases
        WHERE extracted IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM jsonb_array_elements(extracted->'nodes') AS node
            WHERE node->>'label' = :label
              AND node->'properties'->>:id_prop = :node_id
          )
        LIMIT 1
    """)
    
    try:
        result = db.execute(query, {
            "label": node_label,
            "id_prop": id_prop,
            "node_id": node_id,
        }).fetchone()
        
        if result:
            return {
                "case_id": str(result.id),
                "extracted": result.extracted,
                "kg_extracted": result.kg_extracted,
            }
        return None
    except Exception as e:
        logger.error(f"Failed to find case for node {node_label}:{node_id}: {e}")
        return None


def _find_node_temp_id_in_extracted(
    extracted: Dict[str, Any],
    node_id: str,
    node_label: str,
) -> Optional[str]:
    """Find the temp_id of a node in the extracted data.
    
    Args:
        extracted: The case's extracted JSON data
        node_id: The node's permanent ID
        node_label: The node type
        
    Returns:
        The temp_id if found, None otherwise.
    """
    id_prop = _get_target_id_property(node_label)
    
    nodes = extracted.get("nodes", [])
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("label") != node_label:
            continue
        props = node.get("properties", {})
        if props.get(id_prop) == node_id:
            return node.get("temp_id")
    
    return None


def _add_edge_to_extracted(
    extracted: Dict[str, Any],
    from_id: str,
    to_id: str,
    relationship_label: str,
) -> Tuple[Dict[str, Any], bool]:
    """Add an edge to the extracted data.
    
    Args:
        extracted: The case's extracted JSON data
        from_id: The source node temp_id
        to_id: The target concept ID (permanent ID for shared nodes)
        relationship_label: The relationship type
        
    Returns:
        Tuple of (updated extracted data, was_added flag).
    """
    edges = extracted.get("edges", [])
    
    # Check if edge already exists
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if (edge.get("from") == from_id and 
            edge.get("to") == to_id and 
            edge.get("label") == relationship_label):
            # Edge already exists
            return extracted, False
    
    # Add new edge
    new_edge = {
        "from": from_id,
        "to": to_id,
        "label": relationship_label,
        "properties": {},
    }
    
    updated = dict(extracted)
    updated["edges"] = edges + [new_edge]
    
    return updated, True


def _update_case_extracted(
    db: Session,
    case_id: str,
    extracted: Dict[str, Any],
    kg_extracted: Optional[Dict[str, Any]],
    user_id: str,
) -> bool:
    """Update the case's extracted (and optionally kg_extracted) in Postgres.
    
    Args:
        db: SQLAlchemy session
        case_id: The case ID
        extracted: Updated extracted data
        kg_extracted: Updated kg_extracted data (or None to skip)
        user_id: The user making the change
        
    Returns:
        True if successful, False otherwise.
    """
    import os
    import re
    import json
    from sqlalchemy import text
    from datetime import datetime, timezone
    
    _SCHEMA_RAW = os.getenv("POSTGRES_SCHEMA", "public")
    POSTGRES_SCHEMA = _SCHEMA_RAW if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", _SCHEMA_RAW or "") else "public"
    
    try:
        if kg_extracted is not None:
            # Update both extracted and kg_extracted
            query = text(f"""
                UPDATE {POSTGRES_SCHEMA}.cases
                SET extracted = :extracted::jsonb,
                    kg_extracted = :kg_extracted::jsonb,
                    updated_at = :updated_at
                WHERE id = :case_id::uuid
            """)
            db.execute(query, {
                "case_id": case_id,
                "extracted": json.dumps(extracted),
                "kg_extracted": json.dumps(kg_extracted),
                "updated_at": datetime.now(timezone.utc),
            })
        else:
            # Update only extracted
            query = text(f"""
                UPDATE {POSTGRES_SCHEMA}.cases
                SET extracted = :extracted::jsonb,
                    updated_at = :updated_at
                WHERE id = :case_id::uuid
            """)
            db.execute(query, {
                "case_id": case_id,
                "extracted": json.dumps(extracted),
                "updated_at": datetime.now(timezone.utc),
            })
        
        return True
    except Exception as e:
        logger.error(f"Failed to update case {case_id}: {e}")
        return False


def commit_matches(
    concept_label: str,
    concept_id: str,
    matches: List[ApprovedMatch],
    user_id: str,
    db: Session,
) -> CommitResult:
    """Commit approved matches to both Neo4j and Postgres.
    
    This is the main entry point for committing concept links.
    
    Args:
        concept_label: The concept type (e.g., "Doctrine")
        concept_id: The concept's ID
        matches: List of approved matches to commit
        user_id: The user making the changes
        db: SQLAlchemy session
        
    Returns:
        CommitResult with counts and any errors.
    """
    logger.info(f"Committing {len(matches)} matches for {concept_label}:{concept_id}")
    
    neo4j_created = 0
    postgres_updated = 0
    errors: List[str] = []
    
    # Group matches by case for efficient Postgres updates
    matches_by_case: Dict[str, List[ApprovedMatch]] = {}
    
    for match in matches:
        # Get relationship label
        relationship_label = get_relationship_label(match.node_label, concept_label)
        if not relationship_label:
            errors.append(f"No relationship found for {match.node_label} -> {concept_label}")
            continue
        
        # Create Neo4j relationship
        if _create_neo4j_relationship(
            source_label=match.node_label,
            source_id=match.node_id,
            target_label=concept_label,
            target_id=concept_id,
            relationship_label=relationship_label,
        ):
            neo4j_created += 1
        else:
            errors.append(f"Failed to create Neo4j relationship for {match.node_label}:{match.node_id}")
        
        # Group by case for Postgres update
        if match.case_id:
            if match.case_id not in matches_by_case:
                matches_by_case[match.case_id] = []
            matches_by_case[match.case_id].append(match)
    
    # Update Postgres for each affected case
    processed_cases: Set[str] = set()
    
    for case_id, case_matches in matches_by_case.items():
        if case_id in processed_cases:
            continue
        
        # Find the case
        case_data = _find_case_for_node(db, case_matches[0].node_id, case_matches[0].node_label)
        if not case_data:
            # Try to find case by case_id directly
            import os
            import re
            from sqlalchemy import text
            
            _SCHEMA_RAW = os.getenv("POSTGRES_SCHEMA", "public")
            POSTGRES_SCHEMA = _SCHEMA_RAW if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", _SCHEMA_RAW or "") else "public"
            
            query = text(f"""
                SELECT id, extracted, kg_extracted
                FROM {POSTGRES_SCHEMA}.cases
                WHERE id = :case_id::uuid
            """)
            result = db.execute(query, {"case_id": case_id}).fetchone()
            if result:
                case_data = {
                    "case_id": str(result.id),
                    "extracted": result.extracted,
                    "kg_extracted": result.kg_extracted,
                }
        
        if not case_data:
            errors.append(f"Could not find case {case_id} in Postgres")
            continue
        
        extracted = case_data.get("extracted") or {}
        kg_extracted = case_data.get("kg_extracted")
        
        edges_added = 0
        
        for match in case_matches:
            relationship_label = get_relationship_label(match.node_label, concept_label)
            if not relationship_label:
                continue
            
            # Find the node's temp_id in extracted
            temp_id = _find_node_temp_id_in_extracted(extracted, match.node_id, match.node_label)
            if not temp_id:
                # Use the permanent ID as fallback (for shared nodes, the edge 'from' can be the perm ID)
                temp_id = match.node_id
            
            # Add edge to extracted
            extracted, added = _add_edge_to_extracted(
                extracted=extracted,
                from_id=temp_id,
                to_id=concept_id,
                relationship_label=relationship_label,
            )
            
            if added:
                edges_added += 1
                
                # Also update kg_extracted if it exists
                if kg_extracted:
                    kg_temp_id = _find_node_temp_id_in_extracted(kg_extracted, match.node_id, match.node_label)
                    if not kg_temp_id:
                        kg_temp_id = match.node_id
                    kg_extracted, _ = _add_edge_to_extracted(
                        extracted=kg_extracted,
                        from_id=kg_temp_id,
                        to_id=concept_id,
                        relationship_label=relationship_label,
                    )
        
        if edges_added > 0:
            # Save updates to Postgres
            if _update_case_extracted(
                db=db,
                case_id=case_data["case_id"],
                extracted=extracted,
                kg_extracted=kg_extracted if kg_extracted else None,
                user_id=user_id,
            ):
                postgres_updated += 1
            else:
                errors.append(f"Failed to update Postgres for case {case_data['case_id']}")
        
        processed_cases.add(case_id)
    
    # Commit Postgres changes
    try:
        db.commit()
    except Exception as e:
        logger.error(f"Failed to commit Postgres transaction: {e}")
        errors.append(f"Postgres commit failed: {e}")
        db.rollback()
    
    logger.info(f"Commit complete: {neo4j_created} Neo4j relationships, {postgres_updated} Postgres cases")
    
    return CommitResult(
        success=len(errors) == 0,
        neo4j_relationships_created=neo4j_created,
        postgres_cases_updated=postgres_updated,
        errors=errors,
    )
