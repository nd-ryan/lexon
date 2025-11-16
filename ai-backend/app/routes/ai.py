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


@router.get("/schema")
async def get_schema():
    """Return schema from static file if present; fall back to MCP.

    Returns a JSON payload: { success: bool, schema?: Any, error?: str }
    """
    try:
        # Try static schema first
        import os, json
        base_dir = os.path.join(os.path.dirname(__file__), "..", "..")
        path = os.path.abspath(os.path.join(base_dir, "schema_v3.json"))
        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
            return {"success": True, "schema": data, "source": "static"}

        # Fallback to MCP
        from app.lib.mcp_integration import fetch_neo4j_schema_via_mcp
        schema = fetch_neo4j_schema_via_mcp()
        return {"success": True, "schema": schema, "source": "mcp"}
    except Exception as e:
        logger.error(f"Failed to fetch schema: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ui-config")
async def get_ui_config():
    """Deprecated: UI config is embedded in schema.properties now."""
    raise HTTPException(status_code=410, detail="ui-config endpoint removed; use /api/ai/schema")


@router.get("/display-overrides")
async def get_display_overrides():
    """Return display overrides derived from schema_v3.json."""
    try:
        from app.lib.schema_runtime import derive_display_overrides_from_schema
        overrides = derive_display_overrides_from_schema()
        return {"success": True, "overrides": overrides, "source": "schema_v3.json"}
    except Exception as e:
        logger.error(f"Failed to derive display overrides: {e}")
        raise HTTPException(status_code=500, detail="Failed to derive display overrides")


@router.get("/property-mappings")
async def get_property_mappings():
    """Return minimal property mappings derived from schema_v3.json."""
    try:
        from app.lib.schema_runtime import derive_simple_mappings_from_schema
        mappings = derive_simple_mappings_from_schema()
        return {"success": True, "mappings": mappings, "source": "schema_v3.json"}
    except Exception as e:
        logger.error(f"Failed to derive property mappings: {e}")
        raise HTTPException(status_code=500, detail="Failed to derive property mappings")

@router.get("/catalog/{label}")
async def get_catalog_nodes(label: str):
    """Fetch all nodes of a specific label from Neo4j catalog.
    
    Used for selecting existing catalog nodes (where case_unique=false).
    For Forum: includes related Jurisdiction data.
    Filters out hidden properties (like embeddings) based on schema.
    
    If Neo4j is not available, returns empty list gracefully.
    """
    try:
        from app.lib.neo4j_client import neo4j_client
        from app.lib.schema_runtime import load_schema_payload
        
        # Get schema to determine which properties to filter
        schema = load_schema_payload()
        
        def filter_properties(properties: dict, node_label: str) -> dict:
            """Filter out hidden properties except _id fields based on schema."""
            if not schema or not isinstance(schema, list):
                return properties
            
            # Find the schema definition for this label
            label_schema = next((s for s in schema if s.get('label') == node_label), None)
            if not label_schema:
                return properties
            
            schema_props = label_schema.get('properties', {})
            if not isinstance(schema_props, dict):
                return properties
            
            # Filter properties
            filtered = {}
            for key, value in properties.items():
                prop_def = schema_props.get(key, {})
                if not isinstance(prop_def, dict):
                    # No schema definition, include it
                    filtered[key] = value
                    continue
                
                ui_config = prop_def.get('ui', {})
                is_hidden = ui_config.get('hidden', False)
                
                # Include if not hidden, or if it's an _id field (even if hidden)
                if not is_hidden or key.endswith('_id'):
                    filtered[key] = value
            
            return filtered
        
        nodes = []
        
        if label == "Forum":
            # Fetch Forums WITH their Jurisdictions
            query = """
            MATCH (f:Forum)-[:PART_OF]->(j:Jurisdiction)
            RETURN f, j
            LIMIT 1000
            """
            result = neo4j_client.execute_query(query)
            
            for record in result:
                forum_data = record.get('f', {})
                jurisdiction_data = record.get('j', {})
                
                # Create enriched Forum node with embedded Jurisdiction info
                forum_id = forum_data.get('forum_id') or forum_data.get('id') or str(id(forum_data))
                jurisdiction_id = jurisdiction_data.get('jurisdiction_id') or jurisdiction_data.get('id') or str(id(jurisdiction_data))
                
                nodes.append({
                    'temp_id': str(forum_id),
                    'label': 'Forum',
                    'properties': filter_properties(forum_data, 'Forum'),
                    'is_existing': True,
                    'related': {
                        'jurisdiction': {
                            'temp_id': str(jurisdiction_id),
                            'label': 'Jurisdiction',
                            'properties': filter_properties(jurisdiction_data, 'Jurisdiction'),
                            'is_existing': True
                        }
                    }
                })
        else:
            # For other catalog types, just fetch the nodes
            query = f"MATCH (n:`{label}`) RETURN n LIMIT 1000"
            result = neo4j_client.execute_query(query)
            
            # Map label names to their ID property names (for special cases)
            id_property_map = {
                'ReliefType': 'relief_type_id',
                'Jurisdiction': 'jurisdiction_id',
                'FactPattern': 'fact_pattern_id',
                'Domain': 'domain_id',
            }
            
            for record in result:
                node_data = record.get('n', {})
                # Try different ID properties with special handling for compound names
                id_property = id_property_map.get(label, f'{label.lower()}_id')
                temp_id = (
                    node_data.get(id_property) or 
                    node_data.get(f'{label.lower()}_id') or 
                    node_data.get('id') or 
                    str(id(node_data))
                )
                
                nodes.append({
                    'temp_id': str(temp_id),
                    'label': label,
                    'properties': filter_properties(node_data, label),
                    'is_existing': True
                })
        
        return {"success": True, "nodes": nodes}
    except Exception as e:
        logger.warning(f"Could not fetch catalog nodes for {label} (Neo4j may not be available): {e}")
        # Return empty catalog gracefully instead of 500 error
        # This allows the app to work without Neo4j catalog
        return {"success": True, "nodes": [], "warning": "Catalog unavailable"}

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

