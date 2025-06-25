import os
from redis import Redis
from rq import Queue

# Get Redis connection details from environment variables
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

# Establish a connection to Redis
redis_conn = Redis.from_url(redis_url)

# Create a new RQ queue named 'search_jobs'
search_queue = Queue("search_jobs", connection=redis_conn) 