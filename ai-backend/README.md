# AI Backend - Python FastAPI + CrewAI

This is the migrated AI backend that consolidates all AI functionality from the Next.js application into a Python FastAPI service with CrewAI integration.

## What Was Migrated

### From Node.js to Python:
1. **Natural Language to Cypher Query Generation** (`/api/search`)
2. **Document Processing and Knowledge Graph Creation** (`/api/import-kg`)
3. **Vector Embeddings Generation** (background jobs)
4. **Neo4j Query Execution**

### Enhanced with CrewAI:
- **Search Agent**: Specialized in knowledge graph queries and analysis
- **Document Processor Agent**: Expert in legal document parsing
- **Embeddings Agent**: Semantic analysis and similarity search
- **Research Agent**: Comprehensive legal research capabilities
- **Writer Agent**: Content creation based on research findings

## Architecture

```
FastAPI Backend (Port 8000)
├── /api/ai/search                    # Basic search (migrated)
├── /api/ai/search/crew              # Enhanced search with CrewAI
├── /api/ai/search/similarity        # Semantic similarity search
├── /api/ai/import-kg                # Document import (migrated)
├── /api/ai/import-kg/crew          # Enhanced import with CrewAI
├── /api/ai/embeddings/generate     # Generate embeddings
├── /api/ai/embeddings/crew         # Enhanced embeddings with CrewAI
├── /api/ai/research                 # AI research workflows
├── /api/ai/research/comprehensive  # Multi-agent research
├── /api/ai/analysis/case           # Case analysis
├── /api/ai/analysis/patterns       # Pattern analysis
└── /api/ai/health                  # Health check
```

## Key Features

### 1. **Direct Migration Endpoints**
- `/api/ai/search` - Direct replacement for Next.js search
- `/api/ai/import-kg` - Direct replacement for Next.js import

### 2. **Enhanced CrewAI Endpoints**
- `/api/ai/search/crew` - AI agents analyze and enhance search results
- `/api/ai/import-kg/crew` - AI agents provide document processing insights
- `/api/ai/research` - Multi-agent research workflows

### 3. **New Capabilities**
- Semantic similarity search using embeddings
- Comprehensive case analysis
- Pattern analysis across the knowledge graph
- Multi-agent collaborative research

## Setup Instructions

1. **Install Dependencies**
   ```bash
   cd ai-backend
   pip install -r requirements.txt
   ```

2. **Environment Variables**
   Create a `.env` file:
   ```bash
   OPENAI_API_KEY=your_openai_api_key
   NEO4J_URI=bolt://localhost:7687
   NEO4J_USERNAME=neo4j
   NEO4J_PASSWORD=your_password
   ```

3. **Start the Server**
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

4. **Update Frontend**
   Set `NEXT_PUBLIC_AI_BACKEND_URL=http://localhost:8000` in your Next.js `.env.local`

## API Usage Examples

### Basic Search (Migrated)
```bash
curl -X POST "http://localhost:8000/api/ai/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "show me all cases"}'
```

### Enhanced Search with CrewAI
```bash
curl -X POST "http://localhost:8000/api/ai/search/crew" \
  -H "Content-Type: application/json" \
  -d '{"query": "analyze the relationship between constitutional cases and free speech"}'
```

### Comprehensive Research
```bash
curl -X POST "http://localhost:8000/api/ai/research/comprehensive" \
  -H "Content-Type: application/json" \
  -d '{"topic": "First Amendment jurisprudence"}'
```

## Frontend Integration

The Next.js frontend has been updated to call the new Python backend:

- **Search Page**: `src/app/search/page.tsx` now includes basic and CrewAI search options
- **Import Page**: `src/app/import/page.tsx` calls the new Python import endpoint

## Benefits of Migration

1. **Unified AI Stack**: All AI operations in Python with consistent libraries
2. **CrewAI Integration**: Multi-agent workflows for enhanced analysis
3. **Better Performance**: Optimized Python AI libraries and async processing
4. **Extensibility**: Easy to add new agents and tasks
5. **Consistency**: Single source of truth for AI functionality

## Next Steps

1. **Remove Old Node.js AI Code**: Delete the old API routes in Next.js
2. **Add Authentication**: Integrate with NextAuth for secure API access
3. **Background Jobs**: Set up Redis for async embedding generation
4. **Monitoring**: Add logging and monitoring for the AI backend
5. **Deploy**: Configure production deployment for the AI backend 