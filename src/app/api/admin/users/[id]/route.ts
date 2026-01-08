import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'
import { hasDbAtLeastRole, type Role } from '@/lib/rbac'
import { prisma } from '@/lib/prisma'

const ROLES: readonly Role[] = ['user', 'editor', 'developer', 'admin'] as const

function isValidRole(value: unknown): value is Role {
  return typeof value === 'string' && (ROLES as readonly string[]).includes(value)
}

async function countAdmins(): Promise<number> {
  return prisma.user.count({ where: { role: 'admin' as any } })
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const isAdmin = await hasDbAtLeastRole(session, 'admin')
  if (!isAdmin.ok) return NextResponse.json({ error: 'Forbidden' }, { status: 403 })

  const { id } = await params
  const body = await req.json().catch(() => ({}))
  const nextRole = body?.role
  if (!isValidRole(nextRole)) {
    return NextResponse.json({ error: 'Invalid role' }, { status: 400 })
  }

  // Prevent self-demotion (easy footgun).
  if (session.user.id === id && nextRole !== 'admin') {
    return NextResponse.json({ error: 'Cannot change your own role' }, { status: 400 })
  }

  const current = await prisma.user.findUnique({
    where: { id },
    select: { id: true, role: true },
  })
  if (!current) return NextResponse.json({ error: 'User not found' }, { status: 404 })

  // Prevent removing the last admin.
  if ((current.role as any) === 'admin' && nextRole !== 'admin') {
    const admins = await countAdmins()
    if (admins <= 1) {
      return NextResponse.json({ error: 'Cannot remove the last admin' }, { status: 400 })
    }
  }

  const updated = await prisma.user.update({
    where: { id },
    data: { role: nextRole as any },
    select: { id: true, email: true, name: true, role: true, updatedAt: true },
  })

  return NextResponse.json({ success: true, user: updated })
}

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const isAdmin = await hasDbAtLeastRole(session, 'admin')
  if (!isAdmin.ok) return NextResponse.json({ error: 'Forbidden' }, { status: 403 })

  const { id } = await params

  // Prevent deleting yourself.
  if (session.user.id === id) {
    return NextResponse.json({ error: 'Cannot delete your own user' }, { status: 400 })
  }

  const target = await prisma.user.findUnique({
    where: { id },
    select: { id: true, role: true },
  })
  if (!target) return NextResponse.json({ error: 'User not found' }, { status: 404 })

  // Prevent deleting the last admin.
  if ((target.role as any) === 'admin') {
    const admins = await countAdmins()
    if (admins <= 1) {
      return NextResponse.json({ error: 'Cannot delete the last admin' }, { status: 400 })
    }
  }

  await prisma.user.delete({ where: { id } })
  return NextResponse.json({ success: true })
}

