from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader
import os

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

# It's more secure to load the API key from an environment variable
API_KEY = os.environ.get("FASTAPI_API_KEY")

if not API_KEY:
    # You could raise an error here, or set a default for development
    print("Warning: FASTAPI_API_KEY environment variable not set. Using a default insecure key.")
    API_KEY = "your_default_insecure_api_key_for_development"
    

async def get_api_key(api_key_header: str = Security(api_key_header)):
    if api_key_header == API_KEY:
        return api_key_header
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key",
        ) 