from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

# Structured Output Models for Search Results
class SearchResult(BaseModel):
    """Individual search result from Neo4j query"""
    entity_type: str = Field(..., description="Type of entity (Case, Party, Provision, etc.)")
    entity_id: Optional[str] = Field(None, description="Unique identifier for the entity")
    name: Optional[str] = Field(None, description="Name or title of the entity")
    description: Optional[str] = Field(None, description="Brief description of the entity")
    properties: Dict[str, Any] = Field(default_factory=dict, description="All properties from Neo4j node")
    relationships: List[Dict[str, Any]] = Field(default_factory=list, description="Related entities and relationships")
    relevance_score: Optional[float] = Field(None, description="Relevance score for the search query")

class SearchAnalysis(BaseModel):
    """Analysis and insights from the search"""
    query_interpretation: str = Field(..., description="How the AI interpreted the user's query")
    methodology: List[str] = Field(..., description="Steps taken to complete the search")
    key_insights: List[str] = Field(..., description="Key insights derived from the results")
    patterns_identified: List[str] = Field(default_factory=list, description="Patterns found in the data")
    limitations: List[str] = Field(default_factory=list, description="Any limitations in the search results")
    formatted_results: List[str] = Field(..., description="User-friendly formatted results (e.g., bullet points of cases)")
    raw_query_results: List[Dict[str, Any]] = Field(..., description="Raw JSON results from Neo4j queries")

class StructuredSearchResponse(BaseModel):
    """Structured response for AI Agent search with comprehensive data"""
    success: bool = Field(..., description="Whether the search was successful")
    query: str = Field(..., description="Original user query")
    total_results: int = Field(..., description="Total number of results found")
    
    # Core search data
    results: List[SearchResult] = Field(..., description="List of search results")
    cypher_queries: List[str] = Field(..., description="Cypher queries executed")
    
    # AI Analysis
    analysis: SearchAnalysis = Field(..., description="AI analysis of the search results")
    
    # Technical metadata
    execution_time: Optional[float] = Field(None, description="Time taken to execute the search")
    mcp_tools_used: bool = Field(True, description="Whether MCP tools were used")
    agent_reasoning: List[Dict[str, Any]] = Field(default_factory=list, description="Step-by-step agent reasoning")

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