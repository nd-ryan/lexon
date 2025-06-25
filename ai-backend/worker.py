import os
import sys

# Add the parent directory to the Python path to allow for absolute imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from redis import Redis
from rq import Worker
from app.lib.queue import search_queue

# Get Redis connection details from environment variables
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')

if __name__ == '__main__':
    redis_conn = Redis.from_url(redis_url)
    worker = Worker([search_queue], connection=redis_conn, name='search-worker')
    print(f"Starting RQ worker 'search-worker' connected to {redis_url}")
    worker.work() 