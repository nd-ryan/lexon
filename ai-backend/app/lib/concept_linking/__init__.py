"""Concept linking module for retroactive AI-powered linking of shared nodes to case data."""

from .schema_parser import (
    get_linkable_concepts,
    get_concept_targets,
    get_relationship_label,
    get_concept_id_property,
    get_target_text_properties,
    get_schema_info,
    load_schema,
)
from .analysis_service import (
    MatchResult,
    AnalysisResult,
    analyze_concept_matches,
    list_concepts_by_label,
    fetch_concept_details,
)
from .commit_service import (
    ApprovedMatch,
    CommitResult,
    commit_matches,
)

__all__ = [
    # Schema parser
    "get_linkable_concepts",
    "get_concept_targets",
    "get_relationship_label",
    "get_concept_id_property",
    "get_target_text_properties",
    "get_schema_info",
    "load_schema",
    # Analysis service
    "MatchResult",
    "AnalysisResult",
    "analyze_concept_matches",
    "list_concepts_by_label",
    "fetch_concept_details",
    # Commit service
    "ApprovedMatch",
    "CommitResult",
    "commit_matches",
]
