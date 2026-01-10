"""AI-powered analysis service for concept linking.

This service uses OpenAI to analyze existing case data (Arguments, Issues, Rulings)
and determine which should be linked to a specific shared concept (Doctrine, Policy,
FactPattern, Law).

Completely separate from case extraction - uses OpenAI directly, not CrewAI.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.lib.neo4j_client import neo4j_client
from app.lib.openai_client import get_openai_client, get_responses_model
from app.lib.logging_config import setup_logger

from .schema_parser import (
    get_concept_targets,
    get_relationship_label,
    get_concept_id_property,
    get_target_text_properties,
    get_target_analysis_properties,
    get_target_id_property,
)


logger = setup_logger("concept-linking-analysis")


@dataclass
class MatchResult:
    """Result of AI analysis for a single node match."""
    node_id: str
    node_label: str
    case_id: str
    case_name: str
    node_text_preview: str  # First ~200 chars of the node's text


@dataclass
class AnalysisResult:
    """Complete result of concept analysis."""
    concept_label: str
    concept_id: str
    concept_name: str
    total_analyzed: int
    matches: List[MatchResult]


def _fetch_target_nodes_without_relationship(
    concept_label: str,
    concept_id: str,
    target_label: str,
    relationship_label: str,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    """Fetch target nodes from Neo4j that don't already have the relationship.
    
    Only fetches the properties needed for AI analysis (excludes embeddings, IDs, etc.).
    
    Args:
        concept_label: The concept type (e.g., "Doctrine")
        concept_id: The specific concept's ID
        target_label: The target node type (e.g., "Argument")
        relationship_label: The relationship to check (e.g., "RELATES_TO_DOCTRINE")
        limit: Maximum nodes to fetch
        
    Returns:
        List of nodes with their analysis properties and case info.
    """
    concept_id_prop = get_concept_id_property(concept_label)
    target_id_prop = get_target_id_property(target_label)
    
    # Get only the properties needed for AI analysis (schema-driven)
    analysis_props = get_target_analysis_properties(target_label)
    
    # Build property selection: only fetch what we need for AI analysis
    # Always include the ID for tracking, plus schema-defined analysis properties
    prop_selections = [f"n.{target_id_prop} as node_id"]
    for prop in analysis_props:
        prop_selections.append(f"n.{prop} as {prop}")
    prop_return_clause = ", ".join(prop_selections)
    
    # Query nodes that DON'T already have this specific relationship
    # Also get the case info by traversing back through the graph
    query = f"""
        MATCH (n:{target_label})
        WHERE NOT EXISTS {{
            MATCH (n)-[:{relationship_label}]->(c:{concept_label} {{{concept_id_prop}: $concept_id}})
        }}
        // Get case info - traverse to find the Case node
        OPTIONAL MATCH path = (n)<-[*1..4]-(case:Case)
        WITH n, case, length(path) as pathLength
        ORDER BY pathLength ASC
        WITH n, collect(case)[0] as nearestCase
        RETURN 
            {prop_return_clause},
            nearestCase.case_id as case_id,
            nearestCase.name as case_name
        LIMIT $limit
    """
    
    logger.debug(f"Fetching {target_label} with properties: {analysis_props}")
    
    try:
        results = neo4j_client.execute_query(query, {
            "concept_id": concept_id,
            "limit": limit,
        })
        
        # Restructure results to have a 'props' dict for consistency with downstream code
        processed_results = []
        for record in results:
            props = {}
            for prop in analysis_props:
                if prop in record and record[prop] is not None:
                    props[prop] = record[prop]
            
            processed_results.append({
                "node_id": record.get("node_id"),
                "props": props,
                "case_id": record.get("case_id"),
                "case_name": record.get("case_name"),
            })
        
        return processed_results
    except Exception as e:
        logger.error(f"Failed to fetch {target_label} nodes: {e}")
        return []


def _get_node_text_preview(props: Dict[str, Any], target_label: str) -> str:
    """Extract a text preview from node properties for display."""
    text_props = get_target_text_properties(target_label)
    
    # Priority order for preview text
    priority_props = ["text", "label", "reasoning", "description", "summary", "name"]
    
    for prop in priority_props:
        if prop in props and props[prop]:
            text = str(props[prop])
            if len(text) > 200:
                return text[:200] + "..."
            return text
    
    # Fall back to any text property
    for prop in text_props:
        if prop in props and props[prop]:
            text = str(props[prop])
            if len(text) > 200:
                return text[:200] + "..."
            return text
    
    return "(No text available)"


def _build_analysis_prompt(
    concept_label: str,
    concept_name: str,
    concept_description: str,
    target_label: str,
    nodes: List[Dict[str, Any]],
) -> str:
    """Build the prompt for OpenAI analysis.
    
    Note: nodes already contain only analysis-relevant properties (no embeddings, IDs, etc.)
    as they're pre-filtered by _fetch_target_nodes_without_relationship.
    """
    
    # Build nodes JSON for the prompt - props are already filtered
    nodes_for_prompt = []
    for node in nodes:
        props = node.get("props", {})
        nodes_for_prompt.append({
            "node_id": node.get("node_id"),
            "properties": props,
        })
    
    prompt = f"""Analyze which {target_label} nodes relate to this {concept_label}:

CONCEPT: {concept_name}
{concept_description}

NODES:
{json.dumps(nodes_for_prompt, indent=2)}

Return JSON with "results" array. Each result has "node_id" (string) and "relates" (boolean).
Only set relates=true if there is a clear semantic connection to the concept.

Example: {{"results": [{{"node_id": "abc", "relates": true}}, {{"node_id": "xyz", "relates": false}}]}}
"""
    
    return prompt


def _analyze_batch_with_openai(
    concept_label: str,
    concept_name: str,
    concept_description: str,
    target_label: str,
    nodes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Use OpenAI to analyze a batch of nodes.
    
    Returns:
        List of analysis results from OpenAI.
    """
    if not nodes:
        return []
    
    prompt = _build_analysis_prompt(
        concept_label=concept_label,
        concept_name=concept_name,
        concept_description=concept_description,
        target_label=target_label,
        nodes=nodes,
    )
    
    try:
        client = get_openai_client()
        model = get_responses_model()
        
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a legal analysis assistant that determines relationships between legal concepts and case data. You return only valid JSON.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.1,  # Low temperature for consistent analysis
            response_format={"type": "json_object"},
        )
        
        content = response.choices[0].message.content
        if not content:
            logger.warning("OpenAI returned empty response")
            return []
        
        result = json.loads(content)
        return result.get("results", [])
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse OpenAI response as JSON: {e}")
        return []
    except Exception as e:
        logger.error(f"OpenAI analysis failed: {e}")
        return []


def fetch_concept_details(concept_label: str, concept_id: str) -> Optional[Dict[str, Any]]:
    """Fetch the concept node details from Neo4j.
    
    Args:
        concept_label: The concept type (e.g., "Doctrine")
        concept_id: The concept's ID
        
    Returns:
        Dict with concept properties, or None if not found.
    """
    concept_id_prop = get_concept_id_property(concept_label)
    
    query = f"""
        MATCH (c:{concept_label} {{{concept_id_prop}: $concept_id}})
        RETURN properties(c) as props
    """
    
    try:
        results = neo4j_client.execute_query(query, {"concept_id": concept_id})
        if results and len(results) > 0:
            return results[0].get("props", {})
        return None
    except Exception as e:
        logger.error(f"Failed to fetch concept {concept_label}:{concept_id}: {e}")
        return None


