import json
from pathlib import Path

import pytest

from tests._case_extract_test_utils import FakeCrewResult, FakePydantic


def _load_min_schema() -> list[dict]:
    here = Path(__file__).parent
    payload = json.loads((here / "fixtures" / "case_extract_schema_min.json").read_text())
    assert isinstance(payload, list)
    return payload


def test_parse_selection_response_accepts_pydantic_raw_and_string():
    from app.flow_cases.case_extract_flow_v3 import CaseExtractFlow

    flow = CaseExtractFlow()

    # 1) pydantic-like
    res1 = FakeCrewResult(pydantic=FakePydantic({"selected": {"Forum": ["f1"]}}))
    assert flow.parse_selection_response(res1) == {"Forum": ["f1"]}

    # 2) JSON string
    res2 = json.dumps({"selected": {"Forum": ["f2"]}})
    assert flow.parse_selection_response(res2) == {"Forum": ["f2"]}

    # 3) dict
    res3 = {"selected": {"Forum": ["f3"]}}
    assert flow.parse_selection_response(res3) == {"Forum": ["f3"]}

    # 4) weird input -> empty
    assert flow.parse_selection_response(object()) == {}


def test_validate_with_model_drops_unknown_fields_and_keeps_known():
    from app.lib.schema_runtime import prune_ui_schema_for_llm, build_property_models
    from app.flow_cases.case_extract_flow_v3 import CaseExtractFlow

    schema_payload = _load_min_schema()
    spec = prune_ui_schema_for_llm(schema_payload)
    models_by_label, _, _, _, _ = build_property_models(spec)

    flow = CaseExtractFlow()
    model = models_by_label["Case"]

    props = {"case_id": "c1", "name": "X", "citation": "Y", "unknown_field": "NOPE"}
    cleaned = flow.validate_with_model(props, model)

    assert cleaned["case_id"] == "c1"
    assert cleaned["name"] == "X"
    assert cleaned["citation"] == "Y"
    assert "unknown_field" not in cleaned


def test_validate_relationship_properties_enforces_schema_or_falls_back(monkeypatch: pytest.MonkeyPatch):
    from app.lib.schema_runtime import build_relationship_property_models
    from app.flow_cases.case_extract_flow_v3 import CaseExtractFlow

    schema_payload = _load_min_schema()
    rel_models, _rel_meta = build_relationship_property_models(schema_payload)

    flow = CaseExtractFlow()
    flow.state.rel_prop_models_by_key = rel_models

    # Validated path (schema exists for Proceeding-INVOLVES)
    props = {"role": "plaintiff", "extra": "drop-me", "none_val": None}
    out = flow.validate_relationship_properties("Proceeding", "INVOLVES", props)
    assert out == {"role": "plaintiff"}

    # Fallback path: no schema for this relationship -> filters Nones only
    out2 = flow.validate_relationship_properties("Case", "UNKNOWN_REL", {"a": 1, "b": None})
    assert out2 == {"a": 1}


