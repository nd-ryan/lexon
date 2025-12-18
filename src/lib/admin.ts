type EnvLike = Record<string, string | undefined>

function normalizeEmail(email: string): string {
  return email.trim().toLowerCase()
}

/**
 * Admin emails can be configured in either:
 * - NEXT_PUBLIC_ADMIN_EMAILS: comma/semicolon/newline-separated list (preferred)
 * - NEXT_PUBLIC_ADMIN_EMAIL: single email (legacy, still supported)
 */
export function getAdminEmails(env: EnvLike = process.env): string[] {
  const raw = env.NEXT_PUBLIC_ADMIN_EMAILS ?? env.NEXT_PUBLIC_ADMIN_EMAIL ?? ''
  return raw
    .split(/[,\n;]/g)
    .map((s) => s.trim())
    .filter(Boolean)
    .map(normalizeEmail)
}

export function isAdminEmail(
  email: string | null | undefined,
  env: EnvLike = process.env
): boolean {
  if (!email) return false
  const normalized = normalizeEmail(email)
  const admins = getAdminEmails(env)
  return admins.includes(normalized)
}


