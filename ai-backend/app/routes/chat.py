from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import json
from app.lib.security import get_api_key
from app.lib.openai_client import get_openai_client, get_responses_model
from app.flow_query import QueryFlow
from app.lib.logging_config import setup_logger

logger = setup_logger("chat-route")

# High-level behavior instructions for the Responses API
INSTRUCTIONS = """
You are Lexon, a legal research assistant for working with a curated legal knowledge graph.

- When a user asks about law, legal cases, statutes, regulations, doctrines, or legal reasoning,
  you MUST call the `run_query` tool to retrieve information from the knowledge graph.
- The `run_query` tool returns STRUCTURED JSON data (not prose), typically including fields
  like `query`, `cases`, `doctrines`, and other legal metadata.
- Your job is to read ONLY that structured JSON and summarize or explain it to answer the
  user’s original question as clearly as possible.
- For legal facts, holdings, reasoning, citations, and similar legal content,
  you MUST base your answer ONLY on the results returned by the `run_query` tool.
- Do NOT invent or supplement legal information from your general model knowledge.
  If the tool result does not contain enough information to answer reliably, say so explicitly
  and explain what is missing.
- For clearly non-legal, general chit-chat (e.g. “tell me a joke”), you may answer directly
  without calling the tool.
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
        "Execute a knowledge graph query to retrieve STRUCTURED JSON data about law, "
        "including legal cases, doctrines, citations, and related metadata. "
        "The output is a JSON object (not natural-language text) with fields such as "
        "`query`, `cases`, and `doctrines`, which you should then summarize for the user."
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

    NOTE: This is currently unused in the streaming loop. Once we
    add full tool-calling support for streaming Responses, this
    function can be integrated there.
    """
    try:
        logger.info(f"Executing run_query tool with query: {query}")

        flow = QueryFlow()
        flow.state.query = query
        flow.kickoff()

        response_text = flow.state.response
        logger.info("run_query tool completed successfully")
        return {"result": response_text}

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
        model = get_responses_model()

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

                logger.info("Opening initial Responses streaming session (with tools)")

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

                            logger.info(
                                f"Initial streaming response.completed - conversation_id={conversation_id}"
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
                    # Log the tool call response to app.log (trimmed for safety)
                    try:
                        logger.info(
                            "run_query tool result: %s",
                            json.dumps(tool_result)[:2000],
                        )
                    except Exception:
                        # Fallback in case tool_result is not JSON-serializable
                        logger.info("run_query tool result (raw): %s", str(tool_result)[:2000])

                    # Prepare function_call_output input for the follow-up Responses call.
                    # Per Responses API, call_id and output must be top-level fields.
                    tool_call_output = {
                        "type": "function_call_output",
                        "call_id": tool_call_id,
                        "output": json.dumps(tool_result),
                    }

                    followup_params: Dict[str, Any] = {
                        "model": model,
                        "input": [tool_call_output],
                        # Continue from the previous response
                        "previous_response_id": conversation_id,
                    }

                    logger.info(
                        "Opening follow-up Responses streaming session with tool output"
                    )

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
                                logger.info(
                                    f"Follow-up streaming response.completed - conversation_id={final_conversation_id}"
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

