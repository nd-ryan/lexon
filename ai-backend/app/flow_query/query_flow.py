import json
import time
import asyncio
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from crewai.flow.flow import Flow, listen, start
from litellm import acompletion

from app.lib.neo4j_client import neo4j_client
from app.lib.embeddings import generate_embedding_sync
from app.lib.search_schema_static import derive_mcp_style_schema_from_static
from app.lib.logging_config import setup_logger
from app.lib.schema_runtime import derive_primary_vector_index_names_from_schema

logger = setup_logger("query-flow")

# --- Configuration ---
# Performance Note: We assume pre-built vector indexes exist in Neo4j.
# The default index names are derived from schema_v3.json so they stay in sync
# with the canonical schema and the DDL in presets_vector_indices.txt.
INDEX_NAMES = derive_primary_vector_index_names_from_schema()
logger.info(f"Vector index mapping (primary per label): {INDEX_NAMES}")

# Build mapping from index_name -> text_property_name
# e.g., "case_summary_embedding_index" -> "summary"
# Index naming pattern: <label_lower>_<embedding_property_name>_index
def _build_index_to_text_property_map() -> Dict[str, str]:
    """Build a mapping from index_name to the corresponding text property name."""
    result = {}
    for label, index_name in INDEX_NAMES.items():
        # Extract embedding property name from index name pattern
        # Pattern: <label_lower>_<embedding_prop>_index
        # Example: "case_summary_embedding_index" -> "summary_embedding" -> "summary"
        label_prefix = f"{label.lower()}_"
        if index_name.startswith(label_prefix) and index_name.endswith("_index"):
            # Remove label prefix and "_index" suffix
            embedding_prop = index_name[len(label_prefix):-6]  # -6 for "_index"
            # Remove "_embedding" suffix to get text property name
            if embedding_prop.endswith("_embedding"):
                text_prop = embedding_prop[:-10]  # -10 for "_embedding"
                result[index_name] = text_prop
    return result

INDEX_TO_TEXT_PROPERTY = _build_index_to_text_property_map()
logger.info(f"Index to text property mapping: {INDEX_TO_TEXT_PROPERTY}")

# --- State Models ---

class SearchStep(BaseModel):
    node_type: str  # e.g., "Case", "Doctrine"
    search_type: str  # "embedding" or "deterministic"
    query_term: Optional[str] = None
    via: Optional[str] = None  # Relationship path for deterministic steps

class RoutePlan(BaseModel):
    steps: List[SearchStep] = []

class NodeInfo(BaseModel):
    id: str
    label: str
    properties: Dict[str, Any] = {}
    score: float = 1.0

class QueryState(BaseModel):
    query: str = ""
    schema_info: Optional[List[Dict[str, Any]]] = None
    route_plan: Optional[RoutePlan] = None
    
    # Deduped store of all nodes found during the flow
    found_nodes: Dict[str, NodeInfo] = {}
    
    # Final structured response
    response: Dict[str, Any] = {}
    
    # Metrics
    start_time: float = 0.0
    timings: Dict[str, float] = {}

# --- Helpers ---

async def safe_generate_embedding(text: str) -> List[float]:
    """Async wrapper for synchronous embedding generation to avoid blocking the loop."""
    try:
        return await asyncio.to_thread(generate_embedding_sync, text)
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        return []

def _get_id_property_for_label(label: str) -> str:
    """Get the ID property name for a label using common patterns."""
    # Common ID property patterns
    snake_label = label.lower()
    common_patterns = [
        f"{snake_label}_id",  # e.g., case_id, issue_id
        "id",
        "uuid",
    ]
    # Return the most common pattern (will be checked in query)
    return common_patterns[0]

