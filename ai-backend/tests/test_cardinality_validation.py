"""Tests for cardinality validation in validate_case_graph."""

import pytest

from app.lib.schema_runtime import _validate_cardinality, validate_case_graph, build_property_models, prune_ui_schema_for_llm


class TestValidateCardinality:
    """Tests for the _validate_cardinality helper function."""

    def test_one_to_one_valid(self):
        """One-to-one: each source has exactly one edge, each target referenced once."""
        edges = [
            {"from": "ruling1", "to": "issue1", "label": "SETS", "properties": {}},
            {"from": "ruling2", "to": "issue2", "label": "SETS", "properties": {}},
        ]
        id_to_label = {"ruling1": "Ruling", "ruling2": "Ruling", "issue1": "Issue", "issue2": "Issue"}
        cardinality = {"Ruling": {"SETS": "one-to-one"}}

        errors = _validate_cardinality(edges, id_to_label, cardinality)
        assert errors == []

    def test_one_to_one_source_violation(self):
        """One-to-one: error if source has multiple edges."""
        edges = [
            {"from": "ruling1", "to": "issue1", "label": "SETS", "properties": {}},
            {"from": "ruling1", "to": "issue2", "label": "SETS", "properties": {}},  # Same source!
        ]
        id_to_label = {"ruling1": "Ruling", "issue1": "Issue", "issue2": "Issue"}
        cardinality = {"Ruling": {"SETS": "one-to-one"}}

        errors = _validate_cardinality(edges, id_to_label, cardinality)
        assert len(errors) == 1
        assert "source 'ruling1' has 2 edges" in errors[0]

    def test_one_to_one_target_violation(self):
        """One-to-one: error if target is referenced by multiple sources."""
        edges = [
            {"from": "ruling1", "to": "issue1", "label": "SETS", "properties": {}},
            {"from": "ruling2", "to": "issue1", "label": "SETS", "properties": {}},  # Same target!
        ]
        id_to_label = {"ruling1": "Ruling", "ruling2": "Ruling", "issue1": "Issue"}
        cardinality = {"Ruling": {"SETS": "one-to-one"}}

        errors = _validate_cardinality(edges, id_to_label, cardinality)
        assert len(errors) == 1
        assert "target 'issue1' is referenced by 2 sources" in errors[0]

    def test_one_to_many_valid(self):
        """One-to-many: source can have many edges, but each target referenced once."""
        edges = [
            {"from": "case1", "to": "proc1", "label": "HAS_PROCEEDING", "properties": {}},
            {"from": "case1", "to": "proc2", "label": "HAS_PROCEEDING", "properties": {}},  # Same source OK
        ]
        id_to_label = {"case1": "Case", "proc1": "Proceeding", "proc2": "Proceeding"}
        cardinality = {"Case": {"HAS_PROCEEDING": "one-to-many"}}

        errors = _validate_cardinality(edges, id_to_label, cardinality)
        assert errors == []

    def test_one_to_many_target_violation(self):
        """One-to-many: error if target is referenced by multiple sources."""
        edges = [
            {"from": "case1", "to": "proc1", "label": "HAS_PROCEEDING", "properties": {}},
            {"from": "case2", "to": "proc1", "label": "HAS_PROCEEDING", "properties": {}},  # Same target!
        ]
        id_to_label = {"case1": "Case", "case2": "Case", "proc1": "Proceeding"}
        cardinality = {"Case": {"HAS_PROCEEDING": "one-to-many"}}

        errors = _validate_cardinality(edges, id_to_label, cardinality)
        assert len(errors) == 1
        assert "target 'proc1' is referenced by 2 sources" in errors[0]

    def test_many_to_one_valid(self):
        """Many-to-one: each source has at most one edge, but targets can be shared."""
        edges = [
            {"from": "forum1", "to": "juris1", "label": "PART_OF", "properties": {}},
            {"from": "forum2", "to": "juris1", "label": "PART_OF", "properties": {}},  # Same target OK
        ]
        id_to_label = {"forum1": "Forum", "forum2": "Forum", "juris1": "Jurisdiction"}
        cardinality = {"Forum": {"PART_OF": "many-to-one"}}

        errors = _validate_cardinality(edges, id_to_label, cardinality)
        assert errors == []

    def test_many_to_one_source_violation(self):
        """Many-to-one: error if source has multiple edges."""
        edges = [
            {"from": "forum1", "to": "juris1", "label": "PART_OF", "properties": {}},
            {"from": "forum1", "to": "juris2", "label": "PART_OF", "properties": {}},  # Same source!
        ]
        id_to_label = {"forum1": "Forum", "juris1": "Jurisdiction", "juris2": "Jurisdiction"}
        cardinality = {"Forum": {"PART_OF": "many-to-one"}}

        errors = _validate_cardinality(edges, id_to_label, cardinality)
        assert len(errors) == 1
        assert "source 'forum1' has 2 edges" in errors[0]

    def test_many_to_many_no_restrictions(self):
        """Many-to-many: no restrictions on edges."""
        edges = [
            {"from": "issue1", "to": "doctrine1", "label": "RELATES_TO_DOCTRINE", "properties": {}},
            {"from": "issue1", "to": "doctrine2", "label": "RELATES_TO_DOCTRINE", "properties": {}},
            {"from": "issue2", "to": "doctrine1", "label": "RELATES_TO_DOCTRINE", "properties": {}},
        ]
        id_to_label = {"issue1": "Issue", "issue2": "Issue", "doctrine1": "Doctrine", "doctrine2": "Doctrine"}
        cardinality = {"Issue": {"RELATES_TO_DOCTRINE": "many-to-many"}}

        errors = _validate_cardinality(edges, id_to_label, cardinality)
        assert errors == []

    def test_unknown_cardinality_defaults_to_many_to_many(self):
        """Unknown relationship defaults to many-to-many (no validation)."""
        edges = [
            {"from": "a", "to": "b", "label": "UNKNOWN", "properties": {}},
            {"from": "a", "to": "c", "label": "UNKNOWN", "properties": {}},
        ]
        id_to_label = {"a": "SomeLabel"}
        cardinality = {}  # No cardinality defined

        errors = _validate_cardinality(edges, id_to_label, cardinality)
        assert errors == []


