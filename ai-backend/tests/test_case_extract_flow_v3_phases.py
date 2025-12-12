import json
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

from tests._case_extract_test_utils import FakeCrewResult, FakePydantic


class FakeIssueListPydantic:
    def __init__(self, items: List[FakePydantic]):
        self.items = items


def _load_min_schema() -> list[dict]:
    here = Path(__file__).parent
    payload = json.loads((here / "fixtures" / "case_extract_schema_min.json").read_text())
    assert isinstance(payload, list)
    return payload


def _mk_flow(file_path: str, filename: str, case_id: str):
    from app.flow_cases.case_extract_flow_v3 import CaseExtractFlow

    flow = CaseExtractFlow()
    flow.state.file_path = file_path
    flow.state.filename = filename
    flow.state.case_id = case_id
    return flow


def _patch_schema(monkeypatch: pytest.MonkeyPatch, schema_payload: list[dict]) -> None:
    # case_extract_flow_v3 imports fetch_schema_v3 into module scope; patch there.
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


def _nodes_by_label(nodes: list[dict], label: str) -> list[dict]:
    return [n for n in nodes if isinstance(n, dict) and n.get("label") == label]


def _edges_matching(edges: list[dict], label: str) -> list[dict]:
    return [e for e in edges if isinstance(e, dict) and e.get("label") == label]


def test_phase0_prepare_schema_sets_state_and_reads_doc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    schema_payload = _load_min_schema()
    _patch_schema(monkeypatch, schema_payload)

    doc_text = "Tiny synthetic case doc.\nPlaintiff: Alice.\nDefendant: Bob.\nIssue: breach.\n"
    p = tmp_path / "case.txt"
    p.write_text(doc_text)

    flow = _mk_flow(str(p), p.name, "case-123")
    ctx = flow.phase0_kickoff()
    out = flow.phase0_prepare_schema(ctx)
    assert out == ctx

    assert isinstance(flow.state.schema_spec, dict)
    assert isinstance(flow.state.schema_spec.get("labels"), list)
    assert (flow.state.document_text or "") == doc_text
    assert isinstance(flow.state.models_by_label, dict)
    assert isinstance(flow.state.rels_by_label, dict)
    assert isinstance(flow.state.props_meta_by_label, dict)
    assert isinstance(flow.state.label_flags_by_label, dict)
    assert flow.state.nodes_accumulated == []
    assert flow.state.edges_accumulated == []


def test_phase1_extract_foundation_adds_case_proceeding_issues_and_edges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    schema_payload = _load_min_schema()
    _patch_schema(monkeypatch, schema_payload)

    p = tmp_path / "case.txt"
    p.write_text("Doc")

    flow = _mk_flow(str(p), p.name, "case-123")
    ctx = flow.phase0_kickoff()
    flow.phase0_prepare_schema(ctx)

    # Provide sequential kickoff results: Case, Proceeding, IssueList
    case_props = {"case_id": "c1", "name": "Smith v. Jones", "citation": "123 F.3d 456"}
    proceeding_props = {"proceeding_id": "p1", "stage": "trial"}
    issue_items = [FakePydantic({"issue_id": "i1", "name": "Breach"}), FakePydantic({"issue_id": "i2", "name": "Damages"})]

    _patch_crew_kickoff_sequence(
        monkeypatch,
        [
            FakeCrewResult(pydantic=FakePydantic(case_props)),
            FakeCrewResult(pydantic=FakePydantic(proceeding_props)),
            FakeCrewResult(pydantic=FakeIssueListPydantic(issue_items)),
        ],
    )

    flow.phase1_extract_foundation({})

    nodes = flow.state.nodes_accumulated or []
    edges = flow.state.edges_accumulated or []

    assert len(_nodes_by_label(nodes, "Case")) == 1
    assert len(_nodes_by_label(nodes, "Proceeding")) == 1
    assert len(_nodes_by_label(nodes, "Issue")) == 2

    # Relationship labels come from schema_runtime.get_relationship_label_for_edge
    assert len(_edges_matching(edges, "HAS_PROCEEDING")) == 1
    assert len(_edges_matching(edges, "ADDRESSES")) == 2


def test_phase1_raises_if_case_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    schema_payload = _load_min_schema()
    _patch_schema(monkeypatch, schema_payload)

    p = tmp_path / "case.txt"
    p.write_text("Doc")

    flow = _mk_flow(str(p), p.name, "case-123")
    ctx = flow.phase0_kickoff()
    flow.phase0_prepare_schema(ctx)

    # Case extraction fails; Proceeding/Issue could still return, but flow should fail fast.
    _patch_crew_kickoff_sequence(
        monkeypatch,
        [
            FakeCrewResult(pydantic=FakePydantic({})),  # missing required fields; flow will treat as properties but still adds a node
        ],
    )

    # Force Case task to raise so no node is produced.
    def boom(_self):  # noqa: ANN001
        raise RuntimeError("boom")

    monkeypatch.setattr("app.flow_cases.case_extract_flow_v3.Crew.kickoff", boom, raising=False)

    with pytest.raises(RuntimeError, match="Case extraction produced no Case node"):
        flow.phase1_extract_foundation({})


