import { NextResponse } from 'next/server'
import { features } from '@/config/features'

/**
 * API endpoint to expose feature flags to the client
 * GET /api/features
 * 
 * Note: Never expose the actual access code here - only whether one is required
 */
export async function GET() {
  return NextResponse.json({
    registrationEnabled: features.registrationEnabled,
    accessCodeRequired: Boolean(features.registrationAccessCode),
  })
}

