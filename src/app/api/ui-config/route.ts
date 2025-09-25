// This route is deprecated and intentionally left empty to avoid 404 import churn.
export async function GET() {
  return new Response(JSON.stringify({ success: false, error: 'ui-config endpoint removed' }), { status: 410 })
}
