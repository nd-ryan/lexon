import { NextResponse } from 'next/server'
import { features } from '@/config/features'

/**
 * API endpoint to expose feature flags to the client
 * GET /api/features
 */
export async function GET() {
  return NextResponse.json({
    registrationEnabled: features.registrationEnabled,
  })
}

