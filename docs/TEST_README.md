# Doctrine Search Comparison Test

This doc describes how to validate Doctrine retrieval via:
- a **direct Cypher query** (via our Neo4j client wrapper), and
- the **AI SearchFlow** (LLM + Neo4j MCP tools).

## Test Overview

**Test Query**: `"Can you get all the doctrines from the database"`

**Purpose**: Verify that the AI Agent search can correctly:
1. Interpret the user's natural language query
2. Use Neo4j MCP tools to query the database
3. Return actual doctrine data (not just summaries)
4. Provide both formatted results and raw JSON data

## Files

- `ai-backend/tests/test_doctrine_query_integration.py` - Direct Cypher Doctrine query (shape check)
- `ai-backend/tests/test_search_flow_integration.py` - End-to-end SearchFlow (very heavyweight, opt-in)
- `ai-backend/run_doctrine_test.sh` - Convenience runner for the above tests
- `TEST_README.md` - This documentation file

## Prerequisites

### Environment Variables Setup
The test requires AuraDB connection credentials. Set these environment variables:

```bash
export NEO4J_URI="neo4j+s://your-instance-id.databases.neo4j.io"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="your-password-here"
```

### Using .env file (Recommended)
Create a `.env` file in the ai-backend directory (`/Users/john/WebDev/lexon/ai-backend/.env`):
```
NEO4J_URI=neo4j+s://your-instance-id.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password-here
```

`ai-backend/run_doctrine_test.sh` will load this `.env` file if present.

### Python dependencies (current)
The supported dependency workflow for `ai-backend` is **Poetry** (see `ai-backend/pyproject.toml` and `ai-backend/Dockerfile`).

From `ai-backend/`:

```bash
poetry install
```

Note: this backend is Poetry-first (and deploys via Poetry in Docker).

## How to Run

### Option 1: Using the Shell Script (Recommended)
```bash
cd ai-backend
./run_doctrine_test.sh
```

### Option 2: Run the tests directly (pytest)
```bash
cd ai-backend

# Direct Cypher doctrine query shape check (requires Neo4j env vars)
poetry run pytest -m integration -v tests/test_doctrine_query_integration.py

# Full SearchFlow end-to-end (requires Neo4j env vars + OPENAI_API_KEY; opt-in)
RUN_SEARCH_FLOW_INTEGRATION=1 poetry run pytest -m integration -v tests/test_search_flow_integration.py
```

## What the Test Does

### 1. Manual Cypher Query Test
Executes this direct Cypher query (via `tests/test_doctrine_query_integration.py`):
```cypher
MATCH (d:Doctrine)
RETURN d.name as doctrine_name, 
       d.description as description,
       d.category as category,
       d.source as source,
       id(d) as doctrine_id,
       labels(d) as labels,
       properties(d) as all_properties
ORDER BY d.name
```

### 2. AI Agent Search Test
Sends the natural language query `"Can you get all the doctrines from the database"` through `SearchFlow` (see `tests/test_search_flow_integration.py`) using:
- an LLM (requires `OPENAI_API_KEY`)
- Neo4j MCP tools (spawns the `mcp-neo4j-cypher` CLI; tools include `get-neo4j-schema` and `read-neo4j-cypher`)
- a structured response model (`StructuredSearchResponse`)

### 3. Results Comparison
At the moment, the automated checks are:
- **Manual query**: query runs and returned rows have a consistent shape (it does not assert doctrines exist).
- **SearchFlow**: returns a `StructuredSearchResponse` with non-empty explanation, plus `cypher_queries` and `raw_results` lists.

## Expected Output

These are pytest-based checks; successful runs look like standard pytest output. For example:

```bash
cd ai-backend
poetry run pytest -m integration -v tests/test_doctrine_query_integration.py
```

## Quality Metrics

If you want to add “comparison” scoring/metrics (counts match, formatted outputs, raw JSON dump), that logic is not currently implemented as a standalone script in this repo. The current automated checks focus on end-to-end viability and output shape.

If you do implement metrics, the suggested dimensions are:

1. **MCP Tools Usage** - Whether Neo4j MCP tools were used
2. **Methodology Relevance** - Whether the methodology mentions doctrines
3. **Formatted Results Quality** - Whether formatted results contain doctrine information
4. **Raw Data Availability** - Whether raw JSON query results are provided
5. **Query Interpretation** - Whether the AI correctly understood the request

**Quality Scores**:
- 80-100%: 🏆 Excellent
- 60-79%: 👍 Good
- 40-59%: ⚠️ Fair (needs improvement)
- 0-39%: ❌ Poor (requires investigation)

## Troubleshooting

### Common Issues

1. **Neo4j Connection Failed**
   ```
   ❌ Neo4j connection failed: ConnectionError
   ```
   - Ensure Neo4j is running
   - Check environment variables (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)

2. **MCP Tools Not Available**
   ```
   ❌ MCP tools not used
   ```
   - Ensure `mcp-neo4j-cypher` is installed
   - Check MCP server configuration

3. **No Doctrines Found**
   ```
   ❌ No doctrines found in the database
   ```
   - Verify database contains Doctrine nodes
   - Check if data was imported correctly

4. **Import Errors**
   ```
   ❌ Dependencies missing
   ```
   - Ensure Poetry dependencies are installed: `poetry install`

## Test Results Storage

The current pytest checks do not write result JSON files by default.