def test_phase2_assign_forum_creates_forum_node_and_edges_using_catalog_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    schema_payload = _load_min_schema()
    _patch_schema(monkeypatch, schema_payload)

    p = tmp_path / "case.txt"
    p.write_text("Doc")
    flow = _mk_flow(str(p), p.name, "case-123")
    ctx = flow.phase0_kickoff()
    flow.phase0_prepare_schema(ctx)

    # Seed minimal nodes so phase2 can find Proceeding temp_id.
    flow.state.nodes_accumulated = [
        {"temp_id": "n1", "label": "Case", "properties": {"case_id": "c1", "name": "X"}},
        {"temp_id": "n2", "label": "Proceeding", "properties": {"proceeding_id": "p1", "stage": "trial"}},
    ]
    flow.state.edges_accumulated = []

    forum_id = "forum-1"

    # Mock selection result for phase2.
    selection = {"selected": {"Forum": [forum_id]}}
    _patch_crew_kickoff_sequence(monkeypatch, [FakeCrewResult(pydantic=FakePydantic(selection))])

    def fake_execute_query(query: str, parameters: Dict[str, Any] | None = None):
        # phase0 catalog load doesn't happen here; phase2 does jurisdiction lookup by forum name
        if "MATCH (f:Forum" in query and "Jurisdiction" in query:
            return [{"props": {"jurisdiction_id": "jur-1", "name": "NY"}}]
        return []

    monkeypatch.setattr("app.flow_cases.case_extract_flow_v3.neo4j_client.execute_query", fake_execute_query)

    # Provide a Forum catalog entry directly (avoids needing phase0 preload logic).
    flow.state.existing_catalog_by_label = {"Forum": [{"forum_id": forum_id, "name": "Supreme Court"}]}

    out = flow.phase2_assign_forum_jurisdiction({})
    assert out["status"] == "phase2_done"

    nodes = flow.state.nodes_accumulated or []
    edges = flow.state.edges_accumulated or []

    assert len(_nodes_by_label(nodes, "Forum")) == 1
    # Proceeding -> Forum edge uses Neo4j ID string for `to`
    pf_edges = _edges_matching(edges, "IN_FORUM")
    assert len(pf_edges) == 1
    assert pf_edges[0]["from"] == "n2"
    assert pf_edges[0]["to"] == forum_id

    fj_edges = _edges_matching(edges, "PART_OF")
    assert len(fj_edges) == 1
    assert fj_edges[0]["from"] == forum_id
    assert fj_edges[0]["to"] == "jur-1"


def test_phase2_skips_when_selected_forum_not_in_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    schema_payload = _load_min_schema()
    _patch_schema(monkeypatch, schema_payload)

    p = tmp_path / "case.txt"
    p.write_text("Doc")
    flow = _mk_flow(str(p), p.name, "case-123")
    ctx = flow.phase0_kickoff()
    flow.phase0_prepare_schema(ctx)

    flow.state.nodes_accumulated = [
        {"temp_id": "n1", "label": "Case", "properties": {"case_id": "c1", "name": "X"}},
        {"temp_id": "n2", "label": "Proceeding", "properties": {"proceeding_id": "p1", "stage": "trial"}},
    ]
    flow.state.edges_accumulated = []

    forum_id = "forum-missing"
    selection = {"selected": {"Forum": [forum_id]}}
    _patch_crew_kickoff_sequence(monkeypatch, [FakeCrewResult(pydantic=FakePydantic(selection))])

    flow.state.existing_catalog_by_label = {"Forum": [{"forum_id": "other", "name": "Other Court"}]}

    out = flow.phase2_assign_forum_jurisdiction({})
    assert out["status"] == "phase2_done"

    assert len(_nodes_by_label(flow.state.nodes_accumulated or [], "Forum")) == 0
    assert len(_edges_matching(flow.state.edges_accumulated or [], "IN_FORUM")) == 0


def test_phase3_extract_parties_dedup_and_roles_edges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    schema_payload = _load_min_schema()
    _patch_schema(monkeypatch, schema_payload)

    p = tmp_path / "case.txt"
    p.write_text("Doc")
    flow = _mk_flow(str(p), p.name, "case-123")
    ctx = flow.phase0_kickoff()
    flow.phase0_prepare_schema(ctx)

    flow.state.nodes_accumulated = [
        {"temp_id": "n2", "label": "Proceeding", "properties": {"proceeding_id": "p1", "stage": "trial"}},
    ]
    flow.state.edges_accumulated = []

    # Crew returns two parties; one matches existing party in DB via fuzzy lookup.
    parties_roles = {
        "parties": [{"name": "Alice"}, {"name": "Bob"}],
        "case_roles": [{"party_index": 0, "role": "plaintiff"}, {"party_index": 1, "role": "defendant"}],
    }
    _patch_crew_kickoff_sequence(monkeypatch, [FakeCrewResult(raw=json.dumps(parties_roles), text=json.dumps(parties_roles))])

    def fake_execute_query(query: str, parameters: Dict[str, Any] | None = None):
        # phase3 fuzzy lookup query includes MATCH (p:Party)
        if "MATCH (p:Party)" in query:
            q = (parameters or {}).get("q")
            if q and str(q).lower().startswith("alice"):
                return [{"props": {"party_id": "party-1", "name": "Alice"}}]
            return []
        return []

    monkeypatch.setattr("app.flow_cases.case_extract_flow_v3.neo4j_client.execute_query", fake_execute_query)

    out = flow.phase3_extract_parties({})
    assert out["status"] == "phase3_done"

    nodes = flow.state.nodes_accumulated or []
    edges = flow.state.edges_accumulated or []

    parties = _nodes_by_label(nodes, "Party")
    assert len(parties) == 2
    # Alice should have party_id assigned from fuzzy lookup
    alice = next(p for p in parties if p["properties"].get("name") == "Alice")
    assert alice["properties"].get("party_id") == "party-1"

    inv_edges = _edges_matching(edges, "INVOLVES")
    assert len(inv_edges) == 2
    for e in inv_edges:
        assert e["from"] == "n2"
        assert isinstance(e.get("properties"), dict)
        assert "role" in e["properties"]


