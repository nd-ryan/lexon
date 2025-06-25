import jwt
import os
from fastapi import HTTPException, Query, Depends
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

def validate_stream_token(token: str = Query(...)) -> Dict[str, Any]:
    """
    Validate JWT token for streaming access.
    Returns the token payload if valid, raises HTTPException if invalid.
    """
    try:
        jwt_secret = os.getenv("JWT_SECRET")
        if not jwt_secret:
            logger.error("JWT_SECRET not configured")
            raise HTTPException(status_code=500, detail="Server configuration error")
        
        payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
        
        # Verify token purpose
        if payload.get("purpose") != "stream_access":
            raise HTTPException(status_code=403, detail="Invalid token purpose")
        
        return payload
        
    except jwt.ExpiredSignatureError:
        logger.warning("Expired JWT token used for streaming access")
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid JWT token used for streaming access: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        logger.error(f"Unexpected error validating JWT token: {e}")
        raise HTTPException(status_code=500, detail="Token validation error")


async def validate_stream_token_async(token: str = Query(...)) -> Dict[str, Any]:
    """
    Async version of validate_stream_token for compatibility with async routes.
    """
    return validate_stream_token(token) 