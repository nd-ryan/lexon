import OpenAI from 'openai';

const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

const schema = `
## Node Labels & Properties

-   **\`Case\`**
    -   \`case_id\`: Unique ID for the case (e.g., "A018")
    -   \`case_name\`, \`case_number\`, \`case_type\`, \`court_level\`, \`decision_date\`, \`summary\`, \`status\`, \`outcome\`
-   **\`Party\`**
    -   \`party_id\`: Unique ID for the party
    -   \`party_name\`, \`party_type\`
-   **\`Provision\`**
    -   \`provision_id\`: Unique ID for the legal provision
    -   \`provision_name\`, \`provision_statute\`, \`provision_text\`
-   **\`Doctrine\`**
    -   \`doctrine_id\`: Unique ID for the doctrine
    -   \`doctrine_name\`, \`description\`
-   **\`Argument\`**
    -   \`argument_id\`: Unique ID for the argument
    -   \`argument_text\`, \`argument_pattern\`
-   **\`Allegation\`**
    -   \`allegation_id\`: Unique ID for the allegation
    -   \`allegation_text\`, \`type\`
-   **\`Ruling\`**
    -   \`ruling_id\`: Unique ID for the ruling
    -   \`ruling_date\`, \`vote_split\`, \`majority_author\`, \`majority_text\`, \`dissenting\`
-   **\`Relief\`**
    -   \`relief_id\`: Unique ID for the relief
    -   \`relief_type\`, \`relief_description\`, \`legal_basis\`, \`enforcement_mechanisms\`
-   **\`Evidence\`**
    -   \`document_id\`: Unique ID for the piece of evidence

## Relationship Types

-   \`(:Case)-[:HAS_PARTY {role: string}]->(:Party)\`
-   \`(:Case)-[:CITES_PROVISION]->(:Provision)\`
-   \`(:Case)-[:INCLUDES_ALLEGATION]->(:Allegation)\`
-   \`(:Case)-[:HAS_ARGUMENT]->(:Argument)\`
-   \`(:Case)-[:HAS_RULING]->(:Ruling)\`
-   \`(:Case)-[:HAS_RELIEF]->(:Relief)\`
-   \`(:Argument)-[:SUBMITTED_BY]->(:Party)\`
-   \`(:Argument)-[:SUPPORTS_DOCTRINE]->(:Doctrine)\`
-   \`(:Allegation)-[:ALLEGES_AGAINST]->(:Party | :Provision)\`
-   \`(:Ruling)-[:APPLIES_DOCTRINE]->(:Doctrine)\`
-   \`(:Evidence)-[:EVIDENCE_IN {type: string, description: string}]->(:Case)\`
`;

export async function generateCypher(userQuery: string): Promise<string> {
  const systemPrompt = `
You are a Neo4j expert. Your goal is to generate a Cypher query based on a user's natural language question.
You must use the following schema and only the schema provided to construct the query. Do not use any other labels, properties, or relationship types.

${schema}

IMPORTANT: When filtering on text-based properties like names or descriptions, always use a case-insensitive, partial match with the \`WHERE\` clause and \`toLower()\`. 
For example, to find a case named "Schenck", do NOT use \`{case_name: 'Schenck'}\`. Instead, use \`WHERE toLower(c.case_name) CONTAINS 'schenck'\`. 
This is more flexible and user-friendly. For ID properties (e.g., \`case_id\`, \`party_id\`), you should continue to use exact matches.

CRITICAL: Neo4j v4.4+ has deprecated the exists(variable.property) syntax. You MUST use "variable.property IS NOT NULL" instead.
- WRONG: WHERE exists(n.name)
- CORRECT: WHERE n.name IS NOT NULL
- WRONG: WHERE exists((n)-[:RELATIONSHIP]->())
- CORRECT: WHERE (n)-[:RELATIONSHIP]->() (relationship existence checks don't need exists())

You must not include any explanations, introductory text, or markdown formatting in your response. Only return the raw Cypher query.
For example, if the user asks "show me all cases", you should return "MATCH (c:Case) RETURN c.case_name, c.summary".
`;

  const response = await openai.chat.completions.create({
    model: 'gpt-4.1',
    messages: [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: userQuery },
    ],
    temperature: 0,
  });

  const rawQuery = response.choices[0].message.content;
  if (!rawQuery) {
    throw new Error('Failed to generate Cypher query.');
  }

  // Clean the query to remove markdown formatting
  const cleanedQuery = rawQuery.replace(/```(?:cypher)?\n([\s\S]*?)\n```/, '$1').trim();

  return cleanedQuery;
} 