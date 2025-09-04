from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
from app.lib.auth import validate_stream_token_async
from app.flow_import import ImportFlow
from app.lib.security import get_api_key
import logging
import json
from typing import Optional
import os

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(get_api_key)])
streaming_router = APIRouter()  # No API key dependency for streaming endpoints

# Import models from separate module
from app.models.search import (
    QueryRequest
)


@router.get("/property-mappings")
async def get_property_mappings():
    """Return current property mappings loaded from the static file.

    The mappings are continuously updated by the backend after imports.
    Returns a JSON structure with at least `id_properties` and `name_properties`.
    """
    try:
        from app.lib.batch_query_utils import load_property_mappings
        mappings = load_property_mappings()
        return {"success": True, "mappings": mappings}
    except Exception as e:
        logger.error(f"Failed to load property mappings: {e}")
        raise HTTPException(status_code=500, detail="Failed to load property mappings")

@router.get("/node/enriched")
async def get_enriched_node(label: str, id_value: str):
    """Fetch a single enriched node by label and id_value.

    Tries all configured id properties to match id_value and returns the enriched node map
    with relationships, consistent with batch enrichment shape.
    """
    try:
        from app.lib.neo4j_client import neo4j_client
        from app.lib.batch_query_utils import build_single_node_enrichment_query

        if not label or not id_value:
            raise HTTPException(status_code=400, detail="Missing required parameters: label and id_value")

        cypher = build_single_node_enrichment_query(label, id_value)
        result = neo4j_client.execute_query(cypher)

        nodes = []
        for record in result:
            if isinstance(record, dict):
                if 'n' in record:
                    nodes.append(record['n'])
                else:
                    nodes.append(record)

        return {"success": True, "nodes": nodes}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch enriched node: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch enriched node")

@router.post("/import-kg/advanced")
async def import_with_direct_processing(file: UploadFile = File(...)):
    """
    Import and process documents using CrewAI agents with direct Neo4j integration.
    Uses the proven direct Neo4j approach for reliable processing.
    """
    import tempfile
    import os
    
    try:
        file_content = await file.read()
        
        # Create a temporary file to store the document
        with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as temp_file:
            temp_file.write(file_content)
            temp_file_path = temp_file.name
        
        try:
            # Use direct Neo4j approach with ImportFlow
            print(f"📄 Processing document: {file.filename}")
            print(f"Document processing started for: {file.filename}")
            
            # Create and execute import flow
            import_flow = ImportFlow()
            
            # Set file details in flow state before kickoff (structured state management)
            import_flow.state.file_path = temp_file_path
            import_flow.state.filename = file.filename
            
            print("🚀 Starting import flow...")
            result = await import_flow.kickoff_async()
            
            # Extract result
            result_text = result if isinstance(result, str) else str(result)
            
            return {
                "success": True,
                "filename": file.filename,
                "result": result_text,
                "processing_method": "direct_neo4j",
                "message": "Document processed successfully using direct Neo4j integration"
            }
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                
    except Exception as e:
        logger.error(f"Document processing failed: {e}")
        return {
            "success": False,
            "filename": file.filename if file else "unknown",
            "error": str(e),
            "processing_method": "direct_neo4j"
        }

@router.post("/search/crew/stream")
async def enqueue_search_job(request: QueryRequest):
    """
    Accepts a search query, enqueues it as a background job,
    and returns a job ID for the client to use for retrieving results.
    """
    import uuid
    from app.lib.queue import search_queue
    from app.jobs.search_crew_job import run_search_crew

    job_id = str(uuid.uuid4())
    # Set a 10-minute timeout for the job
    search_queue.enqueue(run_search_crew, request.query, job_id, job_timeout="10m")
    
    return {"job_id": job_id}

