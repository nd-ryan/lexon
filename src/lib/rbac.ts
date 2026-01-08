import type { Session } from 'next-auth'
import { prisma } from '@/lib/prisma'

export type Role = 'user' | 'editor' | 'developer' | 'admin'

const ROLE_ORDER: readonly Role[] = ['user', 'editor', 'developer', 'admin'] as const

export function hasAtLeastRole(
  actual: Role | null | undefined,
  required: Role
): boolean {
  if (!actual) return false
  const a = ROLE_ORDER.indexOf(actual)
  const r = ROLE_ORDER.indexOf(required)
  if (a === -1 || r === -1) return false
  return a >= r
}

/**
 * Authoritative role lookup (DB-backed).
 * Do not rely solely on JWT/session role for authorization checks, because it
 * can be stale after an admin changes a user role.
 */
export async function getDbRoleForUserId(userId: string): Promise<Role | null> {
  const user = await prisma.user.findUnique({
    where: { id: userId },
    select: { role: true },
  })
  return (user?.role as Role | undefined) ?? null
}

export async function hasDbAtLeastRole(
  session: Session | null,
  required: Role
): Promise<{ ok: boolean; role: Role | null }> {
  const userId = session?.user?.id
  if (!userId) return { ok: false, role: null }
  const role = await getDbRoleForUserId(userId)
  return { ok: hasAtLeastRole(role, required), role }
}

