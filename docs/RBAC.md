# Role-based access control (RBAC)

Lexon uses **NextAuth (credentials provider)** for authentication and a **database-stored role** for authorization.

Roles live on `auth."User".role` (Prisma-managed).

## Roles

- **`user`**
  - Can sign in
  - Can view the case list and view individual cases (read-only)
  - Can access chat
- **`editor`**
  - Everything `user` can do
  - Can edit cases
  - Can submit cases to the Knowledge Graph (KG)
- **`developer`**
  - Everything `user` can do
  - Can access API documentation pages (`/api/docs/*`)
- **`admin`**
  - Can access everything (including upload/import/search/admin pages)
  - Can manage users/roles

## Enforcement model

Lexon enforces access in two places:

1) **UI gating (client-side)**
- Navigation items are shown/hidden based on the session role.
- Restricted pages redirect non-authorized users back to `/cases` (or to `/auth/signin` if unauthenticated).

2) **Server-side gating (authoritative)**
- Next.js API routes use `getServerSession()` plus a **DB-backed role check** to ensure the request is still authorized even if the UI is bypassed.
- This avoids trusting potentially stale client JWT role claims.

## Admin user management

Admins can manage users at:

- **UI**: `/admin/users`
- **API**:
  - `GET /api/admin/users` (list users)
  - `PATCH /api/admin/users/:id` (set role)
  - `DELETE /api/admin/users/:id` (delete user)

Guardrails:
- Prevent self-demotion / self-deletion
- Prevent deleting (or demoting) the last remaining admin

## Bootstrapping the first admin

Registration is disabled by default, and new users default to role `user`.

To promote the first admin, run (as a DB admin user):

```sql
UPDATE auth."User"
SET role = 'admin'
WHERE email = 'you@example.com';
```

## Related docs

- `docs/POSTGRES_OWNERSHIP_AND_MIGRATIONS.md` (schemas: `auth` vs `app`)
- `docs/ADMIN_NEO4J_CASE_VIEW.md` (admin-only Neo4j read-only view)
