from typing import Dict, Any
from crewai.tools import tool
import os
import logging

logger = logging.getLogger(__name__)

try:
    import mammoth  # DOCX text extraction
except Exception:  # pragma: no cover
    mammoth = None  # type: ignore

try:
    import pdfplumber  # PDF text extraction
except Exception:  # pragma: no cover
    pdfplumber = None  # type: ignore


@tool("read_document_tool")
def read_document_tool(file_path: str, filename: str) -> Dict[str, Any]:
    """
    Read a local document and return its text and basic metadata.

    Returns:
      { ok: bool, text?: str, meta?: {...}, error?: str }
    """
    try:
        if not os.path.exists(file_path):
            return {"ok": False, "error": f"File not found: {file_path}"}

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
        logger.exception("read_document_tool failed")
        return {"ok": False, "error": str(e)}


@tool("get_neo4j_schema_tool")
def get_neo4j_schema_tool() -> Dict[str, Any]:
    """
    Retrieve the Neo4j schema via MCP tools.

    Returns:
      { ok: bool, schema?: Any, error?: str }
    """
    try:
        from app.lib.mcp_integration import MCPEnabledAgents, get_mcp_tools
        with MCPEnabledAgents():
            mcp_tools = get_mcp_tools()
            schema_tool = next((t for t in mcp_tools if "schema" in t.name.lower()), None)
            if not schema_tool:
                return {"ok": False, "error": "Schema tool not found via MCP"}
            payload = schema_tool.run({})
            return {"ok": True, "schema": payload}
    except Exception as e:
        logger.error(f"MCP schema retrieval failed: {e}")
        return {"ok": False, "error": f"MCP schema retrieval failed: {e}"}