class TestValidateCaseGraphWithCardinality:
    """Integration tests for validate_case_graph with cardinality validation."""

    def test_ruling_sets_issue_one_to_one_enforced(self):
        """Verify Ruling-SETS-Issue one-to-one is enforced from actual schema."""
        # Load schema to get actual cardinality settings
        from app.lib.schema_runtime import load_schema_payload

        schema_payload = load_schema_payload()
        spec = prune_ui_schema_for_llm(schema_payload)
        models_by_label, rels_by_label, props_meta_by_label, label_flags_by_label, rel_cardinality_by_label = build_property_models(spec)

        # Verify the SETS cardinality is one-to-one in the schema
        assert rel_cardinality_by_label.get("Ruling", {}).get("SETS") == "one-to-one"

        # Create payload with violation: one ruling sets two issues
        payload = {
            "case_name": "Test Case",
            "nodes": [
                {"temp_id": "n1", "label": "Ruling", "properties": {
                    "label": "Test ruling",
                    "type": "appeal",
                    "reasoning": "Some reasoning",
                    "ratio": "Some ratio",
                    "summary": "Some summary",
                }},
                {"temp_id": "n2", "label": "Issue", "properties": {
                    "label": "Issue 1",
                    "text": "Issue text 1",
                    "type": "substantive",
                }},
                {"temp_id": "n3", "label": "Issue", "properties": {
                    "label": "Issue 2",
                    "text": "Issue text 2",
                    "type": "procedural",
                }},
            ],
            "edges": [
                {"from": "n1", "to": "n2", "label": "SETS", "properties": {"in_favor": "plaintiff"}},
                {"from": "n1", "to": "n3", "label": "SETS", "properties": {"in_favor": "defendant"}},  # Violation!
            ],
        }

        cleaned, errors = validate_case_graph(
            payload,
            models_by_label,
            rels_by_label,
            props_meta_by_label,
            label_flags_by_label=label_flags_by_label,
            relationship_cardinality_by_label=rel_cardinality_by_label,
        )

        # Should have a cardinality violation error
        assert any("Cardinality violation" in e for e in errors)
        assert any("source 'n1' has 2 edges" in e for e in errors)

    def test_case_has_proceeding_one_to_many_allows_multiple(self):
        """Verify Case-HAS_PROCEEDING-Proceeding allows multiple proceedings per case."""
        from app.lib.schema_runtime import load_schema_payload

        schema_payload = load_schema_payload()
        spec = prune_ui_schema_for_llm(schema_payload)
        models_by_label, rels_by_label, props_meta_by_label, label_flags_by_label, rel_cardinality_by_label = build_property_models(spec)

        # Verify the HAS_PROCEEDING cardinality is one-to-many in the schema
        assert rel_cardinality_by_label.get("Case", {}).get("HAS_PROCEEDING") == "one-to-many"

        # Create payload with one case having multiple proceedings (valid)
        payload = {
            "case_name": "Test Case",
            "nodes": [
                {"temp_id": "n1", "label": "Case", "properties": {
                    "name": "Test Case",
                    "citation": "123 F.3d 456",
                    "type": "civil",
                    "summary": "Summary",
                    "status": "final",
                    "outcome": "Plaintiff wins",
                    "court_level": "circuit",
                }},
                {"temp_id": "n2", "label": "Proceeding", "properties": {
                    "stage": "district court",
                    "decided_date": "2024-01-01",
                }},
                {"temp_id": "n3", "label": "Proceeding", "properties": {
                    "stage": "appeal court",
                    "decided_date": "2024-06-01",
                }},
            ],
            "edges": [
                {"from": "n1", "to": "n2", "label": "HAS_PROCEEDING", "properties": {}},
                {"from": "n1", "to": "n3", "label": "HAS_PROCEEDING", "properties": {}},  # Valid - one-to-many
            ],
        }

        cleaned, errors = validate_case_graph(
            payload,
            models_by_label,
            rels_by_label,
            props_meta_by_label,
            label_flags_by_label=label_flags_by_label,
            relationship_cardinality_by_label=rel_cardinality_by_label,
        )

        # Should NOT have cardinality violation errors
        cardinality_errors = [e for e in errors if "Cardinality violation" in e]
        assert cardinality_errors == []

