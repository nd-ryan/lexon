import os
from openai import OpenAI
from typing import Optional
import logging

logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Neo4j schema definition
SCHEMA = """
## Node Labels & Properties

-   **`Case`**
    -   `case_id`: Unique ID for the case (e.g., "A018")
    -   `case_name`, `case_number`, `case_type`, `court_level`, `decision_date`, `summary`, `status`, `outcome`
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
"""

def generate_cypher_query(user_query: str) -> str:
    """
    Generate a Cypher query from a natural language question using OpenAI.
    
    Args:
        user_query: The user's natural language question
        
    Returns:
        A Cypher query string
        
    Raises:
        Exception: If the query generation fails
    """
    system_prompt = f"""
You are a Neo4j expert. Your goal is to generate a Cypher query based on a user's natural language question.
You must use the following schema and only the schema provided to construct the query. Do not use any other labels, properties, or relationship types.

{SCHEMA}

IMPORTANT: When filtering on text-based properties like names or descriptions, always use a case-insensitive, partial match with the `WHERE` clause and `toLower()`. 
For example, to find a case named "Schenck", do NOT use `{{case_name: 'Schenck'}}`. Instead, use `WHERE toLower(c.case_name) CONTAINS 'schenck'`. 
This is more flexible and user-friendly. For ID properties (e.g., `case_id`, `party_id`), you should continue to use exact matches.

You must not include any explanations, introductory text, or markdown formatting in your response. Only return the raw Cypher query.
For example, if the user asks "show me all cases", you should return "MATCH (c:Case) RETURN c.case_name, c.summary".
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            temperature=0
        )
        
        raw_query = response.choices[0].message.content
        if not raw_query:
            raise Exception("Failed to generate Cypher query - empty response")
        
        # Clean the query to remove markdown formatting
        cleaned_query = raw_query.strip()
        if cleaned_query.startswith("```"):
            # Remove code block markers
            lines = cleaned_query.split('\n')
            cleaned_query = '\n'.join(lines[1:-1]).strip()
        
        logger.info(f"Generated Cypher query: {cleaned_query}")
        return cleaned_query
        
    except Exception as e:
        logger.error(f"Error generating Cypher query: {e}")
        raise Exception(f"Failed to generate Cypher query: {str(e)}")

async def generate_cypher_query_async(user_query: str) -> str:
    """Async version of generate_cypher_query for use in FastAPI endpoints."""
    return generate_cypher_query(user_query) 