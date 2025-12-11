"""API routes for viewing graph event audit logs."""

import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Query
from sqlalchemy.orm import Session

from app.lib.db import get_db
from app.lib.graph_events_repo import graph_events_repo
from app.lib.logging_config import setup_logger


logger = setup_logger("graph-events-route")
router = APIRouter(prefix="/graph-events")


def verify_api_key(request: Request):
    """Verify X-API-Key header."""
    api_key = request.headers.get("X-API-Key")
    expected = os.getenv("FASTAPI_API_KEY")
    if not api_key or api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True


@router.get("")
def list_events(
    case_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key),
):
    """List graph events with optional filters."""
    items = graph_events_repo.list_events(
        conn=db.connection(),
        case_id=case_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        limit=limit,
        offset=offset,
    )
    
    # Convert UUIDs to strings for JSON serialization
    for item in items:
        if "id" in item:
            item["id"] = str(item["id"])
        if "case_id" in item:
            item["case_id"] = str(item["case_id"])
        if "created_at" in item and item["created_at"]:
            item["created_at"] = item["created_at"].isoformat()
    
    return {"success": True, "items": items}


@router.get("/stats")
def get_stats(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key),
):
    """Get event statistics."""
    stats = graph_events_repo.get_event_stats(db.connection())
    return {"success": True, "stats": stats}


@router.get("/case/{case_id}")
def get_case_events(
    case_id: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key),
):
    """Get all events for a specific case."""
    items = graph_events_repo.get_events_for_case(db.connection(), case_id)
    
    # Convert UUIDs to strings for JSON serialization
    for item in items:
        if "id" in item:
            item["id"] = str(item["id"])
        if "case_id" in item:
            item["case_id"] = str(item["case_id"])
        if "created_at" in item and item["created_at"]:
            item["created_at"] = item["created_at"].isoformat()
    
    return {"success": True, "items": items}
