from app.lib.neo4j_uploader import get_id_prop_for_label, to_snake_case


def test_to_snake_case():
    assert to_snake_case("CaseEvent") == "case_event"
    assert to_snake_case("URLValue") == "url_value"


def test_get_id_prop_for_label_prefers_schema():
    schema_payload = [
        {"label": "Case", "properties": {"case_id": {"type": "STRING"}}},
        {"label": "Person", "properties": {"custom_id": {"type": "STRING"}}},
    ]

    assert get_id_prop_for_label("Case", schema_payload) == "case_id"
    assert get_id_prop_for_label("Person", schema_payload) == "custom_id"
    # Fallback when nothing matches
    assert get_id_prop_for_label("Unknown", schema_payload) == "unknown_id"
