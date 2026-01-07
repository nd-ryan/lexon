# Chat Query Flow

This document describes how the chat feature works, including the query flow that retrieves structured data from Neo4j and how OpenAI synthesizes answers.

## Overview

The chat system uses OpenAI's Responses API with tool calling to answer legal questions. When a user asks a question:

1. OpenAI decides whether to query the knowledge graph
2. If needed, it calls the `run_query` tool which executes `QueryFlow`
3. QueryFlow returns structured node data from Neo4j
4. OpenAI synthesizes a natural language answer from the data
5. The answer streams back to the user via SSE

```
┌──────────┐    ┌──────────────┐    ┌──────────────┐    ┌─────────┐
│  User    │───▶│  Next.js API │───▶│  FastAPI     │───▶│  OpenAI │
│  Input   │    │  /api/v1/chat│    │  /chat       │    │  (GPT)  │
└──────────┘    └──────────────┘    └──────────────┘    └────┬────┘
                                                             │
                                           tool_choice="auto"│
                                                             ▼
                                    ┌────────────────────────────────┐
                                    │   If run_query tool called:    │
                                    │   ┌──────────────────────┐     │
                                    │   │     QueryFlow        │     │
                                    │   │  ┌────────────────┐  │     │
                                    │   │  │ 1. Reasoning   │  │     │
                                    │   │  │ 2. Planning    │  │     │
                                    │   │  │ 3. Vector Search│ │     │
                                    │   │  │ 4. Traversal   │  │     │
                                    │   │  │ 5. Enrichment  │  │     │
                                    │   │  └────────────────┘  │     │
                                    │   └──────────┬───────────┘     │
                                    │              │                 │
                                    │              ▼                 │
                                    │   { enriched_nodes: [...] }   │
                                    └────────────────────────────────┘
                                                   │
                                                   ▼
                                    ┌────────────────────────────────┐
                                    │  OpenAI synthesizes answer     │
                                    │  from enriched_nodes data      │
                                    └────────────────────────────────┘
                                                   │
                                                   ▼
                                    ┌────────────────────────────────┐
                                    │  SSE Stream to Frontend        │
                                    │  data: {"type": "delta", ...}  │
                                    └────────────────────────────────┘
```

## API Endpoints

### Frontend Proxy: `POST /api/v1/chat`

**Location:** `src/app/api/v1/chat/route.ts`

The Next.js API route that proxies requests to the backend:
- Validates user session via NextAuth
- Forwards request to FastAPI with `X-API-Key` header
- Passes through SSE stream response

**Request:**
```json
{
  "conversation_id": "resp_abc123...",  // Optional, for continuing conversations
  "input": "What are the antitrust implications of platform monopolies?"
}
```

### Backend: `POST /api/v1/chat`

**Location:** `ai-backend/app/routes/chat.py`

The FastAPI endpoint that orchestrates the chat:
- Uses OpenAI Responses API with streaming
- Provides `run_query` tool for knowledge graph access
- Handles tool execution and follow-up responses

## OpenAI Tool: `run_query`

The chat gives OpenAI access to a `run_query` tool:

```json
{
  "type": "function",
  "name": "run_query",
  "description": "Execute a knowledge graph query to retrieve relevant legal nodes...",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "The search query to execute against the knowledge graph"
      }
    },
    "required": ["query"]
  }
}
```

OpenAI decides when to call this tool based on the user's question. For legal questions, it typically calls the tool. For casual conversation, it may respond directly.

## QueryFlow: 5-Stage Pipeline

When `run_query` is called, it executes `QueryFlow` which has 5 stages:

**Location:** `ai-backend/app/flow_query/query_flow.py`

### Stage 1: Reasoning (`reason_query`)

An LLM generates a natural language reasoning paragraph about how to answer the query:
- Identifies target node types (Doctrine, Ruling, Issue, etc.)
- Chooses embedding anchor types for semantic search
- Plans the traversal path through the graph

**Example output:**
> "The final targets are Rulings and Doctrines. The embedding anchor should be Issue.text to find relevant legal issues. From Issues, traverse to Doctrines via RELATES_TO_DOCTRINE, and to Rulings via Proceeding."

### Stage 2: Planning (`interpret_query`)