def execute_vector_search(label: str, embedding: List[float], limit: int = 5) -> List[Dict[str, Any]]:
    """Directly query Neo4j vector index for speed.
    
    Returns only the text property corresponding to the embedding property being searched,
    plus ID fields for node identification.
    """
    index_name = INDEX_NAMES.get(label)
    if not index_name:
        return []
    
    # Get the text property name from the index name
    text_property = INDEX_TO_TEXT_PROPERTY.get(index_name)
    if not text_property:
        logger.warning(f"No text property mapping found for index {index_name}, falling back to all properties")
        # Fallback: return all properties except embeddings
        query = f"""
        CALL db.index.vector.queryNodes($index_name, $limit, $embedding)
        YIELD node, score
        WITH node, score, properties(node) AS props, [k IN keys(node) WHERE k ENDS WITH '_embedding'] AS embeddingKeys
        RETURN apoc.map.removeKeys(props, embeddingKeys) AS node, score, labels(node) AS labels
        """
    else:
        # Get ID property pattern for extraction
        id_prop_pattern = _get_id_property_for_label(label)
        # Query returns only the text property in node map, and id separately
        query = f"""
        CALL db.index.vector.queryNodes($index_name, $limit, $embedding)
        YIELD node, score
        WITH node, score,
             coalesce(node.{id_prop_pattern}, node.id, node.uuid, 
                      node.case_id, node.issue_id, node.doctrine_id, 
                      node.party_id, node.fact_pattern_id) AS node_id
        RETURN {{
            {text_property}: node.{text_property}
        }} AS node, node_id, score, labels(node) AS labels
        """
    
    try:
        results = neo4j_client.execute_query(query, {
            "index_name": index_name, 
            "limit": limit, 
            "embedding": embedding
        })
        if not results:
            logger.info(f"Neo4j vector query returned 0 rows for label={label}, index={index_name}")
        else:
            logger.info(f"Neo4j vector query returned {len(results)} rows for label={label}, index={index_name}")

        normalized = []
        for row in results:
            normalized.append({
                "node": row.get('node', {}),
                "node_id": row.get('node_id'),  # ID extracted separately, not in node map
                "score": row.get('score', 0.0),
                "labels": row.get('labels', [])
            })
        return normalized
    except Exception as e:
        logger.error(f"Vector search failed for {label}: {e}")
        return []

def get_node_id(properties: Dict[str, Any]) -> str:
    """Heuristic to extract a stable ID from node properties."""
    for key in ["id", "case_id", "uuid", "party_id", "doctrine_id", "issue_id"]:
        if key in properties:
            return str(properties[key])
    return str(properties.get("name", "unknown"))

# --- Main Flow ---

