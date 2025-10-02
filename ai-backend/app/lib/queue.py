import os
from redis import Redis
from rq import Queue

# Get Redis connection details from environment variables
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

# Establish a connection to Redis
redis_conn = Redis.from_url(redis_url)

# Create RQ queues
search_queue = Queue("search_jobs", connection=redis_conn)
case_extraction_queue = Queue("case_extraction", connection=redis_conn) 