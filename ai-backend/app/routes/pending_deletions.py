"""API routes for managing pending KG deletion requests."""

import os
from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.orm import Session

from app.lib.db import get_db
from app.lib.pending_deletions_repo import pending_deletions_repo
from app.lib.logging_config import setup_logger


logger = setup_logger("pending-deletions-route")
router = APIRouter(prefix="/pending-deletions")


def verify_api_key(request: Request):
    """Verify X-API-Key header."""
    api_key = request.headers.get("X-API-Key")
    expected = os.getenv("FASTAPI_API_KEY")
    if not api_key or api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True


def get_user_id_from_header(request: Request) -> str:
    """Extract user ID from X-User-Id header."""
    return request.headers.get("X-User-Id", "unknown")


@router.get("")
def list_pending_deletions(
    status: str = None,
    request: Request = None,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key),
):
    """List pending deletion requests, optionally filtered by status."""
    items = pending_deletions_repo.list_pending(db.connection(), status=status)
    # Convert UUIDs to strings for JSON serialization
    for item in items:
        if "id" in item:
            item["id"] = str(item["id"])
        if "case_id" in item:
            item["case_id"] = str(item["case_id"])
    return {"success": True, "items": items}


@router.post("/{request_id}/approve")
def approve_deletion(
    request_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key),
):
    """Approve a deletion request - deletes the node from Neo4j."""
    user_id = get_user_id_from_header(request)
    
    # Get the deletion request
    deletion_req = pending_deletions_repo.get_by_id(db.connection(), request_id)
    if not deletion_req:
        raise HTTPException(404, "Deletion request not found")
    
    if deletion_req.get("status") != "pending":
        raise HTTPException(400, "Deletion request is not pending")
    
    # Delete from Neo4j
    try:
        from app.lib.neo4j_uploader import Neo4jUploader, get_id_prop_for_label
        from app.lib.neo4j_client import neo4j_client
        import json
        
        # Load schema
        schema_path = os.path.join(os.path.dirname(__file__), "..", "..", "schema_v3.json")
        with open(schema_path, "r") as f:
            schema = json.load(f)
        
        uploader = Neo4jUploader(schema, neo4j_client)
        success = uploader.delete_node(
            deletion_req["node_label"],
            deletion_req["node_id"]
        )
        
        if not success:
            raise HTTPException(500, "Failed to delete node from Neo4j")
        
        # Mark as approved
        pending_deletions_repo.approve(db.connection(), request_id, user_id)
        db.commit()
        
        logger.info(f"Approved deletion of {deletion_req['node_label']}:{deletion_req['node_id']} by {user_id}")
        return {"success": True}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to approve deletion {request_id}")
        db.rollback()
        raise HTTPException(500, f"Failed to delete node: {str(e)}")


@router.post("/{request_id}/reject")
def reject_deletion(
    request_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key),
):
    """Reject a deletion request."""
    user_id = get_user_id_from_header(request)
    
    # Get the deletion request
    deletion_req = pending_deletions_repo.get_by_id(db.connection(), request_id)
    if not deletion_req:
        raise HTTPException(404, "Deletion request not found")
    
    if deletion_req.get("status") != "pending":
        raise HTTPException(400, "Deletion request is not pending")
    
    pending_deletions_repo.reject(db.connection(), request_id, user_id)
    db.commit()
    
    logger.info(f"Rejected deletion of {deletion_req['node_label']}:{deletion_req['node_id']} by {user_id}")
    return {"success": True}
