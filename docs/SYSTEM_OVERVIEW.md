# Lexon System Overview

## Core Purpose
Lexon is a legal knowledge and reasoning platform built around a Neo4j knowledge graph.
Primary goals:
- Ingest legal case data into a structured graph using AI-powered extraction.
- Support semantic + relational search for lawyers.
- Provide AI-generated reasoning and summaries.
- Enable efficient batch queries and node enrichment.

## Architecture

### Frontend
- **Framework:** Next.js 15 (React 19, TypeScript, Tailwind CSS 4)
- **State Management:** Zustand
- **UI Components:** Custom Tailwind CSS components
- **Authentication:** NextAuth.js (credentials provider) + **role-based access control (RBAC)**
- **Database:** Prisma ORM with PostgreSQL (**`auth` schema**: users/sessions/search history + user role)
- **Deployment:** Vercel (serverless functions)

### Backend
- **Framework:** FastAPI (Python 3.11)
- **AI Framework:** CrewAI (multi-agent orchestration)
- **Queue System:** Redis with RQ (Python) for background jobs
- **Database Connections:**
  - Neo4j (knowledge graph) - via official Neo4j driver and MCP integration
  - PostgreSQL (case metadata, jobs) - via SQLAlchemy (**`app` schema**; Alembic migrations)
- **Streaming:** JWT-based streaming with Redis pub/sub (bypasses Vercel 60s timeout)
- **Security:** API key authentication + JWT tokens for streaming
- **Deployment:** Fly.io (persistent containers)

### Infrastructure
- **Knowledge Graph:** Neo4j (managed service/Aura)
- **Relational DB:** PostgreSQL (managed service)
- **Queue/Cache:** Redis (managed service)
- **AI Provider:** OpenAI (GPT-4 for extraction and reasoning)

## Key Modules

### AI Flows (CrewAI-based)
1. **Case Extraction Flow (v3)**
   - Multi-phase extraction of legal case data
   - Extracts: Cases, Proceedings, Issues, Parties, Rulings, Arguments, Laws, Concepts, Relief
   - Uses CrewAI agents with MCP tools for Neo4j operations
   - Background job processing via Redis Queue

2. **Search Flow**
   - Two-stage search process:
     - Initial query returns label/id blocks
     - Batch enrichment retrieves complete node data
   - Semantic + relational search with AI synthesis
   - Real-time streaming of results

3. **Import Flow**
   - Document processing and import
   - Supports various document formats (DOCX, PDF, etc.)

4. **Knowledge Graph Flow**
   - Graph operations and maintenance
   - Schema validation and updates

### Core Libraries
- **Neo4j Client:** Custom client with Cypher query execution
- **MCP Integration:** Model Context Protocol for Neo4j tool access
- **Embeddings:** OpenAI embeddings for semantic search
- **Batch Query Utils:** Efficient batch node enrichment
- **Case Repository:** PostgreSQL-based case metadata management
- **Schema Management:** Dynamic schema validation and runtime checks

### API Routes
- `/api/search/crew` - Search with CrewAI agents
- `/api/search/crew/stream` - Streaming search results
- `/api/cases/upload` - Case document upload
- `/api/cases/[id]` - Case retrieval and display
- `/api/auth/*` - Authentication endpoints
- `/api/ai/*` - Backend AI endpoints (FastAPI)

## Key Features
- **Streaming Architecture:** Direct backend connections with JWT auth for unlimited streaming duration
- **Background Processing:** Async job queue for long-running AI operations
- **Progress Tracking:** Real-time progress updates via Redis pub/sub
- **Multi-agent AI:** Orchestrated CrewAI agents for complex extraction tasks
- **Batch Enrichment:** Efficient querying of large node sets
- **Schema-driven:** Dynamic schema validation and property filtering
- **RBAC:** `user`, `editor`, `developer`, `admin` roles gate UI pages and API routes
