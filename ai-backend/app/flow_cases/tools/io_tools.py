from typing import Dict, Any
from crewai.tools import tool
import os
import logging
import json

logger = logging.getLogger(__name__)

try:
    import mammoth  # DOCX text extraction
except Exception:  # pragma: no cover
    mammoth = None  # type: ignore

try:
    import pdfplumber  # PDF text extraction
except Exception:  # pragma: no cover
    pdfplumber = None  # type: ignore


def read_document(file_path: str, filename: str) -> Dict[str, Any]:
    """
    Plain function to read a local document and return its text and basic metadata.
    Safe to call directly from code.

    Returns:
      { ok: bool, text?: str, meta?: {...}, error?: str }
    """
    try:
        # Add retry logic for file access in case of timing issues
        import time
        max_retries = 3
        retry_delay = 0.5
        
        for attempt in range(max_retries):
            if os.path.exists(file_path):
                break
            if attempt < max_retries - 1:
                logger.warning(f"File not found on attempt {attempt + 1}, retrying in {retry_delay}s: {file_path}")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                return {"ok": False, "error": f"File not found after {max_retries} attempts: {file_path}"}
        
        ext = os.path.splitext(filename or file_path)[1].lower()
        text: str = ""

        if ext == ".docx" and mammoth is not None:
            try:
                with open(file_path, "rb") as f:
                    result = mammoth.extract_raw_text(f)  # type: ignore
                    text = (result.value or "").strip()
            except Exception as e:
                logger.warning(f"DOCX extraction failed: {e}")

        if not text and ext == ".pdf" and pdfplumber is not None:
            try:
                with pdfplumber.open(file_path) as pdf:  # type: ignore
                    pages = [p.extract_text() or "" for p in pdf.pages]
                    text = "\n\n".join(pages).strip()
            except Exception as e:
                logger.warning(f"PDF extraction failed: {e}")

        if not text:
            # Fallback: read bytes and decode best-effort
            try:
                with open(file_path, "rb") as f:
                    blob = f.read(200_000)
                text = blob.decode("utf-8", errors="replace")
            except Exception as e:
                logger.warning(f"Binary decode fallback failed: {e}")
                text = ""

        return {
            "ok": True,
            "text": text,
            "meta": {
                "filename": filename,
                "extension": ext,
                "size_bytes": os.path.getsize(file_path)
            }
        }
    except Exception as e:
        logger.exception("read_document failed")
        return {"ok": False, "error": str(e)}


@tool("read_document_tool")
def read_document_tool(file_path: str, filename: str) -> Dict[str, Any]:
    """
    CrewAI tool wrapper for reading documents.
    Delegates to read_document() function.
    """
    return read_document(file_path, filename)


def fetch_neo4j_schema() -> Dict[str, Any]:
    """
    Retrieve schema strictly from the local schema.json file.
    This backend treats schema.json as the single source of truth.
    """
    try:
        base_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        path = os.path.abspath(os.path.join(base_dir, "schema.json"))
        if os.path.exists(path):
            with open(path, "r") as f:
                payload = json.load(f)
            return {"ok": True, "schema": payload}
        # If schema.json is not present, return a clear error
        return {"ok": False, "error": "schema.json not found"}
    except Exception as e:
        logger.error(f"MCP schema retrieval failed: {e}")
        return {"ok": False, "error": f"MCP schema retrieval failed: {e}"}


@tool("get_neo4j_schema_tool")
def get_neo4j_schema_tool() -> Dict[str, Any]:
    """
    CrewAI tool-wrapper that delegates to fetch_neo4j_schema.
    """
    return fetch_neo4j_schema()


def fetch_preset_nodes() -> Dict[str, Any]:
    """
    Plain function to fetch preset nodes; safe to call directly from code.
    The decorated CrewAI tool calls this under the hood.
    """
    try:
        print("[get_preset_nodes_tool] start")
        # Load schema to find preset labels and allowed properties
        base_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        path = os.path.abspath(os.path.join(base_dir, "schema.json"))
        if not os.path.exists(path):
            print("[get_preset_nodes_tool] schema.json not found")
            return {"ok": False, "error": "schema.json not found"}

        with open(path, "r") as f:
            schema = json.load(f)

        preset_labels: Dict[str, Dict[str, Any]] = {}
        for node_def in schema if isinstance(schema, list) else []:
            if not isinstance(node_def, dict):
                continue
            if not node_def.get("preset", False):
                continue
            label = node_def.get("label")
            if not isinstance(label, str):
                continue
            props = node_def.get("properties", {}) or {}
            allowed_props: list[str] = []
            for pname, pmeta in props.items():
                if not isinstance(pname, str) or not isinstance(pmeta, dict):
                    continue
                ui = pmeta.get("ui", {}) or {}
                if ui.get("hidden") is True:
                    continue
                if pname.endswith("_embedding") or pname.endswith("_embeddings") or "embedding" in pname:
                    continue
                allowed_props.append(pname)
            if allowed_props:
                preset_labels[label] = {"allowed_props": allowed_props}

        if not preset_labels:
            print("[get_preset_nodes_tool] no preset labels in schema")
            return {"ok": True, "presets": {}}

        # Build Cypher projection per label and query via MCP
        from app.lib.mcp_integration import MCPEnabledAgents, get_mcp_tools
        results: Dict[str, list[dict]] = {}
        with MCPEnabledAgents() as mcp_context:
            tools = get_mcp_tools()
            if not tools:
                print("[get_preset_nodes_tool] MCP tools unavailable")
                return {"ok": False, "error": "MCP tools unavailable"}
            cypher_tool = next((t for t in tools if 'cypher' in t.name.lower()), None)
            if not cypher_tool:
                print("[get_preset_nodes_tool] Cypher tool not found in MCP")
                return {"ok": False, "error": "Cypher tool not found in MCP"}

            for label, meta in preset_labels.items():
                props = meta["allowed_props"]
                projection = ", ".join([f"n.{p} AS {p}" for p in props]) if props else "n"
                query = f"MATCH (n:`{label}`) RETURN {projection}"
                try:
                    print(f"[get_preset_nodes_tool] querying label={label} props={props}")
                    res = cypher_tool.run({"query": query, "params": {}})
                    # Expected result format depends on MCP server; assume list of dict rows
                    if isinstance(res, dict) and "data" in res:
                        rows = res.get("data") or []
                    else:
                        rows = res if isinstance(res, list) else []
                    cleaned_rows: list[dict] = []
                    for r in rows:
                        if isinstance(r, dict):
                            cleaned_rows.append({k: v for k, v in r.items() if k in props})
                    results[label] = cleaned_rows
                    print(f"[get_preset_nodes_tool] got {len(cleaned_rows)} rows for {label}")
                except Exception as e:
                    logger.error(f"Failed to fetch presets for label {label}: {e}")
                    print(f"[get_preset_nodes_tool] error for {label}: {e}")
                    results[label] = []

        print("[get_preset_nodes_tool] done")
        return {"ok": True, "presets": results}
    except Exception as e:
        logger.exception("get_preset_nodes_tool failed")
        print(f"[get_preset_nodes_tool] failed: {e}")
        return {"ok": False, "error": str(e)}


@tool("get_preset_nodes_tool")
def get_preset_nodes_tool() -> Dict[str, Any]:
    """
    Retrieve preset nodes from Neo4j via MCP, based on labels marked preset in schema.json.

    Returns:
      { ok: bool, presets?: { label: [ { properties... } ] }, error?: str }
    Only returns non-hidden, non-embedding properties as per schema.json.
    """
    return fetch_preset_nodes()


