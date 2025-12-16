# AGENTS.md

This repo has two main parts:

- **Frontend**: Next.js app in the repo root (`src/`, Prisma, Vitest)
- **Backend**: FastAPI + RQ workers in `ai-backend/` (Poetry, pytest)

## Setup commands

### Frontend (Next.js)

- Install deps: `npm install` (runs `prisma generate` via `postinstall`)
- Start dev server: `npm run dev` (defaults to `http://localhost:3000`)
- Lint: `npm run lint` (or `npm run lint:eslint`)
- Tests: `npm test` (Vitest)

### Backend (FastAPI / workers)

From `ai-backend/`:

- Install deps: `poetry install`
- Start API: `poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
- Start worker: `poetry run python worker.py` (needs `REDIS_URL`, defaults to `redis://localhost:6379`)
- Run both via Procfile (recommended): `poetry run honcho start` (uses `ai-backend/Procfile`)

## Environment variables

### Frontend (`.env.local`)

- `JWT_SECRET` (must match backend)
- `AI_BACKEND_URL` (e.g. `http://localhost:8000`)
- `NEXTAUTH_SECRET`
- `FASTAPI_API_KEY` (used by Next.js to call protected backend routes)
- `DATABASE_URL` (Prisma/Postgres; required for auth/session features)

### Backend (`ai-backend/.env`)

- `JWT_SECRET` (must match frontend)
- `FASTAPI_API_KEY`
- `REDIS_URL`
- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
- `OPENAI_API_KEY`

## Testing instructions

### Frontend

- Unit tests: `npm test`

### Backend

From `ai-backend/`:

- Default tests: `poetry run pytest` (also available as `make test`)
- Coverage: `make test-cov`

**Integration tests** are marked with `@pytest.mark.integration` and may hit real services (Neo4j Aura/local, MCP tools, LLMs). Don’t run them unless you’ve set the required env vars.

Useful docs/scripts:

- `docs/TEST_README.md` (Doctrine search comparison and integration test guidance)
- `ai-backend/run_doctrine_test.sh` (loads `ai-backend/.env` if present)

## Code style / conventions

- TypeScript is **strict** (`tsconfig.json`)
- ESLint is configured via `eslint.config.mjs` (generated Prisma client code under `src/generated/**` is ignored)
- Backend is **Poetry-first** (`ai-backend/pyproject.toml`)

## Notes for agents

- Documentation lives in `docs/`. Add new docs there (don’t scatter `.md` files around the repo root).
- If you add/update/delete tests, update the relevant test manifest file: `src/test/TEST_MANIFEST.md` (frontend) or `ai-backend/tests/TEST_MANIFEST.md` (backend).
- The backend exposes `/health` and uses port **8000** by default.
- Many backend routes require an API key; streaming endpoints use JWTs (see `docs/ARCHITECTURE.md`).
