"""
Build structured views of case data based on view configuration.
"""
import json
import os
from typing import Any, Dict, List, Optional


def load_views_config() -> Dict[str, Any]:
    """Load views configuration from views_v3.json"""
    base_dir = os.path.join(os.path.dirname(__file__), "..", "..")
    path = os.path.abspath(os.path.join(base_dir, "views_v3.json"))
    if not os.path.exists(path):
        raise FileNotFoundError(f"views_v3.json not found at {path}")
    with open(path, "r") as f:
        return json.load(f)


class CaseViewBuilder:
    """Build structured views of case data"""
    
    def __init__(self, case_data: Dict[str, Any]):
        """
        Initialize with case data containing nodes and edges arrays.
        
        Args:
            case_data: Dict with 'nodes' and 'edges' arrays
        """
        self.nodes = case_data.get("nodes", [])
        self.edges = case_data.get("edges", [])
        
        # Build lookup indexes
        self._node_by_id = {n["temp_id"]: n for n in self.nodes if "temp_id" in n}
        self._node_by_label = {}
        for node in self.nodes:
            label = node.get("label")
            if label:
                if label not in self._node_by_label:
                    self._node_by_label[label] = []
                self._node_by_label[label].append(node)
        
        # Build edge indexes
        self._edges_from = {}  # temp_id -> list of edges
        self._edges_to = {}     # temp_id -> list of edges
        for edge in self.edges:
            from_id = edge.get("from")
            to_id = edge.get("to")
            
            if from_id:
                if from_id not in self._edges_from:
                    self._edges_from[from_id] = []
                self._edges_from[from_id].append(edge)
            
            if to_id:
                if to_id not in self._edges_to:
                    self._edges_to[to_id] = []
                self._edges_to[to_id].append(edge)
    
    def get_nodes_by_label(self, label: str) -> List[Dict[str, Any]]:
        """Get all nodes with a specific label"""
        return self._node_by_label.get(label, [])
    
    def get_related_nodes(
        self, 
        node_id: str, 
        relationship: str, 
        target_label: Optional[str] = None,
        direction: str = "outgoing"
    ) -> List[Dict[str, Any]]:
        """
        Get nodes related to a given node via a specific relationship.
        
        Args:
            node_id: The temp_id of the source node
            relationship: The relationship label
            target_label: Optional filter by target node label
            direction: 'outgoing' or 'incoming'
        """
        if direction == "outgoing":
            edges = self._edges_from.get(node_id, [])
            edges = [e for e in edges if e.get("label") == relationship]
            target_ids = [e["to"] for e in edges]
        else:  # incoming
            edges = self._edges_to.get(node_id, [])
            edges = [e for e in edges if e.get("label") == relationship]
            target_ids = [e["from"] for e in edges]
        
        nodes = [self._node_by_id.get(tid) for tid in target_ids]
        nodes = [n for n in nodes if n is not None]
        
        if target_label:
            nodes = [n for n in nodes if n.get("label") == target_label]
        
        return nodes
    
    def build_structured_node(
        self, 
        node: Dict[str, Any], 
        structure_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Recursively build a structured node with its related nodes based on config.
        
        Args:
            node: The node to structure
            structure_config: Configuration defining what to include
        """
        result = {}
        node_id = node.get("temp_id")
        
        for key, config in structure_config.items():
            if config.get("self"):
                # Include the node itself
                result[key] = node
            else:
                # Get related nodes
                via = config.get("via")
                label = config.get("label")
                direction = config.get("direction", "outgoing")
                single = config.get("single", False)
                include = config.get("include", {})
                
                if via:
                    related = self.get_related_nodes(node_id, via, label, direction)
                    
                    # Recursively structure related nodes if they have includes
                    if include and related:
                        structured_related = []
                        for r in related:
                            nested = self.build_structured_node(r, include)
                            # Merge nested structure into the node itself
                            structured_node = {**r, **nested}
                            structured_related.append(structured_node)
                        related = structured_related
                    
                    result[key] = related[0] if (single and related) else related
        
        return result
    
    def build_holdings_centric_view(self) -> Dict[str, Any]:
        """Build the holdingsCentric view"""
        views_config = load_views_config()
        view_config = views_config.get("holdingsCentric", {})
        
        result = {}
        
        # Build top-level entities
        top_level = view_config.get("topLevel", {})
        for key, config in top_level.items():
            label = config.get("label")
            single = config.get("single", False)
            via = config.get("via")
            from_label = config.get("from")
            
            if via and from_label:
                # Get nodes via relationship
                from_nodes = self.get_nodes_by_label(from_label)
                all_related = []
                for from_node in from_nodes:
                    related = self.get_related_nodes(from_node["temp_id"], via, label)
                    all_related.extend(related)
                # Deduplicate
                seen_ids = set()
                unique_related = []
                for r in all_related:
                    if r["temp_id"] not in seen_ids:
                        seen_ids.add(r["temp_id"])
                        unique_related.append(r)
                result[key] = unique_related[0] if (single and unique_related) else unique_related
            else:
                # Direct label lookup
                nodes = self.get_nodes_by_label(label)
                result[key] = nodes[0] if (single and nodes) else nodes
        
        # Build root-level structures (holdings, issues, etc.) - support any root name
        for root_key, root_config in view_config.items():
            if root_key in ['topLevel', 'description']:
                continue  # Skip non-structure keys
            
            if not isinstance(root_config, dict):
                continue
            
            root_label = root_config.get("root")
            structure = root_config.get("structure", {})
            
            if root_label and structure:
                entities = self.get_nodes_by_label(root_label)
                result[root_key] = [
                    self.build_structured_node(e, structure)
                    for e in entities
                ]
        
        return result


def build_case_display_view(case_data: Dict[str, Any], view_name: str = "holdingsCentric") -> Dict[str, Any]:
    """
    Build a structured view of case data.
    
    Args:
        case_data: Case data with 'nodes' and 'edges'
        view_name: Name of the view to build
        
    Returns:
        Structured case data according to the view configuration
    """
    builder = CaseViewBuilder(case_data)
    
    if view_name == "holdingsCentric":
        return builder.build_holdings_centric_view()
    
    raise ValueError(f"Unknown view name: {view_name}")

