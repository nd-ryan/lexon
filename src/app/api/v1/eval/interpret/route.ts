import { getServerSession } from 'next-auth/next'
import { NextRequest, NextResponse } from "next/server";
import { authOptions } from "@/lib/auth";

export async function POST(request: NextRequest) {
  // Check authentication - only admin users can access
  const session = await getServerSession(authOptions);
  const adminEmail = process.env.NEXT_PUBLIC_ADMIN_EMAIL;
  
  if (!session || !session.user || !adminEmail || session.user.email !== adminEmail) {
    return NextResponse.json(
      { detail: "Unauthorized. Admin access required." },
      { status: 401 }
    );
  }

  try {
    const body = await request.json();
    
    // Get backend URL and API key from environment
    const backendUrl = process.env.AI_BACKEND_URL || "http://localhost:8000";
    const apiKey = process.env.FASTAPI_API_KEY || "";

    if (!apiKey) {
      console.error("FASTAPI_API_KEY environment variable not set");
      return NextResponse.json(
        { detail: "Server configuration error" },
        { status: 500 }
      );
    }

    // Proxy request to Python backend with API key
    const response = await fetch(`${backendUrl}/api/v1/eval/interpret`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": apiKey,
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        {
          detail: errorData.detail || "Eval backend error",
          statusText: response.statusText,
        },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error("Eval proxy error:", error);
    return NextResponse.json(
      { detail: "Failed to process eval request" },
      { status: 500 }
    );
  }
}