@streaming_router.get("/search/results/{job_id}")
async def get_search_results(
    job_id: str,
    token_data: dict = Depends(validate_stream_token_async)
):
    """
    A streaming endpoint that listens to a Redis channel for results
    from a background job and streams them to the client.
    Requires valid JWT token for authentication.
    """
    from app.lib.queue import redis_conn
    import asyncio
    
    # Verify the token is for this specific job
    if token_data.get("jobId") != job_id:
        raise HTTPException(status_code=403, detail="Token not valid for this job")
    
    logger.info(f"Starting stream for job {job_id} for user {token_data.get('userId')}")

    async def event_stream():
        pubsub = redis_conn.pubsub()
        channel_name = f"job:{job_id}"
        await asyncio.to_thread(pubsub.subscribe, channel_name)
        
        try:
            while True:
                # Use asyncio.to_thread to run the blocking get_message in a separate thread
                message = await asyncio.to_thread(pubsub.get_message, ignore_subscribe_messages=True, timeout=60.0)
                if message:
                    # Decode message data
                    message_data = message['data'].decode('utf-8')
                    try:
                        data = json.loads(message_data)
                        yield f"data: {json.dumps(data)}\n\n"
                        # Stop listening if the worker signals the end
                        if data.get("type") == "end":
                            # Add a small delay to ensure the final message is fully delivered
                            await asyncio.sleep(0.1)
                            break
                    except json.JSONDecodeError:
                        logger.warning(f"Received non-JSON message on channel {channel_name}: {message_data}")

                # Prevent busy-waiting
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            # This is expected when the client disconnects
            logger.info(f"Client disconnected from job {job_id}")
            raise
        finally:
            # Clean up the subscription
            logger.info(f"Closing pubsub for job {job_id}")
            pubsub.unsubscribe(channel_name)
            pubsub.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/debug/update-properties")
async def debug_update_properties():
    """Debug endpoint to manually trigger property mapping update with AI parsing."""
    try:
        from app.lib.dynamic_document_processor import dynamic_processor
        
        print("🔄 Manual property mapping update triggered...")
        dynamic_processor._update_property_mappings_after_import()
        
        # Load and return the updated mappings
        import json
        import os
        mappings_file = os.path.join(os.path.dirname(__file__), "..", "..", "property_mappings.json")
        
        if os.path.exists(mappings_file):
            with open(mappings_file, 'r') as f:
                mappings = json.load(f)
            
            return {
                "success": True,
                "message": "Property mappings updated with AI parsing",
                "mappings": mappings
            }
        else:
            return {
                "success": False,
                "message": "Property mappings file not found after update"
            }
        
    except Exception as e:
        logger.error(f"Failed to update property mappings: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to update property mappings"
        }

@router.get("/debug/upload-codes/{node_type}")
async def debug_upload_codes(node_type: str):
    """Debug endpoint to check upload_codes for a specific node type."""
    # Convert node type to snake_case for property names
    import re
    snake_case = re.sub(r'(?<!^)(?=[A-Z])', '_', node_type).lower()
    upload_code_prop = f"{snake_case}_upload_code"
    
    try:
        from app.lib.neo4j_client import neo4j_client
        
        # Dynamically determine ID property from schema
        from app.lib.dynamic_document_processor import dynamic_processor
        id_prop = dynamic_processor._get_id_property_from_schema(node_type)
        
        query = f"""
        MATCH (n:{node_type})
        WHERE n.{upload_code_prop} IS NOT NULL
        RETURN n.{upload_code_prop} as upload_code, n.{id_prop} as node_id
        ORDER BY n.{upload_code_prop}
        """
        
        result = neo4j_client.execute_query(query)
        
        upload_codes = {}
        for record in result:
            code = record.get('upload_code')
            node_id = record.get('node_id')
            if code:
                upload_codes[code] = node_id
        
        return {
            "success": True,
            "node_type": node_type,
            "upload_code_property": upload_code_prop,
            "id_property": id_prop,
            "total_with_upload_codes": len(upload_codes),
            "upload_codes": upload_codes
        }
        
    except Exception as e:
        logger.error(f"Failed to check upload codes: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to check {snake_case}_upload_code for {node_type}"
        }

@router.get("/debug/relationships/{from_type}/{to_type}")
async def debug_relationships(from_type: str, to_type: str):
    """Debug endpoint to check relationships between two node types."""
    try:
        from app.lib.neo4j_client import neo4j_client
        
        # Get all relationships between these node types
        query = f"""
        MATCH (a:{from_type})-[r]->(b:{to_type})
        RETURN type(r) as rel_type, count(r) as count
        ORDER BY rel_type
        """
        
        result = neo4j_client.execute_query(query)
        
        relationships = {}
        total_count = 0
        for record in result:
            rel_type = record.get('rel_type')
            count = record.get('count', 0)
            relationships[rel_type] = count
            total_count += count
        
        return {
            "success": True,
            "from_type": from_type,
            "to_type": to_type,
            "total_relationships": total_count,
            "relationship_types": relationships
        }
        
    except Exception as e:
        logger.error(f"Failed to check relationships: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to check relationships between {from_type} and {to_type}"
        }

