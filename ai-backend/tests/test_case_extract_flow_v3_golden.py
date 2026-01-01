import json
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

from tests._case_extract_test_utils import FakeCrewResult, FakePydantic
from tests.test_case_extract_flow_v3_phases import FakeIssueListPydantic  # reuse minimal stand-in


def _load_min_schema() -> list[dict]:
    here = Path(__file__).parent
    payload = json.loads((here / "fixtures" / "case_extract_schema_min.json").read_text())
    assert isinstance(payload, list)
    return payload


def _patch_schema(monkeypatch: pytest.MonkeyPatch, schema_payload: list[dict]) -> None:
    monkeypatch.setattr(
        "app.flow_cases.case_extract_flow_v3.fetch_schema_v3",
        lambda: {"ok": True, "schema": schema_payload},
    )


def _patch_crew_kickoff_sequence(monkeypatch: pytest.MonkeyPatch, results: List[Any]) -> None:
    it: Iterator[Any] = iter(results)

    def fake_kickoff(self):  # noqa: ANN001
        try:
            return next(it)
        except StopIteration as e:  # pragma: no cover
            raise AssertionError("Crew.kickoff called more times than test provided results") from e

    monkeypatch.setattr("app.flow_cases.case_extract_flow_v3.Crew.kickoff", fake_kickoff, raising=False)


def _mk_flow(file_path: str, filename: str, case_id: str):
    from app.flow_cases.case_extract_flow_v3 import CaseExtractFlow

    flow = CaseExtractFlow()
    flow.state.file_path = file_path
    flow.state.filename = filename
    flow.state.case_id = case_id
    return flow


def test_case_extract_flow_golden_shape_phases_0_to_3_then_validate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Golden-ish test: exercise the real orchestration (phases 0-3) with deterministic stubs.

    This intentionally asserts stable SHAPE and validation success, not exact text.
    """
    schema_payload = _load_min_schema()
    _patch_schema(monkeypatch, schema_payload)

    doc_text = (
        "In Smith v. Jones, Alice sued Bob.\n"
        "The court considered breach of contract.\n"
        "The case was heard in the Supreme Court.\n"
    )
    p = tmp_path / "case.txt"
    p.write_text(doc_text)

    # Crew kickoff sequence consumed across phases:
    # - phase1: Case, Proceeding, IssueList
    # - phase2: Forum selection
    # - phase3: Parties + roles
    case_props = {"case_id": "c1", "name": "Smith v. Jones", "citation": "123 F.3d 456"}
    proceeding_props = {"proceeding_id": "p1", "stage": "trial"}
    issue_items = [FakePydantic({"issue_id": "i1", "name": "Breach"})]
    # Use UUID-like IDs so validate_case_graph recognizes these as catalog IDs.
    forum_id = "123e4567-e89b-12d3-a456-426614174000"
    selection = {"selected": {"Forum": [0]}}  # Index 0 maps to forum_id
    parties_roles = {
        "parties": [{"name": "Alice"}, {"name": "Bob"}],
        "case_roles": [{"party_index": 0, "role": "plaintiff"}, {"party_index": 1, "role": "defendant"}],
    }

    _patch_crew_kickoff_sequence(
        monkeypatch,
        [
            FakeCrewResult(pydantic=FakePydantic(case_props)),
            FakeCrewResult(pydantic=FakePydantic(proceeding_props)),
            FakeCrewResult(pydantic=FakeIssueListPydantic(issue_items)),
            FakeCrewResult(pydantic=FakePydantic(selection)),
            FakeCrewResult(raw=json.dumps(parties_roles), text=json.dumps(parties_roles)),
        ],
    )

    def fake_execute_query(query: str, parameters: Dict[str, Any] | None = None):
        # Used in phase2 jurisdiction lookup
        if "MATCH (f:Forum" in query and "Jurisdiction" in query:
            return [{"props": {"jurisdiction_id": "123e4567-e89b-12d3-a456-426614174001", "name": "NY"}}]
        # Used in phase3 fuzzy party lookup (match Alice only)
        if "MATCH (p:Party)" in query:
            q = (parameters or {}).get("q")
            if q and str(q).lower().startswith("alice"):
                return [{"props": {"party_id": "party-1", "name": "Alice"}}]
            return []
        return []

    monkeypatch.setattr("app.flow_cases.case_extract_flow_v3.neo4j_client.execute_query", fake_execute_query)

    flow = _mk_flow(str(p), p.name, "case-123")
    ctx = flow.phase0_kickoff()
    flow.phase0_prepare_schema(ctx)

    # Phase 1–3
    flow.phase1_extract_foundation({})
    flow.state.existing_catalog_by_label = {"Forum": [{"forum_id": forum_id, "name": "Supreme Court"}]}
    flow.phase2_assign_forum_jurisdiction({})
    flow.phase3_extract_parties({})

    nodes = flow.state.nodes_accumulated or []
    edges = flow.state.edges_accumulated or []

    labels = {n.get("label") for n in nodes if isinstance(n, dict)}
    assert {"Case", "Proceeding", "Issue", "Forum", "Party"}.issubset(labels)

    edge_labels = {e.get("label") for e in edges if isinstance(e, dict)}
    assert {"HAS_PROCEEDING", "ADDRESSES", "IN_FORUM", "INVOLVES"}.issubset(edge_labels)

    # Validate using real validator against real models built in phase0
    from app.lib.schema_runtime import validate_case_graph

    payload = {
        "case_name": flow.state.filename,
        "nodes": nodes,
        "edges": edges,
    }
    cleaned, errors = validate_case_graph(
        payload,
        flow.state.models_by_label or {},
        flow.state.rels_by_label or {},
        flow.state.props_meta_by_label or {},
        label_flags_by_label=flow.state.label_flags_by_label or {},
        existing_catalog_by_label=flow.state.existing_catalog_by_label or {},
        relationship_cardinality_by_label=flow.state.rel_cardinality_by_label or {},
    )
    assert errors == []
    assert isinstance(cleaned, dict)
    assert isinstance(cleaned.get("nodes"), list)
    assert isinstance(cleaned.get("edges"), list)


