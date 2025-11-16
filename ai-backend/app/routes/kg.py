import os
import logging
from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.orm import Session

from app.lib.db import get_db
from app.lib.case_repo import case_repo
from app.flow_kg import create_flow
from app.lib.property_filter import filter_case_data
from app.lib.logging_config import setup_logger


logger = setup_logger("kg-route")
router = APIRouter(prefix="/kg")


def verify_bearer(request: Request):
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    token = auth.replace("Bearer ", "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    expected = os.getenv("API_TOKEN") or os.getenv("FASTAPI_API_KEY")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="Invalid token")
    return True


@router.post("/submit")
async def submit_to_kg(payload: dict, request: Request, db: Session = Depends(get_db), _: bool = Depends(verify_bearer)):
    try:
        case_id = payload.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            logger.error("KG submit: missing case_id in request body")
            return {"success": False}

        rec = case_repo.get_case(db.connection(), case_id)
        if not rec:
            logger.error(f"KG submit: case not found: {case_id}")
            return {"success": False}

        data = rec.get("extracted") or {}
        # Ensure we don't pass hidden props if filter is used elsewhere
        try:
            data = filter_case_data(data)
        except Exception:
            pass

        # Run KG Flow transformation
        flow = create_flow()
        flow.state.payload = data
        # Use kickoff_async() since we're already in an async context (FastAPI event loop)
        result = await flow.kickoff_async()
        
        # Upload transformed data to Neo4j
        try:
            from app.lib.neo4j_uploader import Neo4jUploader
            from app.lib.neo4j_client import neo4j_client
            from app.lib.property_filter import prepare_for_postgres_save, add_temp_ids
            
            logger.info(f"Uploading case {case_id} to Neo4j")
            uploader = Neo4jUploader(flow.state.schema_payload, neo4j_client)
            updated_data = uploader.upload_graph_data(
                result.get("nodes", []),
                result.get("edges", [])
            )
            
            # Add temp_id back to nodes (was removed before Neo4j upload, needed for Postgres)
            updated_data = add_temp_ids(updated_data)
            
            # Save updated data back to Postgres with Neo4j-generated _ids
            cleaned = prepare_for_postgres_save(updated_data)
            case_repo.update_case(db.connection(), case_id, cleaned, "kg-upload")
            db.commit()
            
            nodes = len(updated_data.get("nodes", []))
            edges = len(updated_data.get("edges", []))
            logger.info(f"KG submit complete for case {case_id}: {nodes} nodes, {edges} edges uploaded to Neo4j and saved to Postgres")
            return {"success": True, "nodes": nodes, "edges": edges}
            
        except Exception as neo4j_error:
            logger.exception(f"Neo4j upload failed for case {case_id}")
            # Don't save to Postgres if Neo4j upload failed
            db.rollback()
            return {"success": False, "error": "Neo4j upload failed"}
            
    except Exception as e:
        logger.exception("KG submit failed")
        db.rollback()
        # Don't leak details to frontend; return generic 200 with success false
        return {"success": False}


