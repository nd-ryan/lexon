from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class GeneratedCypherQuery(BaseModel):
    """A model to hold the generated Cypher query."""
    generated_query: str = Field(..., description="A broader query including related concepts.")

class QueryExecutionResults(BaseModel):
    """Simple model for raw query execution results."""
    raw_results: List[Dict[str, Any]] = Field(..., description="The raw JSON results from the executed Cypher queries.")
    success: bool = Field(True, description="Whether the query execution was successful")

class SearchInsights(BaseModel):
    """Final synthesis model with summary only."""
    summary: str = Field(..., description="A clear, concise summary of the search results in relation to the user's query.")

class FinalSearchResponse(BaseModel):
    """Combined model that includes both execution results and insights for the final task."""
    success: bool = Field(True, description="Whether the search was successful")
    explanation: str = Field(..., description="A clear, concise summary of the search results in relation to the user's query.")
    raw_results: List[Dict[str, Any]] = Field(..., description="The raw JSON results from the executed Cypher queries.")
    cypher_queries: List[str] = Field(..., description="Cypher queries that were executed.")
    query: str = Field(..., description="Original user query")
    execution_time: Optional[float] = Field(None, description="Time taken to execute the search")

# Structured Output Models for Search Results
class StructuredSearchResponse(BaseModel):
    """Simplified structured response for AI Agent search."""
    success: bool = Field(True, description="Indicates if the search was successful")
    explanation: str = Field(..., description="A continuous prose explanation of the search results, drawing insights from the raw data.")
    raw_results: List[Dict[str, Any]] = Field(..., description="The raw JSON results from the executed Cypher queries.")
    cypher_queries: List[str] = Field(..., description="Cypher queries executed by the agent.")
    query: str = Field(..., description="Original user query")
    execution_time: Optional[float] = Field(None, description="Time taken to execute the search")

# Request Models




class QueryRequest(BaseModel):
    query: str
    max_results: Optional[int] = 10

# New models for label/id block structure
class LabelIdBlock(BaseModel):
    """Model for representing a label with its id field and values."""
    label: str = Field(..., description="The Neo4j node label")
    id_field: str = Field(..., description="The field name used as the identifier") 
    id_values: List[str] = Field(..., description="List of identifier values for this label")

class LabelIdQueryResult(BaseModel):
    """Result model for initial query that returns label/id blocks."""
    success: bool = Field(True, description="Whether the query execution was successful")
    label_id_blocks: List[LabelIdBlock] = Field(..., description="List of label/id blocks found")

class EnrichedNodeData(BaseModel):
    """Model for enriched node data with relationships."""
    success: bool = Field(True, description="Whether the batch query execution was successful")
    enriched_results: List[Dict[str, Any]] = Field(..., description="The enriched node data with relationships")
    cypher_queries: List[str] = Field(..., description="Batch queries that were executed")

 