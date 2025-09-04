# File Import Flow Diagram

This diagram shows the complete path of a .docx import from the Next.js frontend through the Next.js API route to the FastAPI backend and into Neo4j.

```mermaid
flowchart TD
  subgraph Frontend[Next.js React App (port 3000)]
    A[User selects .docx on /import/page.tsx]
    A --> B[handleSubmit() builds FormData]
    B --> C[fetch('/api/import-kg')]
  end

  subgraph NextAPI[Next.js API Route (port 3000)]
    C --> D[src/app/api/import-kg/route.ts]
    D -->|Validate FASTAPI_API_KEY<br/>Rebuild FormData<br/>Add X-API-Key| E[fetch('http://localhost:8000/api/ai/import-kg/advanced')]
  end

  subgraph FastAPI[FastAPI Backend (port 8000)]
    E --> F[main.py includes router with prefix /api/ai]
    F --> G[POST /api/ai/import-kg/advanced (app/routes/ai.py)]
    G -->|Read file bytes<br/>Write temp .docx| H[ImportFlow.kickoff_async()]
    H --> I[ImportCrew.crew().kickoff()]
    I --> J[process_document_tool + generate_embeddings_tool]
    J --> K[DynamicDocumentProcessor<br/>Extract text → Identify entities/relationships<br/>Align schema → Generate Cypher]
    K --> L[Neo4j
MERGE nodes/relationships
Update properties/embeddings]
    L --> M[Result JSON { success, filename, result }]
  end

  M --> N[Next.js API route returns JSON to client]
  N --> O[Frontend updates UI (success/error)]

  classDef accent fill:#eef,stroke:#88f,color:#000;
  class Frontend accent;
  class NextAPI accent;
  class FastAPI accent;
```

## Key Notes

- Ports: Next.js on 3000; FastAPI on 8000.
- URL semantics:
  - Relative `/api/import-kg` → handled by Next.js routing (`src/app/api/import-kg/route.ts`).
  - Full `http://localhost:8000/api/ai/import-kg/advanced` → external request to FastAPI.
- Security: Next.js route injects `X-API-Key` header; FastAPI validates against `FASTAPI_API_KEY`.
- CORS: FastAPI allows origins including `http://localhost:3000`.
- Temporary file lifecycle: backend writes uploaded bytes to temp `.docx`, cleans up after processing.


