# Knowledge Graph Schema

This document outlines the schema for the Neo4j knowledge graph, which is populated by uploading `.docx` files through the `/import` page.

## Node Labels & Properties

-   **`Case`**
    -   `case_id`: Unique ID for the case (e.g., "A018")
    -   `case_name`, `case_number`, `case_type`, `court_level`, `decision_date`, `summary`, `status`, `outcome`
    -   `embedding`: (Vector added by the background worker)
-   **`Party`**
    -   `party_id`: Unique ID for the party
    -   `party_name`, `party_type`
-   **`Provision`**
    -   `provision_id`: Unique ID for the legal provision
    -   `provision_name`, `provision_statute`, `provision_text`
-   **`Doctrine`**
    -   `doctrine_id`: Unique ID for the doctrine
    -   `doctrine_name`, `description`
-   **`Argument`**
    -   `argument_id`: Unique ID for the argument
    -   `argument_text`, `argument_pattern`
-   **`Allegation`**
    -   `allegation_id`: Unique ID for the allegation
    -   `allegation_text`, `type`
-   **`Ruling`**
    -   `ruling_id`: Unique ID for the ruling
    -   `ruling_date`, `vote_split`, `majority_author`, `majority_text`, `dissenting`
-   **`Relief`**
    -   `relief_id`: Unique ID for the relief
    -   `relief_type`, `relief_description`, `legal_basis`, `enforcement_mechanisms`
-   **`Evidence`**
    -   `document_id`: Unique ID for the piece of evidence

## Relationship Types

-   `(:Case)-[:HAS_PARTY {role: string}]->(:Party)`
-   `(:Case)-[:CITES_PROVISION]->(:Provision)`
-   `(:Case)-[:INCLUDES_ALLEGATION]->(:Allegation)`
-   `(:Case)-[:HAS_ARGUMENT]->(:Argument)`
-   `(:Case)-[:HAS_RULING]->(:Ruling)`
-   `(:Case)-[:HAS_RELIEF]->(:Relief)`
-   `(:Argument)-[:SUBMITTED_BY]->(:Party)`
-   `(:Argument)-[:SUPPORTS_DOCTRINE]->(:Doctrine)`
-   `(:Allegation)-[:ALLEGES_AGAINST]->(:Party | :Provision)`
-   `(:Ruling)-[:APPLIES_DOCTRINE]->(:Doctrine)`
-   `(:Evidence)-[:EVIDENCE_IN {type: string, description: string}]->(:Case)` 