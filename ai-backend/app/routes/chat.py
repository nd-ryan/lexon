from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import json
from datetime import date, datetime
from app.lib.security import get_api_key
from app.lib.openai_client import get_openai_client
from app.flow_query import QueryFlow
from app.lib.logging_config import setup_logger

logger = setup_logger("chat-route")


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    
    # Handle Neo4j date/time types
    try:
        # Check if it's a Neo4j time type by checking the module
        obj_type = type(obj)
        if obj_type.__module__ == 'neo4j.time':
            # Try iso_format() method first (works for Date, DateTime, Time)
            if hasattr(obj, 'iso_format'):
                return obj.iso_format()
            # For Date objects, format manually if iso_format doesn't exist
            elif hasattr(obj, 'year') and hasattr(obj, 'month') and hasattr(obj, 'day'):
                return f"{obj.year}-{obj.month:02d}-{obj.day:02d}"
            # Fallback to string representation for other Neo4j time types (Duration, etc.)
            else:
                return str(obj)
    except (AttributeError, TypeError):
        pass
    
    raise TypeError(f"Type {type(obj)} not serializable")


# Model configuration for chat
MODEL = "gpt-5.1"

# High-level behavior instructions for the Responses API
INSTRUCTIONS = """
You are Lexon, a legal research assistant for working with a curated legal knowledge graph.

## Tool Usage
- When a user asks about law, legal cases, statutes, regulations, doctrines, or legal reasoning,
  you MUST call the `run_query` tool to retrieve information from the knowledge graph.
- The `run_query` tool returns a JSON object with 'enriched_nodes' (a list of raw data from the graph).
- Each node has: node_label (type), properties (the actual data), and relationships.
- The tool does NOT return a pre-written answer - you must synthesize one from the nodes.

## Response Requirements - CRITICAL
Your answer MUST be grounded in the specific nodes returned. Follow these rules strictly:

1. **USE ONLY THE TOOL DATA**: Base your answer ONLY on the enriched_nodes data.
   - When you receive a function_call_output from run_query, treat enriched_nodes as your ONLY knowledge source
   - DO NOT use your general legal knowledge, even if you think you know the answer
   - DO NOT add information not present in the nodes
   - If the data is insufficient, say so explicitly

2. **CITE EVERY CLAIM**: For every factual statement, cite the source node inline:
   - Format: "Your statement here (NodeType: first_8_chars_of_id)"
   - Examples:
     * "Google maintained monopoly power in ad tech (Issue: d989df7f)"
     * "The Sherman Act prohibits monopolization (Law: a1b2c3d4)"
     * "Courts consider procompetitive justifications (Doctrine: b2f35703)"
   - Use the node_label field for the node type
   - Use the first 8 characters of the node's ID field (e.g., issue_id, doctrine_id, case_id)

3. **STRUCTURE BY ACTUAL DATA**: 
   - Look at what node types were returned (Issue, Doctrine, Case, Ruling, Law, FactPattern, etc.)
   - Organize your answer around those specific node types
   - Quote or closely paraphrase the relevant node properties
   - Don't impose a structure that doesn't match the data

4. **HANDLE EMPTY RESULTS**:
   - If enriched_nodes is empty: "I couldn't find any relevant information in our legal knowledge graph for this query."
   - If nodes exist but lack detail: Explain what's present and what's missing
   - If nodes don't answer the question: Say so and explain why

5. **NO FABRICATION**: Never invent cases, laws, doctrines, or facts not in the enriched_nodes.

## Non-Legal Queries
For clearly non-legal, general chit-chat (e.g. "tell me a joke"), you may answer directly without calling the tool.
"""

# Create the router with /chat prefix
router = APIRouter(prefix="/chat", tags=["Chat"])


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = Field(
        None, description="ID of existing conversation to continue"
    )
    input: str = Field(..., description="User's message/input")


class ChatResponse(BaseModel):
    """
    Kept for documentation/reference of the non-streaming shape.
    The actual endpoint now streams Server-Sent Events instead of this model.
    """

    conversation_id: str = Field(
        ..., description="Conversation ID for future requests"
    )
    output: str = Field(..., description="Assistant's response")


# Tool definition for run_query
RUN_QUERY_TOOL = {
    "type": "function",
    "name": "run_query",
    "description": (
        "Execute a knowledge graph query to retrieve relevant legal nodes (cases, doctrines, laws, etc.). "
        "Returns a JSON object with 'query' (the executed query) and 'enriched_nodes' (list of nodes with full properties and relationships). "
        "You must analyze the enriched_nodes data to construct your answer."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to execute against the knowledge graph",
            }
        },
        "required": ["query"],
    },
}


