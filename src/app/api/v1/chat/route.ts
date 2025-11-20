import { getServerSession } from 'next-auth/next'
import { NextRequest, NextResponse } from "next/server";
import { authOptions } from "@/lib/auth";

export async function POST(request: NextRequest) {
  // Check authentication - only logged in users can access
  const session = await getServerSession(authOptions);
  
  if (!session || !session.user) {
    return NextResponse.json(
      { detail: "Unauthorized. Please sign in to use chat." },
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
    const response = await fetch(`${backendUrl}/api/v1/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": apiKey,
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errorText = await response.text().catch(() => "");
      return NextResponse.json(
        {
          detail: "Chat backend error",
          statusText: response.statusText,
          body: errorText,
        },
        { status: response.status }
      );
    }

    // Pass the SSE stream through to the client
    return new Response(response.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
      },
    });
  } catch (error) {
    console.error("Chat proxy error:", error);
    return NextResponse.json(
      { detail: "Failed to process chat request" },
      { status: 500 }
    );
  }
}

