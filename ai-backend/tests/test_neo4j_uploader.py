from app.lib.neo4j_uploader import Neo4jUploader, get_id_prop_for_label, to_snake_case


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


def test_convert_date_rejects_placeholder_and_invalid_calendar_dates():
    uploader = Neo4jUploader(
        schema_payload=[],
        neo4j_client=object(),
    )

    # Placeholders for unknown month/day should be treated as missing
    assert uploader._convert_property_value("1942-00-00", "DATE") is None
    assert uploader._convert_property_value("1942-01-00", "DATE") is None
    assert uploader._convert_property_value("1942-00-15", "DATE") is None

    # Non-calendar dates should be treated as missing
    assert uploader._convert_property_value("1942-13-01", "DATE") is None
    assert uploader._convert_property_value("1942-02-30", "DATE") is None

    # Valid ISO calendar date should pass through
    assert uploader._convert_property_value("1942-12-01", "DATE") == "1942-12-01"


def test_generate_node_cypher_skips_invalid_date_values():
    schema_payload = [
        {
            "label": "Proceeding",
            "properties": {
                "proceeding_id": {"type": "STRING"},
                "hearing_date": {"type": "DATE"},
            },
        }
    ]
    uploader = Neo4jUploader(schema_payload=schema_payload, neo4j_client=object())

    node = {
        "label": "Proceeding",
        "properties": {
            "hearing_date": "1942-00-00",
        },
    }

    query, params = uploader._generate_node_cypher(node, is_existing=False)

    # Invalid date should not be passed to Neo4j's date() function
    assert "hearing_date" not in params
    assert "hearing_date" not in query
