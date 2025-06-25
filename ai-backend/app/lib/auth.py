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
            print("❌ JWT_SECRET not configured")
            logger.error("JWT_SECRET not configured")
            raise HTTPException(status_code=500, detail="Server configuration error")
        
        # Debug logging for production
        print(f"🔍 Validating JWT token. Secret length: {len(jwt_secret)}")
        print(f"🔍 Token first 20 chars: {token[:20]}...")
        print(f"🔍 JWT Secret first 10 chars: {jwt_secret[:10]}...")
        
        payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
        
        # Verify token purpose
        if payload.get("purpose") != "stream_access":
            print(f"❌ Invalid token purpose: {payload.get('purpose')}")
            logger.error(f"Invalid token purpose: {payload.get('purpose')}")
            raise HTTPException(status_code=403, detail="Invalid token purpose")
        
        print(f"✅ JWT token validated successfully for user: {payload.get('userId')}")
        logger.info(f"JWT token validated successfully for user: {payload.get('userId')}")
        return payload
        
    except jwt.ExpiredSignatureError:
        print("❌ Expired JWT token used for streaming access")
        logger.warning("Expired JWT token used for streaming access")
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        print(f"❌ Invalid JWT token used for streaming access: {e}")
        print(f"❌ Full token: {token}")
        logger.error(f"Invalid JWT token used for streaming access: {e}")
        logger.error(f"Token: {token[:50]}...")
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        print(f"❌ Unexpected error validating JWT token: {e}")
        logger.error(f"Unexpected error validating JWT token: {e}")
        raise HTTPException(status_code=500, detail="Token validation error")


async def validate_stream_token_async(token: str = Query(...)) -> Dict[str, Any]:
    """
    Async version of validate_stream_token for compatibility with async routes.
    """
    return validate_stream_token(token) 