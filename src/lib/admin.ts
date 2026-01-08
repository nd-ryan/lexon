type EnvLike = Record<string, string | undefined>

function normalizeEmail(email: string): string {
  return email.trim().toLowerCase()
}

/**
 * Legacy admin allowlist helper (email-based).
 *
 * This repo now uses RBAC (roles on `auth."User".role`) for authorization.
 * Prefer `hasAtLeastRole()` (UI) and `hasDbAtLeastRole()` (server-side).
 *
 * This file is retained only for backwards compatibility / historical reference.
 *
 * ---
 *
 * Admin emails can be configured in either:
 * - NEXT_PUBLIC_ADMIN_EMAILS: comma/semicolon/newline-separated list (preferred)
 * - NEXT_PUBLIC_ADMIN_EMAIL: single email (legacy, still supported)
 * 
 * Note: For client-side usage, we must access process.env.NEXT_PUBLIC_* directly
 * (not via a parameter) so Next.js can statically replace the values at build time.
 */
export function getAdminEmails(env?: EnvLike): string[] {
  // Access env vars directly for Next.js static replacement to work on client
  const raw = env 
    ? (env.NEXT_PUBLIC_ADMIN_EMAILS ?? env.NEXT_PUBLIC_ADMIN_EMAIL ?? '')
    : (process.env.NEXT_PUBLIC_ADMIN_EMAILS ?? process.env.NEXT_PUBLIC_ADMIN_EMAIL ?? '')
  return raw
    .split(/[,\n;]/g)
    .map((s) => s.trim())
    .filter(Boolean)
    .map(normalizeEmail)
}

export function isAdminEmail(
  email: string | null | undefined,
  env?: EnvLike
): boolean {
  if (!email) return false
  const normalized = normalizeEmail(email)
  const admins = getAdminEmails(env)
  return admins.includes(normalized)
}