Converts the reasoning into a formal JSON search plan:

```json
{
  "steps": [
    {
      "node_type": "Issue",
      "search_type": "embedding",
      "query_term": "platform monopolies, dominant digital platforms",
      "embedding_property": "text",
      "role": "anchor"
    },
    {
      "node_type": "Doctrine",
      "search_type": "deterministic",
      "path": ["Issue", "Doctrine"],
      "depends_on": [0],
      "role": "expand"
    },
    {
      "node_type": "Ruling",
      "search_type": "deterministic",
      "path": ["Issue", "Proceeding", "Ruling"],
      "depends_on": [0],
      "role": "expand"
    }
  ]
}
```

**Step Types:**
- `embedding`: Vector similarity search on a specific property
- `deterministic`: Graph traversal following schema relationships

### Stage 3: Vector Searches (`execute_searches`)

Executes all embedding steps in parallel:
- Generates embeddings for query terms
- Queries Neo4j vector indexes
- Collects matching nodes with similarity scores
- Uses configurable similarity threshold (default: 0.7)

### Stage 4: Deterministic Traversal (`deterministic_traversal`)

Follows graph relationships from found nodes:
- Uses `depends_on` to chain steps together
- Automatically looks up relationship names from schema
- Handles forward and backward traversal
- Limits expansion to prevent result explosion

### Stage 5: Enrichment (`gather_enriched_data`)

Fetches complete data for all found nodes:
- Groups nodes by label
- Executes batch queries for efficiency
- Retrieves full properties and relationship summaries
- Strips internal fields (embeddings, upload codes)

**Output:**
```json
{
  "query": "What are the antitrust implications of platform monopolies?",
  "enriched_nodes": [
    {
      "node_label": "Issue",
      "issue_id": "d989df7f-...",
      "text": "Whether Google maintained monopoly power...",
      "relationships": { "RELATES_TO_DOCTRINE": 3, "PART_OF": 1 }
    },
    {
      "node_label": "Doctrine",
      "doctrine_id": "b2f35703-...",
      "name": "Rule of Reason",
      "description": "Courts consider procompetitive justifications...",
      "relationships": { ... }
    }
  ]
}
```

## Answer Synthesis

After QueryFlow returns, OpenAI receives the enriched nodes and synthesizes an answer following these instructions:

1. **Use only the tool data** - Base answers strictly on `enriched_nodes`
2. **Cite every claim** - Format: `"Statement (NodeType: first_8_chars_of_id)"`
3. **Structure by data** - Organize around the node types returned
4. **Handle empty results** - Explain when data is insufficient
5. **No fabrication** - Never invent cases, laws, or facts

**Example citation:**
> "Google maintained monopoly power in the ad tech market (Issue: d989df7f). Courts apply the Rule of Reason doctrine when evaluating such claims (Doctrine: b2f35703)."

## SSE Response Format

The endpoint streams Server-Sent Events:

```
data: {"type": "delta", "content": "Google"}
data: {"type": "delta", "content": " maintained"}
data: {"type": "delta", "content": " monopoly power..."}
...
data: {"type": "completed", "conversation_id": "resp_abc123..."}
data: [DONE]
```

**Event Types:**
- `delta`: Text chunk of the response
- `completed`: Includes `conversation_id` for continuing the conversation
- `error`: Error message if something fails

## Configuration

### Model
Currently uses `gpt-5.1` for both reasoning/planning and answer synthesis.

### Vector Search
- Default similarity threshold: 0.7
- Default result limit per search: 10
- Index names derived from `schema_v3.json`

### Environment Variables
- `OPENAI_API_KEY`: Required for LLM calls
- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`: Knowledge graph connection
- `FASTAPI_API_KEY`: API authentication

## Related Files

- `ai-backend/app/routes/chat.py` - Chat endpoint and OpenAI integration
- `ai-backend/app/flow_query/query_flow.py` - QueryFlow implementation
- `ai-backend/app/flow_query/__init__.py` - Flow exports
- `ai-backend/app/lib/batch_query_utils.py` - Batch enrichment queries
- `ai-backend/app/lib/embeddings.py` - Embedding generation
- `src/app/api/v1/chat/route.ts` - Frontend API proxy
- `src/app/chat/page.tsx` - Chat UI component
