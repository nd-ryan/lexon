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


def test_check_node_isolation_ignores_shared_catalog_connections():
    """
    Case-unique nodes often connect to shared/catalog nodes (e.g., Case<-[:CONTAINS]-Domain,
    Relief-[:IS_TYPE]->ReliefType). These should NOT prevent deletion of the case-unique node.
    """
    schema_payload = [
        {"label": "Case", "case_unique": True, "can_create_new": True, "properties": {"case_id": {"type": "STRING"}}},
        {"label": "Domain", "case_unique": False, "can_create_new": False, "properties": {"domain_id": {"type": "STRING"}}},
    ]

    class _Client:
        def execute_query(self, query, params=None):
            # connected node is Domain (shared/catalog) and NOT in case_node_ids
            return [{"connected": {"domain_id": "d-outside"}, "labels": ["Domain"], "props": ["domain_id"]}]

    uploader = Neo4jUploader(schema_payload=schema_payload, neo4j_client=_Client())
    assert uploader.check_node_isolation("Case", "c1", case_node_ids=set()) is True


def test_check_node_isolation_blocks_external_case_unique_connections():
    """If a case-unique node connects to another case-unique node outside the case, do not delete it."""
    schema_payload = [
        {"label": "Case", "case_unique": True, "can_create_new": True, "properties": {"case_id": {"type": "STRING"}}},
    ]

    class _Client:
        def execute_query(self, query, params=None):
            # connected node is another Case (case-unique) not in case_node_ids
            return [{"connected": {"case_id": "c-external"}, "labels": ["Case"], "props": ["case_id"]}]

    uploader = Neo4jUploader(schema_payload=schema_payload, neo4j_client=_Client())
    assert uploader.check_node_isolation("Case", "c1", case_node_ids={"c1"}) is False
