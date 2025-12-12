from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes.ai import router as ai_router, streaming_router
from app.routes.cases import router as cases_router
from app.routes.kg import router as kg_router
from app.routes.graph_events import router as graph_events_router
from app.routes.shared_nodes import router as shared_nodes_router
from app.routes.query import router as query_router
from app.routes.chat import router as chat_router
from app.routes.eval import router as eval_router
from app.lib.logging_config import configure_root_logging, setup_logger, setup_clean_file_logging
from app.lib.db import engine
from app.lib.schema import ensure_all_tables
import os
from dotenv import load_dotenv
import warnings
from contextlib import asynccontextmanager
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan handler to run startup/shutdown tasks without deprecated on_event."""
    # Startup
    logger.info("🚀 FastAPI CrewAI Backend server starting up")
    logger.info("✅ Logging configured for real-time output")
    logger.info("📁 Clean logs saved to logs/app.log")
    try:
        ensure_all_tables(engine)
        logger.info("🗄️  Verified all database tables in Postgres")
    except Exception as e:
        logger.error(f"Failed ensuring database tables: {e}")

    yield
    # Shutdown (optional)

app = FastAPI(title="CrewAI Backend", version="1.0.0", lifespan=lifespan)

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
app.include_router(kg_router, prefix="/api/ai", tags=["KG"])
app.include_router(graph_events_router, prefix="/api/ai", tags=["Graph Events"])
app.include_router(shared_nodes_router, prefix="/api/ai", tags=["Shared Nodes"])
app.include_router(query_router, prefix="/api/v1", tags=["Query"])
app.include_router(chat_router, prefix="/api/v1", tags=["Chat"])
app.include_router(eval_router, prefix="/api/v1", tags=["Evaluation"])

"""Startup handled via lifespan above; deprecated on_event removed."""

@app.get("/")
async def root():
    return {"message": "CrewAI Backend is running!"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}