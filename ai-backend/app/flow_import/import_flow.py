from crewai.flow.flow import Flow, listen, start
from .crews.import_crew.import_crew import ImportCrew
from .tools.document_processing_tool import process_document_tool
from .tools.embeddings_tool import generate_embeddings_tool
from typing import Dict, Any
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)


class ImportState(BaseModel):
    """
    Pydantic model for structured state management in ImportFlow.
    """
    file_path: str = ""
    filename: str = ""


class ImportFlow(Flow[ImportState]):
    """
    Flow for handling document imports into the Neo4j knowledge graph.
    
    This flow orchestrates the document processing using the ImportCrew.
    """

    @start()
    def import_kickoff(self) -> Dict[str, Any]:
        """
        Initialize the import flow with file details from flow state.
        The file_path and filename should be set in state before calling kickoff().
        
        Returns:
            Dict containing the file details and initialization status
        """
        # Get file details from state (should be set before kickoff)
        file_path = self.state.file_path
        filename = self.state.filename
        
        logger.info(f"Starting import flow for file: {filename}")
        
        return {
            "file_path": file_path,
            "filename": filename,
            "status": "initialized"
        }

    @listen(import_kickoff)
    def execute_import(self, context: Dict[str, Any]) -> str:
        """
        Execute the document import using the ImportCrew.
        
        Args:
            context: Context from the previous step containing file details
            
        Returns:
            str: The import results and processing report
        """
        # Get data from flow state (CrewAI Flows pattern)
        file_path = self.state.file_path
        filename = self.state.filename
        
        logger.info(f"Executing import crew for file: {filename}")
        
        # Prepare tools for the import crew
        tools = [process_document_tool, generate_embeddings_tool]
        
        # Create and run the import crew
        import_crew = ImportCrew(
            file_path=file_path,
            filename=filename,
            tools=tools
        )
        
        # Execute the crew and get results
        result = import_crew.crew().kickoff()
        
        logger.info(f"Import crew execution completed for file: {filename}")
        return result


# Factory function for backward compatibility
def create_import_flow() -> ImportFlow:
    """
    Factory function to create an ImportFlow instance.
    
    Returns:
        ImportFlow: A new import flow instance
    """
    return ImportFlow() 