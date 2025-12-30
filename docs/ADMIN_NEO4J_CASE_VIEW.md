# Admin Neo4j Case View (Read-Only)

This repo’s normal case page (`/cases/[id]`) renders from **Postgres** (`cases.extracted` + `/display`), and supports editing/saving.

This feature adds an **admin-only**, **read-only** case view that renders from **Neo4j**.

---

## What it is

- **URL**: `/cases/[id]/neo4j`
- **Audience**: Admin users only (checked via `isAdminEmail()` in Next.js + session).
- **Purpose**: Inspect the Neo4j Knowledge Graph representation of a case using the same UI layout/components as the normal case page, but with **no edits**, **no saves**, **no deletes**, and **no KG writes**.

---

## Security / guardrails

- **Admin-only UI page**
  - The `/cases/[id]/neo4j` page redirects non-admins back to `/cases/[id]`.
  - The "Neo4j view (admin)" link on `/cases/[id]` is only shown to admins (and only when the case appears KG-submitted).
- **Admin-only proxy routes**
  - All Next.js proxy routes under `/api/admin/neo4j-cases/` check `isAdminEmail(session?.user?.email)` and return 401 if not admin.
  - Routes: `/api/admin/neo4j-cases/[caseId]/view` and `/api/admin/neo4j-cases/[caseId]/compare`
- **Backend API key protection**
  - FastAPI routes under `/api/ai/neo4j-cases/` require `X-API-Key` header.
  - The router uses `dependencies=[Depends(get_api_key)]` to enforce this.
  - The API key is only available server-side (never exposed to browser).
- **No Neo4j credentials in browser**
  - The browser calls a Next.js server route which proxies to the FastAPI backend using `X-API-Key`.
- **Read-only**
  - The page runs in `isViewMode = true` and does not render or invoke any save/edit/delete actions.
- **Embeddings excluded**
  - The Cypher query removes any `*_embedding` properties using APOC (`apoc.map.removeKeys(...)`).

---

## Data flow (high level)

1. User views a case at `/cases/[id]` (normal Postgres-backed view).
2. If the case has been submitted to KG (`kg_submitted_at` is set) and user is admin, the "Neo4j view (admin)" link appears.
3. The link includes the Neo4j `case_id` as a query parameter:
   - `/cases/[id]/neo4j?neo4j_case_id={case_id}`
   - The `case_id` is extracted from the Case node's `properties.case_id` in the frontend.
4. Neo4j view page reads the query param and calls:
   - `GET /api/admin/neo4j-cases/:neo4jCaseId/view?view=holdingsCentric`
5. Next.js proxies to FastAPI backend with `X-API-Key`:
   - `GET /api/ai/neo4j-cases/:neo4jCaseId/view?view=holdingsCentric`
6. FastAPI:
   - Executes the static Cypher file `ai-backend/app/cypher/case_graph.cypher` using the Neo4j case_id directly.
   - Converts the returned `case_data` into extracted-style `{ nodes, edges }`.
   - Runs `CaseViewBuilder` (`views_v3.json`) to build `displayData` and returns it.

### Important: Postgres ID vs Neo4j case_id

- **Postgres case ID**: The `cases` table primary key (UUID), used in URLs like `/cases/{id}`
- **Neo4j case_id**: A separate UUID stored as the `case_id` property on the Case node in Neo4j

These are different UUIDs. The frontend extracts the Neo4j `case_id` from the case data and passes it directly to the backend via query parameter.

---

## Key routes/files

### Frontend (Next.js)

- **Read-only Neo4j case view page**: `src/app/cases/[id]/neo4j/page.tsx`
- **Admin-only link from normal case page**: `src/app/cases/[id]/page.tsx`
- **Next.js admin proxy route**: `src/app/api/admin/neo4j-cases/[caseId]/view/route.ts`

### Backend (FastAPI)

- **Neo4j routes**: `ai-backend/app/routes/neo4j_cases.py`
  - `GET /api/ai/neo4j-cases/{case_id}/view?view=holdingsCentric`
- **Static Cypher**: `ai-backend/app/cypher/case_graph.cypher`
- **View config**: `ai-backend/views_v3.json`
- **View builder**: `ai-backend/app/lib/case_view_builder.py`

---

## Postgres ↔ Neo4j Comparison

The Neo4j view page includes a **comparison feature** that validates the Neo4j data against Postgres.

- Click "Run Comparison" on the Neo4j view page
- Shows green checkmark if all data matches, amber warning if differences found
- Expandable details for each node/edge with differences

**Frontend files:**
- Proxy route: `src/app/api/admin/neo4j-cases/[caseId]/compare/route.ts`
- UI component: `src/components/cases/ComparisonResults.tsx`

For full details on the comparison logic, API response format, and future integration points, see **[CASE_COMPARISON.md](./CASE_COMPARISON.md)**.

---

## Notes / troubleshooting

- **404 from `/neo4j-cases/{id}/view`**
  - The static Cypher includes a mandatory Proceeding match; if a case exists but has no proceedings, the backend falls back to returning empty proceedings.
- **Requires APOC**
  - The Cypher uses `apoc.map.removeKeys` / `apoc.map.merge`. Ensure APOC is available in the Neo4j instance.
