from typing import Any, Dict
from crewai.tools import tool
from crewai import LLM
from app.models.case_graph import CaseGraph
from app.lib.mcp_integration import MCPEnabledAgents, get_mcp_tools
import logging
import os
import json

try:
    import mammoth  # DOCX text extraction
except Exception:  # pragma: no cover
    mammoth = None  # type: ignore

try:
    import pdfplumber  # PDF text extraction
except Exception:  # pragma: no cover
    pdfplumber = None  # type: ignore

logger = logging.getLogger(__name__)


@tool("extract_case_data_tool")
def extract_case_data_tool(file_path: str, filename: str) -> Dict[str, Any]:
    """
    Read the local file, retrieve the Neo4j schema via MCP, analyze the document
    with an LLM, and return a JSON object conforming to the CaseGraph schema:

    {
      "case_name": string,
      "nodes": [ {"temp_id": string, "label": string, "properties": {...}} ],
      "edges": [ {"from": string, "to": string, "label": string, "properties": {...}} ]
    }
    """
    logger.info(f"extract_case_data_tool called with file_path='{file_path}', filename='{filename}'")
    print(f"[extract_case_data_tool] file_path={file_path}, filename={filename}")

    # 1) Basic file checks and content extraction
    document_text = ""
    try:
        exists = os.path.exists(file_path)
        size = os.path.getsize(file_path) if exists else -1
        logger.info(f"Input file exists={exists}, size_bytes={size}")
        print(f"[extract_case_data_tool] file exists={exists}, size={size}")
        if not exists:
            raise FileNotFoundError(f"File not found: {file_path}")

        with open(file_path, 'rb') as f:
            header = f.read(8)
        header_hex = header.hex() if header else ""
        logger.info(f"Header hex (first 8 bytes)={header_hex}")
        print(f"[extract_case_data_tool] header_hex={header_hex}")

        ext = os.path.splitext(filename or file_path)[1].lower()
        if ext == ".docx" and mammoth is not None:
            try:
                with open(file_path, 'rb') as f:
                    result = mammoth.extract_raw_text(f)  # type: ignore
                    document_text = (result.value or "").strip()
                    logger.info(f"DOCX text length={len(document_text)}")
            except Exception as e:
                logger.warning(f"DOCX extraction failed: {e}")
        if not document_text and ext == ".pdf" and pdfplumber is not None:
            try:
                with pdfplumber.open(file_path) as pdf:  # type: ignore
                    pages = [p.extract_text() or "" for p in pdf.pages]
                    document_text = "\n\n".join(pages).strip()
                    logger.info(f"PDF text length={len(document_text)}")
            except Exception as e:
                logger.warning(f"PDF extraction failed: {e}")
        if not document_text:
            with open(file_path, 'rb') as f:
                blob = f.read()
            snippet = blob[:4096]
            document_text = f"[BINARY_CONTENT_SNIPPET]\n{snippet!r}"
            logger.info("Falling back to binary snippet content for LLM context")
    except Exception as fe:
        logger.error(f"Failed reading input file: {fe}")
        document_text = ""

    # 2) Retrieve Neo4j schema via MCP
    schema_payload: Any = None
    with MCPEnabledAgents() as mcp_context:
        neo4j_tools = get_mcp_tools()
        logger.info(f"MCP tools available={bool(neo4j_tools)}")
        print(f"[extract_case_data_tool] MCP tools available={bool(neo4j_tools)}")
        if neo4j_tools:
            tool_names = [t.name for t in neo4j_tools]
            logger.info(f"MCP tool names: {tool_names}")
            print(f"[extract_case_data_tool] MCP tool names: {tool_names}")
            schema_tool = next((t for t in neo4j_tools if 'schema' in t.name.lower()), None)
            logger.info(f"Schema tool found={bool(schema_tool)}")
            print(f"[extract_case_data_tool] schema_tool_found={bool(schema_tool)}")
            if schema_tool:
                try:
                    logger.info("Invoking schema tool to retrieve Neo4j schema...")
                    print("[extract_case_data_tool] invoking schema tool...")
                    schema_payload = schema_tool.run({})
                except Exception as se:
                    logger.error(f"Schema retrieval failed: {se}")
                    print(f"[extract_case_data_tool] schema retrieval error: {se}")
                    schema_payload = None

    # 3) Call LLM to extract CaseGraph JSON
    llm = LLM(model="gpt-4.1", temperature=0)
    schema_str = str(schema_payload)[:20000] if schema_payload is not None else ""
    doc_snippet = document_text[:24000] if document_text else ""
    instruction = (
        "You are extracting a knowledge graph from a legal case document.\n"
        "You MUST return only JSON (no markdown, no comments) that conforms to this schema:\n"
        "{\n"
        "  \"case_name\": string,\n"
        "  \"nodes\": [ {\"temp_id\": string, \"label\": string, \"properties\": {}} ],\n"
        "  \"edges\": [ {\"from\": string, \"to\": string, \"label\": string, \"properties\": {}} ]\n"
        "}\n\n"
        "Rules:\n"
        "- Use canonical node labels and relationship types consistent with the Neo4j schema when possible.\n"
        "- temp_id must be unique within this payload.\n"
        "- properties is a flat object of key/value pairs.\n"
        "- For edges, from/to must reference node temp_id values.\n"
        "- Prefer properties that actually appear in the document.\n"
        "- If unsure about exact names, use reasonable, concise keys.\n"
        "- Return ONLY the JSON.\n\n"
        f"Document filename: {filename}\n"
    )
    context_blocks = []
    if schema_str:
        context_blocks.append(f"NEO4J SCHEMA (truncated):\n{schema_str}")
    if doc_snippet:
        context_blocks.append(f"DOCUMENT CONTENT (truncated):\n{doc_snippet}")
    full_prompt = instruction + "\n\n" + "\n\n".join(context_blocks)

    try:
        print("[extract_case_data_tool] Calling LLM for structured extraction...")
        response = llm.call([{ "role": "user", "content": full_prompt }])
        if not response:
            raise ValueError("Empty response from LLM")

        cleaned = str(response).strip()
        if cleaned.startswith("```"):
            lines = cleaned.split('\n')
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        data = json.loads(cleaned)

        try:
            model = CaseGraph.model_validate(data)  # type: ignore[attr-defined]
        except Exception:
            model = CaseGraph(**data)  # type: ignore[call-arg]

        result = model.model_dump(by_alias=True)
        logger.info("Returning CaseGraph payload from LLM")
        return result
    except Exception as e:
        logger.error(f"LLM extraction failed, returning minimal fallback: {e}")
        example = CaseGraph(
            case_name=filename or "Untitled Case",
            nodes=[
                {
                    "temp_id": "case_1",
                    "label": "Case",
                    "properties": {"source_filename": filename}
                }
            ],
            edges=[]
        )
        return example.model_dump(by_alias=True)