def analyze_concept_matches(
    concept_label: str,
    concept_id: str,
    batch_size: int = 100,
    max_nodes: int = 1000,
    progress_callback: Optional[callable] = None,
) -> AnalysisResult:
    """Analyze all target nodes and determine which should link to the concept.
    
    This is the main entry point for concept analysis.
    
    Args:
        concept_label: The concept type (e.g., "Doctrine", "Policy", "Law")
        concept_id: The specific concept's ID
        batch_size: Number of nodes to analyze per OpenAI call
        max_nodes: Maximum total nodes to analyze
        progress_callback: Optional callback(analyzed_count, total_count) for progress
        
    Returns:
        AnalysisResult with all suggested matches.
    """
    logger.info(f"Starting concept analysis for {concept_label}:{concept_id}")
    
    # Fetch concept details
    concept_props = fetch_concept_details(concept_label, concept_id)
    if not concept_props:
        raise ValueError(f"Concept not found: {concept_label}:{concept_id}")
    
    concept_name = concept_props.get("name", "")
    concept_description = concept_props.get("description", concept_props.get("text", ""))
    
    # Get target labels for this concept type
    target_labels = get_concept_targets(concept_label)
    if not target_labels:
        logger.warning(f"No target labels found for concept type: {concept_label}")
        return AnalysisResult(
            concept_label=concept_label,
            concept_id=concept_id,
            concept_name=concept_name,
            total_analyzed=0,
            matches=[],
        )
    
    logger.info(f"Will analyze targets: {target_labels}")
    
    all_matches: List[MatchResult] = []
    total_analyzed = 0
    
    for target_label in target_labels:
        relationship_label = get_relationship_label(target_label, concept_label)
        if not relationship_label:
            logger.warning(f"No relationship label found for {target_label} -> {concept_label}")
            continue
        
        logger.info(f"Fetching {target_label} nodes without {relationship_label}")
        
        # Fetch nodes that don't have this relationship
        nodes = _fetch_target_nodes_without_relationship(
            concept_label=concept_label,
            concept_id=concept_id,
            target_label=target_label,
            relationship_label=relationship_label,
            limit=max_nodes,
        )
        
        logger.info(f"Found {len(nodes)} {target_label} nodes to analyze")
        
        # Process in batches
        for i in range(0, len(nodes), batch_size):
            batch = nodes[i:i + batch_size]
            
            logger.info(f"Analyzing batch {i // batch_size + 1} ({len(batch)} nodes)")
            
            # Call OpenAI for analysis
            batch_results = _analyze_batch_with_openai(
                concept_label=concept_label,
                concept_name=concept_name,
                concept_description=concept_description,
                target_label=target_label,
                nodes=batch,
            )
            
            # Process results - only keep matches
            for result in batch_results:
                if not result.get("relates"):
                    continue
                
                node_id = result.get("node_id")
                if not node_id:
                    continue
                
                # Find the original node data
                node_data = next((n for n in batch if n.get("node_id") == node_id), None)
                if not node_data:
                    continue
                
                match = MatchResult(
                    node_id=node_id,
                    node_label=target_label,
                    case_id=node_data.get("case_id") or "",
                    case_name=node_data.get("case_name") or "(Unknown case)",
                    node_text_preview=_get_node_text_preview(
                        node_data.get("props", {}), 
                        target_label
                    ),
                )
                all_matches.append(match)
            
            total_analyzed += len(batch)
            
            if progress_callback:
                try:
                    progress_callback(total_analyzed, len(nodes))
                except Exception:
                    pass
    
    logger.info(f"Analysis complete: {total_analyzed} nodes analyzed, {len(all_matches)} matches found")
    
    return AnalysisResult(
        concept_label=concept_label,
        concept_id=concept_id,
        concept_name=concept_name,
        total_analyzed=total_analyzed,
        matches=all_matches,
    )


def list_concepts_by_label(concept_label: str, limit: int = 100) -> List[Dict[str, Any]]:
    """List all concepts of a given type from Neo4j.
    
    Args:
        concept_label: The concept type (e.g., "Doctrine")
        limit: Maximum concepts to return
        
    Returns:
        List of concept nodes with their properties.
    """
    concept_id_prop = get_concept_id_property(concept_label)
    
    query = f"""
        MATCH (c:{concept_label})
        OPTIONAL MATCH (c)<-[r]-()
        WITH c, count(r) as connectionCount
        RETURN 
            c.{concept_id_prop} as id,
            properties(c) as props,
            connectionCount
        ORDER BY c.name
        LIMIT $limit
    """
    
    try:
        results = neo4j_client.execute_query(query, {"limit": limit})
        concepts = []
        for r in results:
            props = r.get("props", {})
            # Filter out embeddings
            filtered_props = {
                k: v for k, v in props.items()
                if not k.endswith("_embedding") and not k.endswith("_upload_code")
            }
            concepts.append({
                "id": r.get("id"),
                "name": filtered_props.get("name", ""),
                "description": filtered_props.get("description", filtered_props.get("text", "")),
                "connectionCount": r.get("connectionCount", 0),
                "properties": filtered_props,
            })
        return concepts
    except Exception as e:
        logger.error(f"Failed to list {concept_label} concepts: {e}")
        return []
