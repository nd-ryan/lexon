from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel
from typing import Dict, Any
from .crews.case_crew.case_crew import CaseCrew
from .tools.io_tools import read_document_tool, get_neo4j_schema_tool
from app.models.case_graph import CaseGraph
import logging
import json


logger = logging.getLogger(__name__)


class CaseExtractState(BaseModel):
    file_path: str = ""
    filename: str = ""
    case_id: str = ""


class CaseExtractFlow(Flow[CaseExtractState]):
    @start()
    def kickoff(self) -> Dict[str, Any]:
        return {
            "file_path": self.state.file_path,
            "filename": self.state.filename,
            "case_id": self.state.case_id,
            "status": "initialized"
        }

    @listen(kickoff)
    def run_extraction(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        tools = [read_document_tool, get_neo4j_schema_tool]
        crew = CaseCrew(
            file_path=self.state.file_path,
            filename=self.state.filename,
            case_id=self.state.case_id,
            tools=tools
        )
        logger.info(f"Executing case extraction for file: {self.state.filename}")
        raw_result = crew.crew().kickoff()
        logger.info(f"Case extraction completed for: {self.state.filename}")
        # Debug: log the raw_result shape
        try:
            has_p = hasattr(raw_result, 'pydantic') and getattr(raw_result, 'pydantic') is not None
            has_r = hasattr(raw_result, 'raw') and getattr(raw_result, 'raw') is not None
            has_td = hasattr(raw_result, 'to_dict')
            logger.info(f"CrewOutput debug: type={type(raw_result)}, has_pydantic={has_p}, has_raw={has_r}, has_to_dict={has_td}")
        except Exception:
            pass

        # Normalize and return structured output (task enforces output_pydantic)
        try:
            # Prefer CrewAI structured output when available
            if hasattr(raw_result, 'pydantic') and getattr(raw_result, 'pydantic') is not None:
                p = getattr(raw_result, 'pydantic')
                # If Crew already returned a Pydantic model of our type
                if isinstance(p, CaseGraph):
                    return p.model_dump(by_alias=True)
                # If Crew returned some other BaseModel, coerce via dict
                if hasattr(p, 'model_dump'):
                    return p.model_dump()  # type: ignore[attr-defined]
                # If Crew returned a dict-like structure
                if isinstance(p, dict):
                    return p

            # Next try a dict conversion
            if hasattr(raw_result, 'to_dict'):
                payload = raw_result.to_dict()  # type: ignore[attr-defined]
            elif isinstance(raw_result, dict):
                payload = raw_result
            elif hasattr(raw_result, 'raw') and getattr(raw_result, 'raw') is not None:
                raw = getattr(raw_result, 'raw')
                if hasattr(raw, 'model_dump'):
                    payload = raw.model_dump()  # type: ignore[attr-defined]
                elif isinstance(raw, str):
                    payload = json.loads(raw)
                else:
                    payload = raw
            elif isinstance(raw_result, str):
                payload = json.loads(raw_result)
            else:
                # Last resort: dump to string then parse if possible
                payload = json.loads(str(raw_result))

            # Rely on task-level output_pydantic; return payload as-is
            return payload
        except Exception as e:
            logger.error(f"Structured output validation failed: {e}")
            raise


