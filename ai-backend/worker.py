import os
import sys

# Suppress CrewAI verbose output BEFORE any CrewAI imports
os.environ.setdefault("CREWAI_VERBOSE", "false")
os.environ.setdefault("CREWAI_LOGS", "false")
os.environ.setdefault("CREWAI_TRACE", "false")

# Suppress warnings before any imports
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*PydanticDeprecatedSince.*")
warnings.filterwarnings("ignore", message=".*Using extra keyword arguments.*")

# Add the parent directory to the Python path to allow for absolute imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import our custom logging setup
from app.lib.logging_config import configure_root_logging, setup_logger, setup_clean_file_logging

# Configure logging FIRST to prevent duplicates and noise
configure_root_logging()
setup_clean_file_logging()
logger = setup_logger("rq-worker")

from redis import Redis
from rq import Worker
from app.lib.queue import search_queue, case_extraction_queue

# Get Redis connection details from environment variables
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')

if __name__ == '__main__':
    redis_conn = Redis.from_url(redis_url)
    # Worker handles both search and case extraction queues
    worker = Worker([search_queue, case_extraction_queue], connection=redis_conn)
    logger.info("🚀 Starting RQ worker handling search_jobs and case_extraction queues")
    logger.info("   Connected to Redis (REDIS_URL set)")
    worker.work() 