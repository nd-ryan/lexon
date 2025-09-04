# Doctrine Search Comparison Test

This test compares the results between a manual Cypher query and the AI Agent search flow to ensure the search functionality is working correctly.

## Test Overview

**Test Query**: `"Can you get all the doctrines from the database"`

**Purpose**: Verify that the AI Agent search can correctly:
1. Interpret the user's natural language query
2. Use Neo4j MCP tools to query the database
3. Return actual doctrine data (not just summaries)
4. Provide both formatted results and raw JSON data

## Files

- `test_doctrine_search.py` - Main test script
- `run_doctrine_test.sh` - Shell script to run the test easily
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

The test script will automatically load these variables using `python-dotenv`.

## How to Run

### Option 1: Using the Shell Script (Recommended)
```bash
./run_doctrine_test.sh
```

### Option 2: Direct Python Execution
```bash
# Activate virtual environment first
source venv/bin/activate

# Run the test
python test_doctrine_search.py
```

## What the Test Does

### 1. Manual Cypher Query Test
Executes this direct Cypher query:
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
Sends the natural language query `"Can you get all the doctrines from the database"` through the AI Agent search flow using:
- CrewAI agents
- Neo4j MCP tools (`read-neo4j-cypher` and `get-neo4j-schema`)
- Structured output with Pydantic models

### 3. Results Comparison
Compares:
- **Result counts**: Manual vs AI search
- **Data quality**: Whether AI search captures actual doctrine data
- **Search quality**: Methodology, MCP tool usage, formatted results
- **Raw data availability**: Whether raw JSON results are provided

## Expected Output

The test will show:

```
🧪 DOCTRINE SEARCH COMPARISON TEST
===============================================================================
 MANUAL CYPHER QUERY TEST
===============================================================================
Query: MATCH (d:Doctrine) RETURN d.name as doctrine_name, ...

✅ Manual query executed successfully
Results found: 25

📋 DOCTRINE RESULTS (25 total):
   1. Abstention Doctrine
      Category: Judicial
      Description: A doctrine whereby federal courts refrain from...
   
   2. Clean Hands Doctrine
      Category: Equity
      Description: A legal principle that denies relief to...
   
   ... (more results)

===============================================================================
 AI AGENT SEARCH TEST
===============================================================================
Query: 'Can you get all the doctrines from the database'

🤖 Executing AI Agent search...
✅ AI search completed
Success: True
Total results: 25
Execution time: 4.32s
MCP tools used: True

📝 ANALYSIS SUMMARY:
Query interpretation: The user wants to retrieve all legal doctrines...

⚡ METHODOLOGY (4 steps):
  1. Called get-neo4j-schema to understand database structure
  2. Identified Doctrine nodes in the schema
  3. Constructed Cypher query to retrieve all doctrines
  4. Executed query and formatted results

💡 KEY INSIGHTS (3):
  • Found 25 legal doctrines in the database
  • Doctrines span multiple categories including Judicial, Equity, Constitutional
  • Most doctrines have comprehensive descriptions and source references

📋 FORMATTED RESULTS (25):
  • Abstention Doctrine - Federal courts refrain from exercising jurisdiction
  • Clean Hands Doctrine - Denies relief to parties with unclean hands
  • Commerce Clause Doctrine - Regulates interstate commerce
  ... (more results)

🔧 RAW QUERY RESULTS (25 items):
  1. {
      "doctrine_name": "Abstention Doctrine",
      "description": "A doctrine whereby federal courts refrain from...",
      "category": "Judicial",
      "source": "Federal Courts",
      "doctrine_id": 123
     }
  ... (more results)

===============================================================================
 RESULTS COMPARISON
===============================================================================
📊 RESULT COUNTS:
  Manual query: 25 doctrines
  AI search: 25 items
✅ Result counts match perfectly!

🎯 AI SEARCH QUALITY:
  ✅ MCP tools used
  ✅ Methodology mentions doctrines
  ✅ Formatted results contain doctrine info
  ✅ Raw query results available (25 items)
  ✅ Query interpretation mentions doctrines

📈 Quality Score: 5/5 (100%)
🏆 Excellent AI search performance!

===============================================================================
 TEST COMPLETED SUCCESSFULLY! ✅
===============================================================================
```

## Quality Metrics

The test evaluates AI search quality based on:

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
   - Ensure virtual environment is activated
   - Run `pip install -r requirements.txt`

## Test Results Storage

The test can optionally save detailed results to JSON files with timestamps:
- `doctrine_search_test_YYYYMMDD_HHMMSS.json`

These files contain complete test data for further analysis and debugging. 