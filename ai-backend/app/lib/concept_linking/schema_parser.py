"""Schema parser for concept linking - extracts linkable relationships from schema_v3.json.

This module parses the schema to determine:
- Which shared node types support linking (Doctrine, Policy, FactPattern, Law)
- Which source labels can link to each concept type
- The relationship labels to use for each combination

All data is derived dynamically from schema_v3.json, so if the schema changes,
the concept linking feature will automatically adapt.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from functools import lru_cache


# Relationship patterns that indicate a linkable concept
# These are the relationship types we support for retroactive linking
LINKABLE_RELATIONSHIP_PATTERNS = [
    "RELATES_TO_",  # e.g., RELATES_TO_DOCTRINE, RELATES_TO_POLICY
    "RELIES_ON_",   # e.g., RELIES_ON_LAW
]


def _get_schema_path() -> str:
    """Get the path to schema_v3.json."""
    return os.path.join(os.path.dirname(__file__), "..", "..", "..", "schema_v3.json")


@lru_cache(maxsize=1)
def load_schema() -> List[Dict[str, Any]]:
    """Load and cache the schema from schema_v3.json.
    
    Returns:
        List of node definitions from the schema.
    """
    schema_path = _get_schema_path()
    with open(schema_path, "r") as f:
        return json.load(f)


def _is_linkable_relationship(rel_name: str) -> bool:
    """Check if a relationship name matches our linkable patterns."""
    return any(rel_name.startswith(pattern) for pattern in LINKABLE_RELATIONSHIP_PATTERNS)


def _to_snake_case(label: str) -> str:
    """Convert CamelCase to snake_case (e.g., FactPattern -> fact_pattern)."""
    if not label:
        return ""
    # Handle special cases
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", label)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


def get_concept_id_property(concept_label: str) -> str:
    """Get the ID property name for a concept label.
    
    Args:
        concept_label: The concept type (e.g., "Doctrine", "FactPattern")
        
    Returns:
        The ID property name (e.g., "doctrine_id", "fact_pattern_id")
    """
    return f"{_to_snake_case(concept_label)}_id"


def get_target_id_property(target_label: str) -> str:
    """Get the ID property name for a target label.
    
    Args:
        target_label: The target type (e.g., "Argument", "Issue")
        
    Returns:
        The ID property name (e.g., "argument_id", "issue_id")
    """
    return f"{_to_snake_case(target_label)}_id"


def get_linkable_concepts() -> Dict[str, List[str]]:
    """Get all linkable concept types and their valid source labels.
    
    Scans the schema for relationships like RELATES_TO_DOCTRINE, RELIES_ON_LAW, etc.
    and builds a mapping of concept types to the labels that can link to them.
    
    Returns:
        Dict mapping concept label to list of source labels that can link to it.
        Example: {"Doctrine": ["Issue", "Argument"], "Law": ["Ruling"], ...}
    """
    schema = load_schema()
    
    # Build a reverse mapping: concept_label -> list of source labels
    concept_sources: Dict[str, List[str]] = {}
    
    for node_def in schema:
        if not isinstance(node_def, dict):
            continue
            
        source_label = node_def.get("label")
        if not isinstance(source_label, str):
            continue
            
        relationships = node_def.get("relationships", {})
        if not isinstance(relationships, dict):
            continue
            
        for rel_name, rel_def in relationships.items():
            if not _is_linkable_relationship(rel_name):
                continue
                
            if not isinstance(rel_def, dict):
                continue
                
            target_label = rel_def.get("target")
            if not isinstance(target_label, str):
                continue
            
            # Add this source to the concept's list of sources
            if target_label not in concept_sources:
                concept_sources[target_label] = []
            if source_label not in concept_sources[target_label]:
                concept_sources[target_label].append(source_label)
    
    return concept_sources


def get_concept_targets(concept_label: str) -> List[str]:
    """Get the list of source labels that can link to a specific concept type.
    
    Args:
        concept_label: The concept type (e.g., "Doctrine", "Policy", "Law")
        
    Returns:
        List of source labels that can have relationships to this concept.
        Example: For "Doctrine", returns ["Issue", "Argument"]
    """
    linkable = get_linkable_concepts()
    return linkable.get(concept_label, [])


def get_relationship_label(source_label: str, concept_label: str) -> Optional[str]:
    """Get the relationship label for linking a source to a concept.
    
    Args:
        source_label: The source node type (e.g., "Argument", "Issue", "Ruling")
        concept_label: The concept type (e.g., "Doctrine", "Policy", "Law")
        
    Returns:
        The relationship label (e.g., "RELATES_TO_DOCTRINE", "RELIES_ON_LAW")
        or None if no such relationship exists in the schema.
    """
    schema = load_schema()
    
    for node_def in schema:
        if not isinstance(node_def, dict):
            continue
            
        if node_def.get("label") != source_label:
            continue
            
        relationships = node_def.get("relationships", {})
        if not isinstance(relationships, dict):
            continue
            
        for rel_name, rel_def in relationships.items():
            if not _is_linkable_relationship(rel_name):
                continue
                
            if not isinstance(rel_def, dict):
                continue
                
            if rel_def.get("target") == concept_label:
                return rel_name
    
    return None


def get_target_text_properties(target_label: str) -> List[str]:
    """Get the text properties for a target label that should be analyzed by AI.
    
    These are the properties that contain meaningful text for matching against concepts.
    
    Args:
        target_label: The target type (e.g., "Argument", "Issue", "Ruling")
        
    Returns:
        List of property names containing text for analysis.
    """
    schema = load_schema()
    
    text_properties = []
    
    for node_def in schema:
        if not isinstance(node_def, dict):
            continue
            
        if node_def.get("label") != target_label:
            continue
            
        properties = node_def.get("properties", {})
        if not isinstance(properties, dict):
            continue
            
        for prop_name, prop_def in properties.items():
            if not isinstance(prop_def, dict):
                continue
            
            # Skip hidden properties and embeddings
            ui = prop_def.get("ui", {})
            if ui.get("hidden"):
                continue
            if prop_name.endswith("_embedding"):
                continue
            if prop_name.endswith("_id"):
                continue
            if prop_name.endswith("_upload_code"):
                continue
                
            # Include text and textarea inputs
            input_type = ui.get("input")
            prop_type = prop_def.get("type")
            
            if input_type in ("text", "textarea") or prop_type == "STRING":
                text_properties.append(prop_name)
    
    return text_properties


def get_target_analysis_properties(target_label: str) -> List[str]:
    """Get the minimal properties needed for AI analysis of a target node.
    
    Returns only the properties that are semantically meaningful for determining
    whether a node should be linked to a concept. We want the primary text content
    that describes what the node is about, not metadata or disposition info.
    
    Args:
        target_label: The target type (e.g., "Argument", "Issue", "Ruling")
        
    Returns:
        List of property names for AI analysis.
    """
    # Explicit mapping of which properties are relevant for concept matching.
    # These are the properties that contain semantic content for determining
    # if a node relates to a Doctrine, Policy, FactPattern, or Law.
    ANALYSIS_PROPERTIES = {
        "Argument": ["label", "text"],  # Main argument content
        "Issue": ["label", "text"],     # Main issue content  
        "Ruling": ["label", "reasoning"],  # Court's reasoning for Law matching
    }
    
    return ANALYSIS_PROPERTIES.get(target_label, ["label", "text"])


def get_concept_properties(concept_label: str) -> Dict[str, Any]:
    """Get the property definitions for a concept type.
    
    Args:
        concept_label: The concept type (e.g., "Doctrine", "Policy")
        
    Returns:
        Dict of property definitions from the schema.
    """
    schema = load_schema()
    
    for node_def in schema:
        if not isinstance(node_def, dict):
            continue
            
        if node_def.get("label") == concept_label:
            return node_def.get("properties", {})
    
    return {}


def get_schema_info() -> Dict[str, Any]:
    """Get a summary of the schema for the concept linking feature.
    
    Returns:
        Dict containing:
        - linkable_concepts: Dict of concept labels to their target labels
        - concept_properties: Dict of concept labels to their display properties
        - relationships: Dict of (source, concept) tuples to relationship labels
    """
    linkable = get_linkable_concepts()
    
    # Build relationship mapping
    relationships: Dict[Tuple[str, str], str] = {}
    for concept_label, source_labels in linkable.items():
        for source_label in source_labels:
            rel_label = get_relationship_label(source_label, concept_label)
            if rel_label:
                relationships[(source_label, concept_label)] = rel_label
    
    # Get display properties for each concept
    concept_properties: Dict[str, List[str]] = {}
    for concept_label in linkable.keys():
        props = get_concept_properties(concept_label)
        display_props = []
        for prop_name, prop_def in props.items():
            if not isinstance(prop_def, dict):
                continue
            ui = prop_def.get("ui", {})
            if ui.get("hidden"):
                continue
            if prop_name.endswith("_embedding"):
                continue
            display_props.append(prop_name)
        concept_properties[concept_label] = display_props
    
    return {
        "linkable_concepts": linkable,
        "concept_properties": concept_properties,
        "relationships": {f"{k[0]}->{k[1]}": v for k, v in relationships.items()},
    }
