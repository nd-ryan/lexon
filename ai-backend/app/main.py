from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes.ai import router as ai_router, streaming_router
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="CrewAI Backend", version="1.0.0")

# Configure CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Development
        "https://*.vercel.app",   # All Vercel deployments
        "https://lexon-phi.vercel.app"  # Your actual production domain
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(ai_router, prefix="/api/ai", tags=["AI"])
app.include_router(streaming_router, prefix="/api/ai", tags=["Streaming"])

@app.get("/")
async def root():
    return {"message": "CrewAI Backend is running!"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}