def execute_run_query_tool(query: str) -> Dict[str, Any]:
    """
    Execute the run_query tool by calling QueryFlow directly.
    
    Returns the response dict directly containing 'query' and 'enriched_nodes'.
    """
    import asyncio
    
    async def run_flow():
        """Run the async flow steps in sequence."""
        flow = QueryFlow()
        flow.state.query = query
        
        # Execute all flow steps in sequence
        await flow.reason_query()
        await flow.interpret_query()
        await flow.execute_searches()
        await flow.deterministic_traversal()
        response = await flow.gather_enriched_data()
        
        return response
    
    try:
        logger.info(f"Executing run_query tool with query: {query}")
        
        # Run the async flow in the current event loop if available, otherwise create one
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're already in an event loop, we can't use asyncio.run()
                # This shouldn't happen in our case, but handle it defensively
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, run_flow())
                    response_text = future.result()
            else:
                response_text = asyncio.run(run_flow())
        except RuntimeError:
            # No event loop exists, create one
            response_text = asyncio.run(run_flow())
        
        logger.info("run_query tool completed successfully")
        return response_text

    except Exception as e:
        logger.error(f"Error executing run_query tool: {e}", exc_info=True)
        return {"error": f"Failed to execute query: {str(e)}"}


@router.post("")
async def chat(request: ChatRequest, api_key: str = Depends(get_api_key)):
    """
    Chat endpoint using OpenAI Responses API with streaming.

    This endpoint returns a Server-Sent Events (SSE) stream that
    slowly yields the assistant's reply as tokens arrive from OpenAI.

    For now we call the Responses API without tools in streaming mode.
    Once we need tool-calling with streaming, we can extend this to
    handle tool events and feed tool outputs back into the stream.
    """
    try:
        client = get_openai_client()
        model = MODEL

        logger.info(
            f"Chat request - conversation_id: {request.conversation_id}, "
            f"input: {request.input[:100]}..."
        )

        def event_generator():
            """
            Synchronous generator that FastAPI wraps into a StreamingResponse.
            Uses the OpenAI Responses streaming API and forwards text deltas
            as SSE 'data:' events.
            """
            try:
                # --- First streaming pass: let the model decide whether to call tools ---
                stream_params: Dict[str, Any] = {
                    "model": model,
                    "input": request.input,
                    "tools": [RUN_QUERY_TOOL],
                    # Let the model decide when to call the tool
                    "tool_choice": "auto",
                    "instructions": INSTRUCTIONS,
                }
                # For streaming, the SDK expects previous_response_id (not conversation_id)
                # to continue a conversation using the prior response's id.
                if request.conversation_id:
                    stream_params["previous_response_id"] = request.conversation_id

                # Log what we're sending to OpenAI
                logger.info("Opening initial Responses streaming session (with tools)")
                logger.info(f"📤 Initial OpenAI call - model: {model}")
                logger.info(f"📤 Initial OpenAI call - input: {request.input[:200]}...")
                logger.info(f"📤 Initial OpenAI call - instructions (first 500 chars): {INSTRUCTIONS[:500]}...")
                logger.info(f"📤 Initial OpenAI call - tools: {[RUN_QUERY_TOOL['name']]}")
                logger.info(f"📤 Initial OpenAI call - tool_choice: auto")
                if request.conversation_id:
                    logger.info(f"📤 Initial OpenAI call - previous_response_id: {request.conversation_id}")

                tool_arguments: Optional[Dict[str, Any]] = None
                tool_call_id: Optional[str] = None
                # Track which output item the tool call corresponds to
                tool_item_id: Optional[str] = None
                tool_output_index: Optional[int] = None
                conversation_id: Optional[str] = None

                # Use the Responses streaming helper from the Python SDK
                with client.responses.stream(**stream_params) as stream:
                    # Stream text deltas as they come in, and watch for tool calls
                    for event in stream:
                        event_type = getattr(event, "type", None)

                        # Text delta events
                        if event_type == "response.output_text.delta":
                            # According to the docs, delta is the text fragment
                            delta = getattr(event, "delta", "")
                            if not isinstance(delta, str):
                                # Some SDK versions may wrap this; be defensive
                                delta = getattr(delta, "text", "") or ""

                            if delta:
                                payload = {"type": "delta", "content": delta}
                                yield f"data: {json.dumps(payload)}\n\n"

                        # Function-call arguments finished: we now have the full JSON args
                        elif event_type == "response.function_call_arguments.done":
                            # ResponseFunctionCallArgumentsDoneEvent has .arguments and .item_id
                            raw_args = getattr(event, "arguments", "") or ""
                            tool_item_id = getattr(event, "item_id", None)
                            tool_output_index = getattr(event, "output_index", None)
                            logger.info(
                                f"Received function_call_arguments.done (item_id={tool_item_id}) "
                                f"with args: {raw_args[:200]}..."
                            )
                            try:
                                parsed_args = json.loads(raw_args) if raw_args else {}
                            except Exception as parse_err:
                                logger.error(
                                    f"Failed to parse tool arguments JSON: {parse_err}",
                                    exc_info=True,
                                )
                                parsed_args = {}

                            tool_arguments = parsed_args or {}

                        # Completed event: cache the response id and resolve the tool call_id, but don't emit to client yet
                        elif event_type == "response.completed":
                            # Per Responses streaming docs, the completed event
                            # carries the full response object on event.response
                            resp_obj = getattr(event, "response", None)
                            conversation_id = (
                                getattr(resp_obj, "id", None)
                                if resp_obj is not None
                                else None
                            )
                            # If we had a tool call, resolve its call_id from the completed response
                            if tool_arguments is not None and resp_obj is not None:
                                try:
                                    outputs = getattr(resp_obj, "output", []) or []

                                    # Prefer using the recorded output_index
                                    if (
                                        tool_output_index is not None
                                        and 0 <= tool_output_index < len(outputs)
                                    ):
                                        out = outputs[tool_output_index]
                                        if getattr(out, "type", None) == "function_call":
                                            tool_call_id = getattr(out, "call_id", None)

                                    # Fallback: search by item_id matching the tool item id
                                    if tool_call_id is None and tool_item_id is not None:
                                        for out in outputs:
                                            if getattr(out, "type", None) == "function_call" and getattr(
                                                out, "id", None
                                            ) == tool_item_id:
                                                tool_call_id = getattr(out, "call_id", None)
                                                break

                                    logger.info(
                                        f"Resolved tool call: item_id={tool_item_id}, "
                                        f"output_index={tool_output_index}, call_id={tool_call_id}"
                                    )
                                except Exception as resolve_err:
                                    logger.error(
                                        f"Failed to resolve tool call_id from completed response: {resolve_err}",
                                        exc_info=True,
                                    )

                            # Log token usage if available
                            usage_info = ""
                            if resp_obj and hasattr(resp_obj, 'usage'):
                                usage = resp_obj.usage
                                if usage:
                                    input_tokens = getattr(usage, 'input_tokens', 0)
                                    output_tokens = getattr(usage, 'output_tokens', 0)
                                    total_tokens = getattr(usage, 'total_tokens', input_tokens + output_tokens)
                                    usage_info = f" [tokens: {input_tokens} input + {output_tokens} output = {total_tokens} total]"
                            
                            logger.info(
                                f"Initial streaming response.completed - conversation_id={conversation_id}{usage_info}"
                            )

                # --- If a tool call was requested, execute it and run a follow-up stream ---
                if tool_arguments is not None:
                    # Prefer the explicit 'query' argument; if missing/empty,
                    # fall back to the user's original input so the tool
                    # always receives a meaningful question.
                    query = (tool_arguments.get("query") or request.input or "").strip()
                    logger.info(
                        f"Model requested run_query tool with query: {query[:200]}..."
                    )
                    tool_result = execute_run_query_tool(query)
                    
                    # Log a summary of the tool results
                    tool_output_str = json.dumps(tool_result, default=json_serial)
                    tool_output_chars = len(tool_output_str)
                    tool_output_tokens_est = tool_output_chars // 4  # Rough estimate: ~4 chars per token
                    
                    if isinstance(tool_result, dict):
                        enriched_nodes = tool_result.get("enriched_nodes", [])
                        if enriched_nodes:
                            # Count nodes by label
                            node_counts = {}
                            for node in enriched_nodes:
                                label = node.get("node_label", "Unknown")
                                node_counts[label] = node_counts.get(label, 0) + 1
                            breakdown = ", ".join([f"{count} {label}" for label, count in sorted(node_counts.items())])
                            logger.info(f"🔍 Query tool returned {len(enriched_nodes)} nodes: {breakdown} (~{tool_output_tokens_est:,} tokens)")
                        else:
                            logger.info(f"🔍 Query tool returned 0 nodes (empty result) (~{tool_output_tokens_est:,} tokens)")
                    else:
                        logger.info(f"🔍 Query tool result: {str(tool_result)[:200]} (~{tool_output_tokens_est:,} tokens)")

                    # Prepare function_call_output input for the follow-up Responses call.
                    # Per Responses API, call_id and output must be top-level fields.
                    tool_call_output = {
                        "type": "function_call_output",
                        "call_id": tool_call_id,
                        "output": json.dumps(tool_result, default=json_serial),
                    }

                    followup_params: Dict[str, Any] = {
                        "model": model,
                        "input": [tool_call_output],
                        # Continue from the previous response
                        "previous_response_id": conversation_id,
                        # CRITICAL: Re-apply instructions - they are NOT carried forward by previous_response_id
                        "instructions": INSTRUCTIONS,
                    }

                    # Log what we're sending to OpenAI in the follow-up
                    logger.info(
                        "Opening follow-up Responses streaming session with tool output"
                    )
                    logger.info(f"📤 Follow-up OpenAI call - model: {model}")
                    logger.info(f"📤 Follow-up OpenAI call - previous_response_id: {conversation_id}")
                    logger.info(f"📤 Follow-up OpenAI call - instructions: RE-SENT (not carried forward by previous_response_id)")
                    logger.info(f"📤 Follow-up OpenAI call - tools: NONE (no multi-hop)")
                    logger.info(f"📤 Follow-up OpenAI call - tool output (first 1000 chars): {json.dumps(tool_result, default=json_serial)[:1000]}...")

                    with client.responses.stream(**followup_params) as follow_stream:
                        final_conversation_id: Optional[str] = conversation_id

                        for event in follow_stream:
                            event_type = getattr(event, "type", None)

                            if event_type == "response.output_text.delta":
                                delta = getattr(event, "delta", "")
                                if not isinstance(delta, str):
                                    delta = getattr(delta, "text", "") or ""

                                if delta:
                                    payload = {"type": "delta", "content": delta}
                                    yield f"data: {json.dumps(payload)}\n\n"

                            elif event_type == "response.completed":
                                resp_obj = getattr(event, "response", None)
                                final_conversation_id = (
                                    getattr(resp_obj, "id", None)
                                    if resp_obj is not None
                                    else final_conversation_id
                                )
                                
                                # Log token usage if available
                                usage_info = ""
                                if resp_obj and hasattr(resp_obj, 'usage'):
                                    usage = resp_obj.usage
                                    if usage:
                                        input_tokens = getattr(usage, 'input_tokens', 0)
                                        output_tokens = getattr(usage, 'output_tokens', 0)
                                        total_tokens = getattr(usage, 'total_tokens', input_tokens + output_tokens)
                                        usage_info = f" [tokens: {input_tokens} input + {output_tokens} output = {total_tokens} total]"
                                
                                logger.info(
                                    f"Follow-up streaming response.completed - conversation_id={final_conversation_id}{usage_info}"
                                )
                                break

                    # After tool-based follow-up, signal completion once
                    completion_payload = {
                        "type": "completed",
                        "conversation_id": final_conversation_id,
                    }
                    yield f"data: {json.dumps(completion_payload)}\n\n"
                    yield "data: [DONE]\n\n"

                else:
                    # No tool calls were made; we've already streamed all text deltas from
                    # the initial response. Just emit a single completed event for the client.
                    completion_payload = {
                        "type": "completed",
                        "conversation_id": conversation_id,
                    }
                    yield f"data: {json.dumps(completion_payload)}\n\n"
                    yield "data: [DONE]\n\n"

            except Exception as e:
                logger.error(f"Chat streaming error: {e}", exc_info=True)
                error_payload = {
                    "type": "error",
                    "message": "An error occurred while processing your message. Please try again.",
                }
                # Send a final error event; client should display a generic error
                yield f"data: {json.dumps(error_payload)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    except ValueError as e:
        # Configuration error (e.g., missing API key)
        logger.error(f"Configuration error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Chat service is temporarily unavailable. Please try again later.",
        )

    except Exception as e:
        logger.error(f"Chat endpoint error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An error occurred while processing your message. Please try again.",
        )

