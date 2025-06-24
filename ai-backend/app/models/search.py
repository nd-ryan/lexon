from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class GeneratedCypherQueries(BaseModel):
    """A model to hold the three generated Cypher queries."""
    primary_query: str = Field(..., description="The most direct query to answer the user's request.")
    alternative_query: str = Field(..., description="A broader query including related concepts.")
    fallback_query: str = Field(..., description="A simpler query to run if the others fail or return no results.")

# Structured Output Models for Search Results
class StructuredSearchResponse(BaseModel):
    """Simplified structured response for AI Agent search."""
    explanation: str = Field(..., description="A continuous prose explanation of the search results, drawing insights from the raw data.")
    raw_results: List[Dict[str, Any]] = Field(..., description="The raw JSON results from the executed Cypher queries.")
    cypher_queries: List[str] = Field(..., description="Cypher queries executed by the agent.")
    query: str = Field(..., description="Original user query")
    execution_time: Optional[float] = Field(None, description="Time taken to execute the search")

# Request Models
class SearchRequest(BaseModel):
    query: str

class SearchResponse(BaseModel):
    cypher_query: str
    results: List[Dict[str, Any]]
    count: int

class SimilaritySearchRequest(BaseModel):
    query: str
    limit: Optional[int] = 5

class ResearchRequest(BaseModel):
    topic: str

class EmbeddingsRequest(BaseModel):
    case_ids: List[str]

class CaseAnalysisRequest(BaseModel):
    case_id: str

class PatternAnalysisRequest(BaseModel):
    entity_type: str

class QueryRequest(BaseModel):
    query: str
    max_results: Optional[int] = 10

class DocumentRequest(BaseModel):
    content: str
    document_type: Optional[str] = "legal"

class CrewResponse(BaseModel):
    result: str
    success: bool
    mcp_tools_used: bool = False
    agent_steps: Optional[List[Dict[str, Any]]] = None 