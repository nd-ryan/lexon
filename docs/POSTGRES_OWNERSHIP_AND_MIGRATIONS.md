## Postgres ownership & migrations (safety-first)

This repo uses **one Postgres database** for multiple concerns:

- **Frontend (Prisma / NextAuth)**: `User`, `Session`, `Account`, `VerificationToken`, `SearchHistory`
- **Backend (FastAPI / SQLAlchemy)**: `cases`, `graph_events`, `case_comparisons`, `pending_kg_deletions`, etc.

To avoid accidental table drops/changes, we enforce **single-owner-per-table** and isolate owners using **Postgres schemas + restricted DB users**.

### Goals

- **No automatic schema mutation at runtime** (neither frontend nor backend should `CREATE/ALTER` tables on startup).
- **No cross-service DDL**: frontend cannot touch backend tables, backend cannot touch auth tables.
- **All schema changes are explicit migrations** (Prisma migrations for Prisma-owned tables; Alembic migrations for backend-owned tables).

---

## 1) Target structure

### Schemas

- `auth` schema: Prisma-managed tables only (NextAuth + SearchHistory + RBAC role column)
- `app` schema: backend-managed tables only

### Database users (recommended)

- `lexon_auth` (frontend): privileges only on `auth` schema
- `lexon_app` (backend): privileges only on `app` schema

---

## 2) One-time DB setup (schemas + move tables)

Run this as a **database owner** / admin user (not the application users).

> This is non-destructive (no drops), but it **does move tables between schemas**.

```sql
BEGIN;

CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS app;

-- Prisma/NextAuth tables (Prisma uses quoted, capitalized names)
ALTER TABLE IF EXISTS public."User"              SET SCHEMA auth;
ALTER TABLE IF EXISTS public."Account"           SET SCHEMA auth;
ALTER TABLE IF EXISTS public."Session"           SET SCHEMA auth;
ALTER TABLE IF EXISTS public."VerificationToken" SET SCHEMA auth;
ALTER TABLE IF EXISTS public."SearchHistory"     SET SCHEMA auth;

-- If present (depends on whether Prisma Migrate was ever used)
ALTER TABLE IF EXISTS public."_prisma_migrations" SET SCHEMA auth;

-- Backend tables (typically unquoted, lowercase)
ALTER TABLE IF EXISTS public.cases               SET SCHEMA app;
ALTER TABLE IF EXISTS public.graph_events        SET SCHEMA app;
ALTER TABLE IF EXISTS public.case_comparisons    SET SCHEMA app;
ALTER TABLE IF EXISTS public.pending_kg_deletions SET SCHEMA app;

COMMIT;
```

---

## 3) Connection strings

### Frontend (Prisma)

Prisma must connect with a URL that targets the `auth` schema. Prisma uses the URL query param `schema=...`.

- `.env.local` (frontend):

```env
DATABASE_URL="postgresql://.../yourdb?schema=auth"
```

### Backend (SQLAlchemy)

Backend should connect normally and set `POSTGRES_SCHEMA=app`, but **should not rely on `search_path`** (especially with hosted poolers like Neon).
This codebase schema-qualifies backend-owned tables using `POSTGRES_SCHEMA` so queries target `app.*` explicitly.

- `ai-backend/.env` (backend):

```env
DATABASE_URL="postgresql://.../yourdb"
POSTGRES_SCHEMA="app"
```

---

## 4) Lock down permissions (strongly recommended)

Run as DB admin user.

```sql
-- Create roles/users (adjust auth method per your host)
CREATE ROLE lexon_auth LOGIN PASSWORD '...';
CREATE ROLE lexon_app  LOGIN PASSWORD '...';

-- Revoke default privileges (optional, but safer)
REVOKE ALL ON SCHEMA public FROM PUBLIC;

-- AUTH schema: frontend-only
GRANT USAGE ON SCHEMA auth TO lexon_auth;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA auth TO lexon_auth;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA auth TO lexon_auth;

-- APP schema: backend-only
GRANT USAGE ON SCHEMA app TO lexon_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO lexon_app;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA app TO lexon_app;

-- Ensure future tables inherit permissions
ALTER DEFAULT PRIVILEGES IN SCHEMA auth GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO lexon_auth;
ALTER DEFAULT PRIVILEGES IN SCHEMA app  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO lexon_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA auth GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO lexon_auth;
ALTER DEFAULT PRIVILEGES IN SCHEMA app  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO lexon_app;
```

At this point, **even if someone runs a destructive tool**, it should fail due to missing permissions.

---

## 5) Prisma migrations (baseline + future changes)

This repo now includes a baseline migration at `prisma/migrations/0000_baseline/migration.sql`.

Baseline strategy:

- The baseline migration represents the **current Prisma schema** (NextAuth + SearchHistory + `User.role`).
- On an existing DB that already has these tables, you should **mark the baseline as applied** (do not re-run CREATE TABLE on existing tables).

Typical workflow:

- local dev: `npx prisma migrate dev` (on a disposable local DB)
- shared envs: `npx prisma migrate deploy` (apply committed migrations)

Never use `prisma migrate reset` outside of disposable local dev DBs.

---

## 6) Backend migrations (Alembic) and no runtime DDL

The backend previously created/altered tables at startup (see `ai-backend/app/lib/schema.py`).
That behavior should be replaced with Alembic migrations:

- `alembic upgrade head` is the only step that mutates backend-owned schema.
- The app process should **not** `CREATE/ALTER` tables at runtime.

---

## 7) Promoting the first admin (RBAC)

Once `User.role` exists, promote an account to admin:

```sql
UPDATE auth."User"
SET role = 'admin'
WHERE email = 'you@example.com';
```

