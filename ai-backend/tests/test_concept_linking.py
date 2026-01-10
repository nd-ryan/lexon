"""Tests for the concept linking feature.

This module tests the schema_parser, analysis_service, commit_service, and API routes
for retroactive concept linking.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import json


# ============================================================================
# Schema Parser Tests
# ============================================================================


class TestSchemaParser:
    """Tests for app/lib/concept_linking/schema_parser.py"""

    def test_get_linkable_concepts_returns_expected_types(self):
        """Schema should identify Doctrine, Policy, FactPattern, Law as linkable."""
        from app.lib.concept_linking.schema_parser import get_linkable_concepts
        
        linkable = get_linkable_concepts()
        
        # These are the expected linkable concept types
        assert "Doctrine" in linkable
        assert "Policy" in linkable
        assert "FactPattern" in linkable
        assert "Law" in linkable

    def test_get_linkable_concepts_maps_to_correct_targets(self):
        """Each concept type should map to correct target labels."""
        from app.lib.concept_linking.schema_parser import get_linkable_concepts
        
        linkable = get_linkable_concepts()
        
        # Doctrine, Policy, FactPattern can link to Issue and Argument
        assert "Issue" in linkable.get("Doctrine", [])
        assert "Argument" in linkable.get("Doctrine", [])
        assert "Issue" in linkable.get("Policy", [])
        assert "Argument" in linkable.get("Policy", [])
        assert "Issue" in linkable.get("FactPattern", [])
        assert "Argument" in linkable.get("FactPattern", [])
        
        # Law can link to Ruling
        assert "Ruling" in linkable.get("Law", [])

    def test_get_concept_targets_returns_targets_for_valid_concept(self):
        """get_concept_targets should return targets for valid concept type."""
        from app.lib.concept_linking.schema_parser import get_concept_targets
        
        targets = get_concept_targets("Doctrine")
        
        assert "Issue" in targets
        assert "Argument" in targets

    def test_get_concept_targets_returns_empty_for_invalid_concept(self):
        """get_concept_targets should return empty list for invalid concept."""
        from app.lib.concept_linking.schema_parser import get_concept_targets
        
        targets = get_concept_targets("InvalidConcept")
        
        assert targets == []

    def test_get_relationship_label_returns_correct_label(self):
        """get_relationship_label should return correct relationship label."""
        from app.lib.concept_linking.schema_parser import get_relationship_label
        
        # Issue -> Doctrine uses RELATES_TO_DOCTRINE
        rel = get_relationship_label("Issue", "Doctrine")
        assert rel == "RELATES_TO_DOCTRINE"
        
        # Argument -> Policy uses RELATES_TO_POLICY
        rel = get_relationship_label("Argument", "Policy")
        assert rel == "RELATES_TO_POLICY"
        
        # Ruling -> Law uses RELIES_ON_LAW
        rel = get_relationship_label("Ruling", "Law")
        assert rel == "RELIES_ON_LAW"

    def test_get_relationship_label_returns_none_for_invalid_pair(self):
        """get_relationship_label should return None for invalid source/concept pair."""
        from app.lib.concept_linking.schema_parser import get_relationship_label
        
        rel = get_relationship_label("Case", "Doctrine")
        assert rel is None

    def test_get_concept_id_property_converts_to_snake_case(self):
        """get_concept_id_property should convert label to snake_case_id."""
        from app.lib.concept_linking.schema_parser import get_concept_id_property
        
        assert get_concept_id_property("Doctrine") == "doctrine_id"
        assert get_concept_id_property("FactPattern") == "fact_pattern_id"
        assert get_concept_id_property("Law") == "law_id"

    def test_get_target_text_properties_returns_text_fields(self):
        """get_target_text_properties should return text fields for analysis."""
        from app.lib.concept_linking.schema_parser import get_target_text_properties
        
        # Argument has text, label, disposition_text
        props = get_target_text_properties("Argument")
        assert "text" in props
        assert "label" in props

    def test_get_schema_info_returns_complete_info(self):
        """get_schema_info should return complete schema information."""
        from app.lib.concept_linking.schema_parser import get_schema_info
        
        info = get_schema_info()
        
        assert "linkable_concepts" in info
        assert "concept_properties" in info
        assert "relationships" in info
        
        # Check relationships are formatted correctly
        assert "Issue->Doctrine" in info["relationships"]
        assert info["relationships"]["Issue->Doctrine"] == "RELATES_TO_DOCTRINE"


# ============================================================================
# Analysis Service Tests
# ============================================================================


class TestAnalysisService:
    """Tests for app/lib/concept_linking/analysis_service.py"""

    def test_get_node_text_preview_extracts_text(self):
        """_get_node_text_preview should extract text from node properties."""
        from app.lib.concept_linking.analysis_service import _get_node_text_preview
        
        props = {"text": "This is a test argument text", "label": "Test Label"}
        preview = _get_node_text_preview(props, "Argument")
        
        assert preview == "This is a test argument text"

    def test_get_node_text_preview_truncates_long_text(self):
        """_get_node_text_preview should truncate text longer than 200 chars."""
        from app.lib.concept_linking.analysis_service import _get_node_text_preview
        
        long_text = "x" * 300
        props = {"text": long_text}
        preview = _get_node_text_preview(props, "Argument")
        
        assert len(preview) == 203  # 200 chars + "..."
        assert preview.endswith("...")

    def test_get_node_text_preview_handles_missing_props(self):
        """_get_node_text_preview should handle missing properties."""
        from app.lib.concept_linking.analysis_service import _get_node_text_preview
        
        props = {}
        preview = _get_node_text_preview(props, "Argument")
        
        assert preview == "(No text available)"

    def test_build_analysis_prompt_includes_concept_info(self):
        """_build_analysis_prompt should include concept information."""
        from app.lib.concept_linking.analysis_service import _build_analysis_prompt
        
        prompt = _build_analysis_prompt(
            concept_label="Doctrine",
            concept_name="Market Power",
            concept_description="The ability to control prices",
            target_label="Argument",
            nodes=[{"node_id": "arg-1", "props": {"text": "test"}}],
        )
        
        assert "Market Power" in prompt
        assert "The ability to control prices" in prompt
        assert "Argument" in prompt

    @patch("app.lib.concept_linking.analysis_service.neo4j_client")
    def test_fetch_concept_details_returns_props(self, mock_neo4j):
        """fetch_concept_details should return concept properties."""
        from app.lib.concept_linking.analysis_service import fetch_concept_details
        
        mock_neo4j.execute_query.return_value = [
            {"props": {"name": "Test Doctrine", "description": "Test description"}}
        ]
        
        props = fetch_concept_details("Doctrine", "doc-123")
        
        assert props is not None
        assert props["name"] == "Test Doctrine"

    @patch("app.lib.concept_linking.analysis_service.neo4j_client")
    def test_fetch_concept_details_returns_none_when_not_found(self, mock_neo4j):
        """fetch_concept_details should return None when concept not found."""
        from app.lib.concept_linking.analysis_service import fetch_concept_details
        
        mock_neo4j.execute_query.return_value = []
        
        props = fetch_concept_details("Doctrine", "nonexistent")
        
        assert props is None

    @patch("app.lib.concept_linking.analysis_service.neo4j_client")
    def test_list_concepts_by_label(self, mock_neo4j):
        """list_concepts_by_label should return formatted concepts."""
        from app.lib.concept_linking.analysis_service import list_concepts_by_label
        
        mock_neo4j.execute_query.return_value = [
            {
                "id": "doc-1",
                "props": {"name": "Doctrine 1", "description": "Desc 1"},
                "connectionCount": 5,
            },
            {
                "id": "doc-2",
                "props": {"name": "Doctrine 2", "description": "Desc 2"},
                "connectionCount": 3,
            },
        ]
        
        concepts = list_concepts_by_label("Doctrine")
        
        assert len(concepts) == 2
        assert concepts[0]["name"] == "Doctrine 1"
        assert concepts[0]["connectionCount"] == 5


# ============================================================================
# Commit Service Tests
# ============================================================================


class TestCommitService:
    """Tests for app/lib/concept_linking/commit_service.py"""

    def test_get_target_id_property_converts_correctly(self):
        """_get_target_id_property should convert label to snake_case_id."""
        from app.lib.concept_linking.commit_service import _get_target_id_property
        
        assert _get_target_id_property("Argument") == "argument_id"
        assert _get_target_id_property("Issue") == "issue_id"
        assert _get_target_id_property("FactPattern") == "fact_pattern_id"

    def test_add_edge_to_extracted_adds_new_edge(self):
        """_add_edge_to_extracted should add a new edge."""
        from app.lib.concept_linking.commit_service import _add_edge_to_extracted
        
        extracted = {"nodes": [], "edges": []}
        updated, added = _add_edge_to_extracted(
            extracted=extracted,
            from_id="arg-1",
            to_id="doc-1",
            relationship_label="RELATES_TO_DOCTRINE",
        )
        
        assert added is True
        assert len(updated["edges"]) == 1
        assert updated["edges"][0]["from"] == "arg-1"
        assert updated["edges"][0]["to"] == "doc-1"
        assert updated["edges"][0]["label"] == "RELATES_TO_DOCTRINE"

    def test_add_edge_to_extracted_skips_duplicate(self):
        """_add_edge_to_extracted should not add duplicate edges."""
        from app.lib.concept_linking.commit_service import _add_edge_to_extracted
        
        extracted = {
            "nodes": [],
            "edges": [
                {"from": "arg-1", "to": "doc-1", "label": "RELATES_TO_DOCTRINE", "properties": {}}
            ],
        }
        updated, added = _add_edge_to_extracted(
            extracted=extracted,
            from_id="arg-1",
            to_id="doc-1",
            relationship_label="RELATES_TO_DOCTRINE",
        )
        
        assert added is False
        assert len(updated["edges"]) == 1

    def test_find_node_temp_id_in_extracted_finds_node(self):
        """_find_node_temp_id_in_extracted should find node by permanent ID."""
        from app.lib.concept_linking.commit_service import _find_node_temp_id_in_extracted
        
        extracted = {
            "nodes": [
                {
                    "temp_id": "temp-arg-1",
                    "label": "Argument",
                    "properties": {"argument_id": "perm-arg-1"},
                }
            ],
            "edges": [],
        }
        
        temp_id = _find_node_temp_id_in_extracted(extracted, "perm-arg-1", "Argument")
        
        assert temp_id == "temp-arg-1"

    def test_find_node_temp_id_in_extracted_returns_none_when_not_found(self):
        """_find_node_temp_id_in_extracted should return None when not found."""
        from app.lib.concept_linking.commit_service import _find_node_temp_id_in_extracted
        
        extracted = {"nodes": [], "edges": []}
        
        temp_id = _find_node_temp_id_in_extracted(extracted, "nonexistent", "Argument")
        
        assert temp_id is None


# ============================================================================
# API Route Tests
# ============================================================================


@pytest.mark.asyncio
class TestConceptLinkingRoutes:
    """Tests for app/routes/concept_linking.py API endpoints.
    
    Note: The async_client fixture provides auth by default, so we don't test
    "requires_auth" scenarios here - those are covered by the shared auth tests.
    """

    async def test_get_schema_returns_linkable_concepts(self, async_client, api_key_header):
        """GET /concept-linking/schema should return linkable concepts."""
        response = await async_client.get(
            "/api/ai/concept-linking/schema",
            headers=api_key_header,
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "linkableConcepts" in data
        assert "Doctrine" in data["linkableConcepts"]

    async def test_list_concepts_rejects_invalid_label(self, async_client, api_key_header):
        """GET /concept-linking/concepts/{label} should reject invalid labels."""
        response = await async_client.get(
            "/api/ai/concept-linking/concepts/InvalidLabel",
            headers=api_key_header,
        )
        
        assert response.status_code == 400

    @patch("app.lib.concept_linking.analysis_service.neo4j_client")
    async def test_list_concepts_returns_concepts(
        self, mock_neo4j, async_client, api_key_header
    ):
        """GET /concept-linking/concepts/{label} should return concepts list."""
        mock_neo4j.execute_query.return_value = [
            {
                "id": "doc-1",
                "props": {"name": "Test Doctrine", "description": "Test desc"},
                "connectionCount": 5,
            }
        ]
        
        response = await async_client.get(
            "/api/ai/concept-linking/concepts/Doctrine",
            headers=api_key_header,
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "concepts" in data

    async def test_analyze_rejects_invalid_label(self, async_client, api_key_header):
        """POST /concept-linking/analyze should reject invalid concept label."""
        response = await async_client.post(
            "/api/ai/concept-linking/analyze",
            headers=api_key_header,
            json={"conceptLabel": "InvalidLabel", "conceptId": "doc-1"},
        )
        
        assert response.status_code == 400

    async def test_commit_rejects_empty_matches(self, async_client, api_key_header):
        """POST /concept-linking/commit should reject empty matches list."""
        response = await async_client.post(
            "/api/ai/concept-linking/commit",
            headers=api_key_header,
            json={
                "conceptLabel": "Doctrine",
                "conceptId": "doc-1",
                "matches": [],
            },
        )
        
        assert response.status_code == 400

    async def test_commit_rejects_invalid_label(self, async_client, api_key_header):
        """POST /concept-linking/commit should reject invalid concept label."""
        response = await async_client.post(
            "/api/ai/concept-linking/commit",
            headers=api_key_header,
            json={
                "conceptLabel": "InvalidLabel",
                "conceptId": "doc-1",
                "matches": [{"nodeId": "arg-1", "nodeLabel": "Argument", "caseId": "case-1"}],
            },
        )
        
        assert response.status_code == 400

    @patch("app.lib.concept_linking.analysis_service.neo4j_client")
    async def test_get_target_counts_returns_counts(
        self, mock_neo4j, async_client, api_key_header
    ):
        """GET /concepts/{label}/{id}/target-counts should return counts."""
        mock_neo4j.execute_query.return_value = [{"count": 42}]
        
        response = await async_client.get(
            "/api/ai/concept-linking/concepts/Doctrine/doc-1/target-counts",
            headers=api_key_header,
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "targetCounts" in data
        assert "totalTargets" in data
