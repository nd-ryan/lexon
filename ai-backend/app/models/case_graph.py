from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    temp_id: str = Field(..., description="Temporary unique identifier for the node within this graph payload")
    label: str = Field(..., description="Node label/type, e.g., Case, Party, Issue, Law, Doctrine, Fact, Ruling")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary key/value properties for this node")


class GraphEdge(BaseModel):
    from_: str = Field(..., alias="from", description="temp_id of the source node")
    to: str = Field(..., description="temp_id of the target node")
    label: str = Field(..., description="Relationship type, e.g., RELIES_ON, ADDRESSES, RESULTS_IN, RELATES_TO")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Optional relationship properties")

    class Config:
        populate_by_name = True


class CaseGraph(BaseModel):
    case_name: str = Field(..., description="Canonical case name for this graph payload")
    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)


