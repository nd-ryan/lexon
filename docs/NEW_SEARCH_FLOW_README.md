# New Search Flow Implementation

This document describes the new search flow implementation that uses a label/id block approach with batch enrichment.

## Overview

The new search flow (`NewSearchFlow`) implements a two-stage search process:

1. **Initial Query Stage**: Generate and execute a query that identifies relevant nodes and returns their labels, id fields, and id values
2. **Batch Enrichment Stage**: Execute batch queries to retrieve complete node data with relationships for the identified nodes
3. **Synthesis Stage**: Analyze the enriched data to provide comprehensive insights

## Files Created

### Models (`ai-backend/app/models/search.py`)
- `LabelIdBlock`: Represents a node label with its id field and values
- `LabelIdQueryResult`: Result from initial query containing label/id blocks
- `EnrichedNodeData`: Result from batch queries containing enriched node data

### Utility Functions (`ai-backend/app/lib/batch_query_utils.py`)
- `build_batch_query(label, id_field, id_values)`: Builds Cypher queries for batch node enrichment

### Configuration Files
- `ai-backend/app/flow_search/crews/search_crew/config/new_agents.yaml`: Agent definitions for new approach
- `ai-backend/app/flow_search/crews/search_crew/config/new_tasks.yaml`: Task definitions for new approach

### Flow Implementation (`ai-backend/app/flow_search/new_search_flow.py`)
- `NewSearchFlow`: Main flow class implementing the new approach
- `NewSearchState`: State management for the new flow
- `create_new_search_flow()`: Factory function

## How It Works

### Stage 1: Initial Query
The `new_query_generation_agent` creates a Cypher query that returns data in this format:
```json
[
  { "label": "Case", "id_field": "case_id", "id_values": ["C0016", "C0017"] },
  { "label": "Doctrine", "id_field": "doctrine_id", "id_values": ["D0002"] },
  { "label": "Issue", "id_field": "issue_id", "id_values": ["I0031", "I0032"] }
]
```

### Stage 2: Batch Enrichment
For each label/id block, the flow:
1. Calls `build_batch_query()` to create an enrichment query
2. Executes the query to get complete node data with relationships
3. Collects all enriched results

### Stage 3: Synthesis
The `insights_synthesis_agent` analyzes the enriched data to provide comprehensive insights.

## Usage

```python
from app.flow_search.new_search_flow import create_new_search_flow

# Create the flow
flow = create_new_search_flow()

# Set the query in state
flow.state.query = "Tell me about contract disputes in California"

# Execute the flow
result = await flow.kickoff()

# The result will be a StructuredSearchResponse with enriched data
```

## Key Differences from Original Flow

1. **Two-stage process**: Initial identification + batch enrichment vs. single enhanced query
2. **Structured identification**: Returns structured label/id blocks instead of immediate full data
3. **Batch processing**: Efficiently retrieves complete data for identified nodes
4. **Enhanced relationships**: Gets comprehensive relationship data for each node

## Preserved Original Code

All original files remain unchanged:
- `search_flow.py` - Original search flow
- `agents.yaml` - Original agent definitions  
- `tasks.yaml` - Original task definitions

The new implementation can be used alongside the original, allowing for easy rollback if needed.

## Configuration

The new flow uses separate configuration files (`new_agents.yaml`, `new_tasks.yaml`) to avoid conflicts with the original implementation.

## Error Handling

- Retry logic for initial query (up to 3 attempts with different strategies)
- Graceful handling of batch query failures
- Comprehensive logging throughout the process 