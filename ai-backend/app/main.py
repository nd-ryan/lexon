from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes.ai import router as ai_router, streaming_router
from app.routes.cases import router as cases_router
from app.lib.logging_config import configure_root_logging, setup_logger, setup_clean_file_logging
from app.lib.db import engine
from app.lib.schema import ensure_cases_table
import os
from dotenv import load_dotenv
import warnings
# Suppress warnings to keep logs clean everywhere
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*PydanticDeprecatedSince.*")
warnings.filterwarnings("ignore", message=".*Using extra keyword arguments.*")

load_dotenv()

# Set up logging with proper real-time output and clean file logging
configure_root_logging()
setup_clean_file_logging()
logger = setup_logger("fastapi-main")

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
app.include_router(cases_router, prefix="/api/ai", tags=["Cases"])

@app.on_event("startup")
async def startup_event():
    """Log server startup with clean formatting."""
    logger.info("🚀 FastAPI CrewAI Backend server starting up")
    logger.info("✅ Logging configured for real-time output")
    logger.info("📁 Clean logs saved to logs/app.log")
    try:
        ensure_cases_table(engine)
        logger.info("🗄️  Verified cases table in Postgres")
    except Exception as e:
        logger.error(f"Failed ensuring cases table: {e}")

@app.get("/")
async def root():
    return {"message": "CrewAI Backend is running!"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}