class QueryFlow(Flow[QueryState]):
    
    @start()
    def interpret_query(self):
        """Step 1: Interpret Query & Plan Strategy (Agentic Step)"""
        self.state.start_time = time.time()
        logger.info(f"🚀 Starting Query Flow: {self.state.query}")
        self.state.timings = {}
        
        # 1. Fast Schema Load
        t_schema_start = time.time()
        if not self.state.schema_info:
            try:
                self.state.schema_info = derive_mcp_style_schema_from_static()
            except Exception:
                self.state.schema_info = []
        t_schema_end = time.time()
        self.state.timings["schema_load_seconds"] = t_schema_end - t_schema_start

        # 2. Generate Plan
        t_prompt_start = time.time()
        # We use a direct LLM call here instead of an Agent wrapper to save ~500ms+ overhead
        schema_summary = [
            {"label": s["label"], "relationships": list(s.get("relationships", {}).keys())} 
            for s in self.state.schema_info
        ]
        
        prompt = f"""
        You are the **Planner Agent** in a legal graph reasoning system (Lexon).
        Your job is to read the user's natural language query and produce a
        schema-aware search plan — the minimal set of non-deterministic and deterministic
        steps needed to retrieve all relevant nodes from the Neo4j knowledge graph.

        ---

        ### USER QUERY
        "{self.state.query}"

        ---

        ### AVAILABLE SCHEMA (SUMMARY)
        {json.dumps(schema_summary)}

        ---

        # GOAL
        Return a JSON object containing a `"steps"` array.
        Each step describes a *search operation* needed to answer the query.

        A step has this format:
        {{
        "node_type": "Case" | "Doctrine" | "Issue" | "FactPattern" | "Law" | "Domain" | "Forum" | ...,
        "search_type": "embedding" | "deterministic",
        "query_term": "string explaining what semantic concept to match",
        "via": "optional: describe deterministic traversal path to reach the node"
        }}

        ---

        # PLANNING GUIDELINES

        Think like an expert lawyer with perfect memory of the entire dataset.

        1. **Identify the primary legal concepts** in the user query.
        - These are usually Doctrines, Issues, FactPatterns, Laws, or Domains.

        2. **Identify the legal entities** needed to resolve the query:
        - Likely Cases, Doctrines, Issues, FactPatterns, or Laws.

        3. **Use embedding search** whenever the user query uses:
        - conceptual phrases,
        - lay terminology,
        - synonyms,
        - non-legal words,
        - or domain-level ideas (“monopolies”, “platform suppression”, “speech rights”).

        4. **Use deterministic search** when:
        - the step involves predictable schema paths,
        - e.g., finding doctrines attached to a case via:
            Case → Proceeding → Issue → Doctrine.

        5. *Do not* return IDs in Step 1 (they appear later in the pipeline).

        6. Produce **several steps** if necessary:
        - Often you will need:
            - one step for Domains,
            - one for Cases,
            - one for Doctrines,
            - optionally one for FactPatterns.

        7. Prefer over-inclusion at the planning stage:
        - The filtering and sufficiency checks happen later.

        ---

        # OUTPUT REQUIREMENTS

        Return ONLY valid JSON with a `"steps"` array.

        Example:
        {{
        "steps": [
            {{
            "node_type": "Domain",
            "search_type": "embedding",
            "query_term": "antitrust or competition law"
            }},
            {{
            "node_type": "Case",
            "search_type": "embedding",
            "query_term": "exclusive control of platforms"
            }},
            {{
            "node_type": "Doctrine",
            "search_type": "deterministic",
            "via": "Case → Proceeding → Issue → Doctrine"
            }}
        ]
        }}
        """
        t_prompt_end = time.time()
        self.state.timings["prompt_build_seconds"] = t_prompt_end - t_prompt_start
        return self._generate_plan_async(prompt)

    async def _generate_plan_async(self, prompt: str):
        try:
            t_llm_start = time.time()
            response = await acompletion(
                model="gpt-4.1",
                messages=[
                    {"role": "system", "content": "You are a JSON-only planner. Output valid JSON."}, 
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            t_llm_end = time.time()
            self.state.timings["llm_plan_seconds"] = t_llm_end - t_llm_start
            content = response.choices[0].message.content
            plan_dict = json.loads(content)
            self.state.route_plan = RoutePlan(**plan_dict)
            logger.info(f"📋 Plan generated: {len(self.state.route_plan.steps)} steps")
            # Total time spent in interpret step (from when it was started)
            if self.state.start_time:
                self.state.timings["interpret_total_seconds"] = t_llm_end - self.state.start_time
            return "plan_ready"
        except Exception as e:
            logger.error(f"Planning failed: {e}")
            # Fallback safety plan
            self.state.route_plan = RoutePlan(steps=[
                SearchStep(node_type="Case", search_type="embedding", query_term=self.state.query)
            ])
            # Still record total time if possible
            now = time.time()
            if self.state.start_time:
                self.state.timings["interpret_total_seconds"] = now - self.state.start_time
            return "plan_ready"

    @listen("plan_ready")
    async def execute_searches(self):
        """Step 2: Execute Non-Deterministic Searches (Parallel)"""
        logger.info("Running vector searches...")
        
        # Prepare all async tasks
        tasks = []
        for step in self.state.route_plan.steps:
            if step.search_type == "embedding" and step.query_term:
                tasks.append(self._run_vector_search(step))
        logger.info(
            f"Prepared {len(tasks)} embedding vector search steps "
            f"(total plan steps={len(self.state.route_plan.steps)})"
        )
        
        if tasks:
            # Fire all requests simultaneously
            results_list = await asyncio.gather(*tasks)
            
            # Process results into state
            count = 0
            for results in results_list:
                for item in results:
                    props = item["node"]
                    # Use node_id if available (from vector search), otherwise extract from props
                    nid = item.get("node_id") or get_node_id(props)
                    if nid not in self.state.found_nodes:
                        lbl = item["labels"][0] if item["labels"] else "Unknown"
                        self.state.found_nodes[nid] = NodeInfo(
                            id=nid,
                            label=lbl,
                            properties=props,
                            score=item["score"]
                        )
                        count += 1
            logger.info(f"Found {count} new nodes from vector search.")
        
        return "searches_done"

    async def _run_vector_search(self, step: SearchStep) -> List[Dict[str, Any]]:
        logger.info(
            f"Starting vector search step: node_type={step.node_type}, "
            f"search_type={step.search_type}, query_term={step.query_term!r}"
        )

        # Generate embedding
        vec = await safe_generate_embedding(step.query_term)
        if not vec:
            logger.warning(
                f"Embedding is empty for node_type={step.node_type}, "
                f"query_term={step.query_term!r}; skipping vector search."
            )
            return []

        index_name = INDEX_NAMES.get(step.node_type)
        if not index_name:
            logger.info(
                f"No vector index configured for label={step.node_type}; "
                "skipping vector search for this step."
            )
            return []

        logger.info(
            f"Executing vector search for label={step.node_type}, "
            f"index={index_name}, embedding_dim={len(vec)}, limit=5"
        )

        # Run DB query
        results = await asyncio.to_thread(execute_vector_search, step.node_type, vec)
        logger.info(
            f"Completed vector search for label={step.node_type}, "
            f"index={index_name}, normalized_results={len(results)}"
        )
        return results

    @listen("searches_done")
    async def deterministic_traversal(self):
        """Step 3: Deterministic Graph Traversal (Expansion)"""
        logger.info("Running deterministic traversal...")
        
        # Start from the highest relevance nodes
        top_nodes = sorted(self.state.found_nodes.values(), key=lambda x: x.score, reverse=True)[:3]
        
        for node in top_nodes:
            query = ""
            params = {"id": node.id}
            
            # Example Logic: Case -> Cites -> Case, or Case -> Raises -> Issue
            if node.label == "Case":
                query = """
                MATCH (c:Case) WHERE c.case_id = $id OR c.id = $id
                OPTIONAL MATCH (c)-[:RAISES]->(i:Issue)
                OPTIONAL MATCH (i)-[:RELATES_TO]->(d:Doctrine)
                RETURN i, d
                LIMIT 10
                """
            elif node.label == "Issue":
                query = """
                MATCH (i:Issue) WHERE i.id = $id
                OPTIONAL MATCH (i)-[:RELATES_TO]->(d:Doctrine)
                RETURN d
                LIMIT 5
                """
                
            if query:
                try:
                    # Run traversal
                    res = await asyncio.to_thread(neo4j_client.execute_query, query, params)
                    for row in res:
                        for key, val in row.items():
                            if val and isinstance(val, dict):
                                nid = get_node_id(val)
                                if nid not in self.state.found_nodes:
                                    # Heuristic label detection
                                    lbl = "Doctrine" if "d" in key else "Issue" if "i" in key else "Unknown"
                                    # Remove id from properties to avoid duplication
                                    val_clean = {k: v for k, v in val.items() if k != "id"}
                                    self.state.found_nodes[nid] = NodeInfo(
                                        id=nid, 
                                        label=lbl, 
                                        properties=val_clean, 
                                        score=node.score * 0.8 # Decay score for related nodes
                                    )
                except Exception as e:
                    logger.error(f"Traversal failed for {node.id}: {e}")

        return "traversal_done"

    @listen("traversal_done")
    async def construct_answer(self):
        """Step 4: Construct Final Answer"""
        logger.info("Synthesizing answer...")
        
        # Prepare minimal context for the LLM
        sorted_nodes = sorted(self.state.found_nodes.values(), key=lambda x: x.score, reverse=True)
        
        context_items = []
        for n in sorted_nodes[:15]: # Hard limit to prevent context overflow/latency
            context_items.append({
                "type": n.label,
                "name": n.properties.get("name") or n.properties.get("case_name") or "Unknown",
                "summary": n.properties.get("summary") or n.properties.get("description") or "N/A",
                "id": n.id
            })
            
        prompt = f"""
        User Query: "{self.state.query}"
        
        Graph Data:
        {json.dumps(context_items, indent=2)}
        
        Task:
        1. Answer the user's question using ONLY the provided graph data.
        2. Return a structured JSON response.
        
        Format:
        {{
            "query": "...",
            "cases": [ {{ "name": "...", "citation": "...", "summary": "...", "jurisdiction": "..." }} ],
            "doctrines": [ {{ "name": "...", "description": "..." }} ],
            "analysis": "A synthesized legal analysis answering the question..."
        }}
        """
        
        try:
            response = await acompletion(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a helpful legal assistant. Output valid JSON."}, 
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            self.state.response = json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"Answer generation failed: {e}")
            self.state.response = {
                "query": self.state.query,
                "error": "Failed to generate answer.",
                "details": str(e)
            }
            
        elapsed = time.time() - self.state.start_time
        logger.info(f"✅ Query Flow completed in {elapsed:.2f}s")
        return self.state.response


def create_query_flow() -> QueryFlow:
    return QueryFlow()
