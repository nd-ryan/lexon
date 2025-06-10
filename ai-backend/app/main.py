from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes.ai import router as ai_router
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="CrewAI Backend", version="1.0.0")

# Configure CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js default port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(ai_router, prefix="/api/ai", tags=["AI"])

@app.get("/")
async def root():
    return {"message": "CrewAI Backend is running!"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}