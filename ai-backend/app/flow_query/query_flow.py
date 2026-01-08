import json
import time
import asyncio
import hashlib
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from crewai.flow.flow import Flow, listen, start
from litellm import acompletion

from app.lib.neo4j_client import neo4j_client
from app.lib.embeddings import generate_embedding_sync
from app.lib.search_schema_static import derive_mcp_style_schema_from_static
from app.lib.logging_config import setup_logger
from app.lib.schema_runtime import derive_all_vector_index_names_from_schema
from app.lib.batch_query_utils import build_batch_query

logger = setup_logger("query-flow")

# --- Configuration ---
# Performance Note: We assume pre-built vector indexes exist in Neo4j.
# The default index names are derived from schema_v3.json so they stay in sync
# with the canonical schema and the DDL in presets_vector_indices.txt.
INDEX_NAMES = derive_all_vector_index_names_from_schema()
logger.info(f"Vector index mapping (all per label): {INDEX_NAMES}")

# Build mapping from index_name -> text_property_name
# e.g., "case_summary_embedding_index" -> "summary"
# Index naming pattern: <label_lower>_<embedding_property_name>_index
def _build_index_to_text_property_map() -> Dict[str, str]:
    """Build a mapping from index_name to the corresponding text property name."""
    result = {}
    for label, prop_map in INDEX_NAMES.items():
        for embedding_prop, index_name in prop_map.items():
            # embedding_prop is e.g. "summary_embedding"
            # We want "summary"
            if embedding_prop.endswith("_embedding"):
                text_prop = embedding_prop[:-10]
                result[index_name] = text_prop
            else:
                # Fallback if naming convention differs (though derive_all guarantees _embedding suffix)
                result[index_name] = embedding_prop
    return result

INDEX_TO_TEXT_PROPERTY = _build_index_to_text_property_map()
logger.info(f"Index to text property mapping: {INDEX_TO_TEXT_PROPERTY}")

# --- State Models ---

class SearchStep(BaseModel):
    node_type: str  # e.g., "Case", "Doctrine"
    search_type: str  # "embedding" or "deterministic"
    query_term: Optional[str] = None
    embedding_property: Optional[str] = None  # Which property to search (if multiple exist)
    path: Optional[List[str]] = None  # Node sequence for deterministic steps (e.g., ["Issue", "Doctrine"])
    depends_on: Optional[List[int]] = None  # Indices of previous steps to use as input

class RoutePlan(BaseModel):
    steps: List[SearchStep] = []

class NodeInfo(BaseModel):
    label: str
    properties: Dict[str, Any] = {}
    score: float = 1.0

class QueryState(BaseModel):
    query: str = ""
    schema_info: Optional[List[Dict[str, Any]]] = None
    route_plan: Optional[RoutePlan] = None
    
    # Deduped store of all nodes found during the flow
    found_nodes: Dict[str, NodeInfo] = {}
    
    # Results by step index: step_index -> [node_id, ...]
    step_results: Dict[int, List[str]] = {}
    
    # Final structured response
    response: Dict[str, Any] = {}
    
    # Reasoning chain
    reasoning: Optional[str] = None

    # Metrics
    start_time: float = 0.0
    timings: Dict[str, float] = {}

# --- Helpers ---

def _get_incoming_relationships(target_label: str, schema_info: List[Dict[str, Any]]) -> List[str]:
    """Find all relationships pointing TO this label from other nodes."""
    incoming = []
    for node in schema_info:
        for rel_name, rel_target in node.get("relationships", {}).items():
            target = rel_target if isinstance(rel_target, str) else rel_target.get("target")
            if target == target_label:
                incoming.append(f"{node['label']}-{rel_name}->{target_label}")
    return incoming

def _build_schema_summary_with_directionality(schema_info: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build enhanced schema summary showing both outgoing and incoming relationships."""
    schema_summary = []
    for s in schema_info:
        # Outgoing relationships (defined in this node's schema)
        outgoing = [
            f"{k} (-> {v})" if isinstance(v, str) else f"{k} (-> {v.get('target', 'Unknown')})"
            for k, v in s.get("relationships", {}).items()
        ]
        
        # Incoming relationships (from other nodes pointing to this one)
        incoming = _get_incoming_relationships(s["label"], schema_info)
        
        schema_summary.append({
            "label": s["label"],
            "properties": [
                p for p in s.get("attributes", {}).keys()
                if not (p.endswith("_embedding") or p.endswith("_upload_code"))
            ],
            "outgoing_relationships": outgoing,
            "incoming_relationships": incoming
        })
    return schema_summary

async def safe_generate_embedding(text: str) -> List[float]:
    """Async wrapper for synchronous embedding generation to avoid blocking the loop."""
    try:
        return await asyncio.to_thread(generate_embedding_sync, text)
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        return []

def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case."""
    import re
    # Insert underscore before uppercase letters that follow lowercase letters
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    # Insert underscore before uppercase letters that follow lowercase or uppercase letters
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def _get_id_property_for_label(label: str) -> str:
    """Get the ID property name for a label using common patterns."""
    # Convert CamelCase to snake_case properly (e.g., FactPattern -> fact_pattern)
    snake_label = _camel_to_snake(label)
    common_patterns = [
        f"{snake_label}_id",  # e.g., case_id, fact_pattern_id
        "id",
        "uuid",
    ]
    # Return the most common pattern (will be checked in query)
    return common_patterns[0]

def execute_vector_search(label: str, embedding: List[float], limit: int = 5, target_property: Optional[str] = None, threshold: float = 0.7) -> List[Dict[str, Any]]:
    """Directly query Neo4j vector index for speed.
    
    Returns only the text property corresponding to the embedding property being searched,
    plus ID fields for node identification.
    """
    prop_map = INDEX_NAMES.get(label)
    if not prop_map:
        return []
    
    index_name = None
    if target_property:
        # Try exact match or append _embedding
        candidates = [target_property]
        if not target_property.endswith("_embedding"):
            candidates.append(f"{target_property}_embedding")
        
        for c in candidates:
            if c in prop_map:
                index_name = prop_map[c]
                break
        
        if not index_name:
            logger.warning(f"Target property '{target_property}' not found in indexes for {label}. Available: {list(prop_map.keys())}")

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
        WHERE score >= $threshold
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
        WHERE score >= $threshold
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
            "embedding": embedding,
            "threshold": threshold
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
    # Try common ID properties first
    for key in ["id", "uuid", "case_id", "party_id", "doctrine_id", "issue_id", "ruling_id", 
                "proceeding_id", "argument_id", "relief_id", "law_id", "fact_pattern_id", 
                "policy_id", "forum_id", "jurisdiction_id", "relief_type_id", "domain_id"]:
        if key in properties and properties[key]:
            return str(properties[key])
    
    # Fallback to name if it exists and is not empty
    if properties.get("name"):
        return str(properties["name"])
    
    # Last resort: use a hash of all properties
    props_str = json.dumps(properties, sort_keys=True)
    return hashlib.md5(props_str.encode()).hexdigest()[:16]

def _find_relationship_between_nodes(source_label: str, target_label: str, schema_info: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Look up the relationship between two node types in the schema.
    
    Returns:
        {
            'relationship_name': str,
            'direction': 'forward' | 'backward',
            'cypher_pattern': str  # e.g., "-[:REL_NAME]->" or "<-[:REL_NAME]-"
        }
        or None if no relationship found
    """
    # First, check if source has an outgoing relationship to target
    for node in schema_info:
        if node['label'] == source_label:
            for rel_name, rel_target in node.get('relationships', {}).items():
                target = rel_target if isinstance(rel_target, str) else rel_target.get('target')
                if target == target_label:
                    return {
                        'relationship_name': rel_name,
                        'direction': 'forward',
                        'cypher_pattern': f'-[:{rel_name}]->'
                    }
    
    # Second, check if target has an outgoing relationship to source (we'd traverse backward)
    for node in schema_info:
        if node['label'] == target_label:
            for rel_name, rel_target in node.get('relationships', {}).items():
                target = rel_target if isinstance(rel_target, str) else rel_target.get('target')
                if target == source_label:
                    return {
                        'relationship_name': rel_name,
                        'direction': 'backward',
                        'cypher_pattern': f'<-[:{rel_name}]-'
                    }
    
    return None

# --- Main Flow ---

class QueryFlow(Flow[QueryState]):
    
    @start()
    def reason_query(self):
        """Step 1: Reason about the Query (Natural Language Planning)"""
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

        schema_summary = _build_schema_summary_with_directionality(self.state.schema_info)

        # Build embedding capabilities summary
        embedding_capabilities = {}
        for label, prop_map in INDEX_NAMES.items():
            props = []
            for prop in prop_map.keys():
                if prop.endswith("_embedding"):
                     props.append(prop[:-10])
                else:
                     props.append(prop)
            embedding_capabilities[label] = sorted(props)

        system_instruction = f"""
        You are the **Planner Agent** in a legal knowledge-graph reasoning system (Lexon).
        Your task is to think step-by-step about how to answer the user's natural language
        query using the graph schema.

        You MUST produce a clean, minimal, non-duplicative search strategy.

        Do NOT output JSON yet. Output only a concise, logical paragraph describing your reasoning.

        ---

        ### AVAILABLE SCHEMA (with Relationship Directionality)
        {json.dumps(schema_summary, indent=2)}

        ---

        # HOW TO PLAN (STRICT RULES)

        You must follow these rules exactly:

        1. **Identify the final target node types first.**
        - These are the node types the answer must ultimately draw from, based on the schema.
        - Examples: Doctrine, Ruling, Issue, Law, FactPattern, Case, etc
        - Select ONLY the node types that are truly necessary for answering the query.
        - Do NOT list every connected node type.

        2. **Choose ONE embedding anchor node type for each conceptual entry point.**
        - If the query is conceptual, choose ONE node type whose text properties capture the concept best
            (e.g., Issue.text, Doctrine.description, Ruling.reasoning).
        - You MUST NOT run embedding search on multiple node types for the same concept.
        - You MUST NOT run embedding search on a node type that will be obtained deterministically later.

        3. **All embedding searches run FIRST and have NO dependencies.**
        - These embedding searches generate the initial "anchor set" of nodes.
        - There should only be 1-3 embedding steps total.
        - Embedding searches must specify which text property to match.

        4. **Deterministic steps come AFTER embeddings and MUST be dependency-linked.**
        - The deterministic chain must go ONE direction only.
        - Example: Issue → Doctrine → Ruling → Case (if the answer requires it).
        - Do NOT gather the same node type from more than one path.
        - Do NOT propose multiple different ways to reach the same node type.
        - Deterministic steps must explicitly reference which earlier step they depend on.
        - **IMPORTANT**: You just specify the node types - the system will automatically look up 
          the correct relationships and directionality from the schema!

        5. **Avoid duplication at all costs.**
        - If you obtain Doctrines via Issue → Doctrine, do NOT also obtain Doctrines via
            embeddings or via Law → Ruling → Issue → Doctrine.
        - If you obtain Issues via embeddings, do NOT also expand Cases → Proceeding → Issue.

        6. **Keep the plan minimal.**
        - Only include the nodes strictly required to answer the query.
        - Over-inclusion wastes compute.

        ---

        # WHAT TO EXPLAIN IN THE PARAGRAPH

        Write 3-4 concise sentences describing:

        1. Which node types are the final targets and why.
        2. Which SINGLE embedding anchor type(s) you will use, and which property to match.
        3. The EXACT deterministic traversal path starting from the embedding results (include arrow directions).
        4. Why this sequence avoids duplication and is the minimal complete search.

        Be concise, structured, and disciplined.

        ---

        # EXAMPLE (for demonstration only)

        Query: "I'm looking for antitrust rulings that cite the Sherman Act."

        A good reasoning paragraph would say:

        - The final targets are Rulings because the user wants "rulings," and we also need Law nodes
        to identify Sherman Act statutes.
        - The embedding anchor should be Law.text to find Sherman Act references.
        - From the Law nodes, deterministically traverse Law to Ruling.
        - Since the target is Rulings, no Issue or Doctrine traversal is needed.

        ---

        Now read the user's query and produce your reasoning paragraph.
        """


        user_input = f"""
        ### USER QUERY
        "{self.state.query}"
        """
        
        return self._generate_reasoning_async(system_instruction, user_input)

    async def _generate_reasoning_async(self, system_instruction: str, user_input: str):
        try:
            t_llm_start = time.time()
            # Using a fast model for reasoning
            response = await acompletion(
                model="gemini/gemini-3-pro", 
                messages=[
                    {"role": "system", "content": system_instruction}, 
                    {"role": "user", "content": user_input}
                ]
            )
            t_llm_end = time.time()
            self.state.timings["llm_reasoning_seconds"] = t_llm_end - t_llm_start
            self.state.reasoning = response.choices[0].message.content
            
            # Log token usage if available
            if hasattr(response, 'usage') and response.usage:
                usage = response.usage
                prompt_tokens = getattr(usage, 'prompt_tokens', 0)
                completion_tokens = getattr(usage, 'completion_tokens', 0)
                total_tokens = getattr(usage, 'total_tokens', 0)
                logger.info(f"🧠 Reasoning generated: {self.state.reasoning[:100]}... [tokens: {prompt_tokens} prompt + {completion_tokens} completion = {total_tokens} total]")
            else:
                logger.info(f"🧠 Reasoning generated: {self.state.reasoning[:100]}...")
            return "reasoning_ready"
        except Exception as e:
            logger.error(f"Reasoning failed: {e}")
            self.state.reasoning = "Proceeding with default search strategy."
            return "reasoning_ready"

    @listen("reasoning_ready")
    def interpret_query(self):
        """Step 2: Interpret Query & Plan Strategy (JSON Generation)"""
        # Re-use schema info loaded in previous step
        t_prompt_start = time.time()
        
        schema_summary = _build_schema_summary_with_directionality(self.state.schema_info)
        
        embedding_capabilities = {}
        for label, prop_map in INDEX_NAMES.items():
            props = []
            for prop in prop_map.keys():
                if prop.endswith("_embedding"):
                     props.append(prop[:-10])
                else:
                     props.append(prop)
            embedding_capabilities[label] = sorted(props)

        system_instruction = f"""
        You are the **Planner Agent** in a legal graph reasoning system (Lexon).
        Your task is to convert the REASONING STRATEGY (provided in the user input) 
        into a formal schema-aware search plan.
        
        ---

        ### AVAILABLE SCHEMA (with Relationship Directionality)
        {json.dumps(schema_summary, indent=2)}

        ### EMBEDDING SEARCH CAPABILITIES
        {json.dumps(embedding_capabilities)}

        ---

        # PURPOSE

        Your output determines *what* the system will search for, and *in what order*.
        You do **not** return IDs or Cypher. You return **instructions** describing
        a correct, dependency-aware search strategy that downstream components will execute.

        All **embedding searches** (if any) will be executed first and in parallel.
        Then **deterministic steps** will run, using the outputs of earlier steps where needed.

        ---

        # STEP FORMAT

        Each step is a JSON object in a `"steps"` array.

        Every step MUST include:
        - `"node_type"`: One of the labels in the schema (e.g., "Case", "Issue", "Doctrine").
        - `"search_type"`: Either `"embedding"` or `"deterministic"`.

        For **embedding steps**:
        - `"query_term"`: A short phrase describing the semantic concept to match.
        - `"embedding_property"`: One of the allowed embedding properties for that node type,
        as listed under EMBEDDING SEARCH CAPABILITIES.
        - **Do NOT include** a `"depends_on"` field for embedding steps.
        - Embedding steps must always come *before* any deterministic steps.

        For **deterministic steps**:
        - `"path"`: An array of node labels showing the traversal sequence.
                The system will automatically look up the correct relationships from the schema.
                Examples:
                - Single hop: `["Issue", "Doctrine"]` (system will find: Issue-RELATES_TO_DOCTRINE->Doctrine)
                - Multi-hop: `["Issue", "Proceeding", "Ruling"]` (system will chain the relationships)
                - Backward: `["Doctrine", "Issue"]` (system will detect: Doctrine<-RELATES_TO_DOCTRINE-Issue)
        - `"depends_on"`: An array of step indices (0-based) indicating which previous
        steps' outputs (node IDs) this step will operate on.
        - Example: `"depends_on": [0, 2]` means this step will use results from steps 0 and 2.

        Optional field for any step:
        - `"role"`: `"anchor"` | `"expand"` | `"optional"` (helps describe the intent of the step).

        ---

        # SIMPLIFIED: NO NEED TO SPECIFY RELATIONSHIPS!

        **Great News**: You don't need to know the relationship names or arrows!
        
        Just specify the sequence of node types you want to traverse, and the system will:
        - Automatically look up the correct relationship from the schema
        - Handle forward and backward traversal automatically
        - Build the optimal Cypher query
        
        **Examples:**
        - Want to go from Doctrine to Issue? Just write: `"path": ["Doctrine", "Issue"]`
        - Want to go from Issue to Doctrine to Argument? Write: `"path": ["Issue", "Doctrine", "Argument"]`
        - The system handles all the complexity!

        ---

        # SEQUENTIAL LOGIC RULES

        1. **If needed, embedding steps come first** in the plan:
        - They have `"search_type": "embedding"`.
        - They must NOT have a `"depends_on"` field.
        - They will be executed in parallel downstream.

        2. **Deterministic steps come after all embedding steps (if any)**:
        - They have `"search_type": "deterministic"`.
        - They MUST include `"depends_on"` and reference only earlier steps.
        - They describe how to traverse the graph from nodes found in those earlier steps.

        3. Use **embedding steps** to locate:
        - high-level legal domains,
        - issues,
        - doctrines,
        - fact patterns,
        - laws,
        when fuzzy or conceptual matching is needed.

        4. Use **deterministic steps** to follow schema paths from those anchors:
        - e.g., from Domains to Cases: `["Domain", "Case"]`
        - from Cases to Issues: `["Case", "Proceeding", "Issue"]`
        - from Issues to Doctrines: `["Issue", "Doctrine"]`
        - No need to worry about relationship names or directions!

        5. Include only the steps that are reasonably necessary to answer the query.
        Avoid irrelevant node types.

        ---

        # PLANNING GUIDELINES

        Think like an expert lawyer with perfect recall of the entire graph.

        1. Follow the REASONING STRATEGY provided in the user input.
        2. Translate it into the required JSON format.
        3. Make sure deterministic `"via"` paths use real relationship names from the schema.
        4. **Pay close attention to relationship directionality** in the schema summary.

        ---

        # OUTPUT FORMAT

        Return ONLY valid JSON with a top-level `"steps"` array.

        Each step must follow these rules:

        - Embedding step example:

        {{
            "node_type": "Domain",
            "search_type": "embedding",
            "query_term": "antitrust or competition law",
            "embedding_property": "name",
            "role": "anchor"
        }}

        - Deterministic step example (simple path):

        {{
            "node_type": "Doctrine",
            "search_type": "deterministic",
            "path": ["Issue", "Doctrine"],
            "depends_on": [0],
            "role": "expand"
        }}

        - Deterministic step example (multi-hop path):

        {{
            "node_type": "Ruling",
            "search_type": "deterministic",
            "path": ["Issue", "Proceeding", "Ruling"],
            "depends_on": [0],
            "role": "expand"
        }}

        Do NOT wrap the result in any extra object (no "route_plan" or similar).

        ---

        # FULL EXAMPLE (ILLUSTRATIVE ONLY)

        {{
        "steps": [
            {{
            "node_type": "Issue",
            "search_type": "embedding",
            "query_term": "platform monopolies, dominant digital platforms",
            "embedding_property": "text",
            "role": "anchor"
            }},
            {{
            "node_type": "Doctrine",
            "search_type": "deterministic",
            "path": ["Issue", "Doctrine"],
            "depends_on": [0],
            "role": "expand"
            }},
            {{
            "node_type": "Ruling",
            "search_type": "deterministic",
            "path": ["Issue", "Proceeding", "Ruling"],
            "depends_on": [0],
            "role": "expand"
            }},
            {{
            "node_type": "Case",
            "search_type": "deterministic",
            "path": ["Proceeding", "Case"],
            "depends_on": [2],
            "role": "expand"
            }}
        ]
        }}
        """

        user_input = f"""
        ### USER QUERY
        "{self.state.query}"

        ### REASONING STRATEGY
        "{self.state.reasoning}"
        
        Based on the reasoning strategy above, generate the formal JSON search plan steps.
        CRITICAL: Ensure every 'deterministic' step has a 'depends_on' field pointing to the correct previous step indices.
        """
        
        t_prompt_end = time.time()
        self.state.timings["prompt_build_seconds"] = t_prompt_end - t_prompt_start
        return self._generate_plan_async(system_instruction, user_input)

    async def _generate_plan_async(self, system_instruction: str, user_input: str):
        try:
            t_llm_start = time.time()
            response = await acompletion(
                model="gemini/gemini-3-pro",
                messages=[
                    {"role": "system", "content": system_instruction}, 
                    {"role": "user", "content": user_input}
                ],
                response_format={"type": "json_object"}
            )
            t_llm_end = time.time()
            self.state.timings["llm_plan_seconds"] = t_llm_end - t_llm_start
            content = response.choices[0].message.content
            plan_dict = json.loads(content)
            self.state.route_plan = RoutePlan(**plan_dict)
            
            # Log token usage if available
            if hasattr(response, 'usage') and response.usage:
                usage = response.usage
                prompt_tokens = getattr(usage, 'prompt_tokens', 0)
                completion_tokens = getattr(usage, 'completion_tokens', 0)
                total_tokens = getattr(usage, 'total_tokens', 0)
                logger.info(f"📋 Plan generated: {len(self.state.route_plan.steps)} steps [tokens: {prompt_tokens} prompt + {completion_tokens} completion = {total_tokens} total]")
            else:
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
        
        # Prepare all async tasks, keeping track of their original step index
        tasks = []
        # Use enumerate to keep track of the step index for result mapping
        embedding_steps = []
        
        for i, step in enumerate(self.state.route_plan.steps):
            if step.search_type == "embedding" and step.query_term:
                embedding_steps.append(i)
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
            for idx, results in enumerate(results_list):
                step_index = embedding_steps[idx]
                step_node_ids = []
                
                for item in results:
                    props = item["node"]
                    # Use node_id if available (from vector search), otherwise extract from props
                    nid = item.get("node_id") or get_node_id(props)
                    
                    if nid:
                        step_node_ids.append(nid)
                        if nid not in self.state.found_nodes:
                            lbl = item["labels"][0] if item["labels"] else "Unknown"
                            self.state.found_nodes[nid] = NodeInfo(
                                label=lbl,
                                properties=props,
                                score=item["score"]
                            )
                            count += 1
                
                # Store the IDs found by this specific step
                self.state.step_results[step_index] = step_node_ids
                
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

        # Check if label has any indexes
        prop_map = INDEX_NAMES.get(step.node_type)
        if not prop_map:
            logger.info(
                f"No vector index configured for label={step.node_type}; "
                "skipping vector search for this step."
            )
            return []

        logger.info(
            f"Executing vector search for label={step.node_type}, "
            f"target_property={step.embedding_property}, embedding_dim={len(vec)}, limit=10, threshold=0.7"
        )

        # Run DB query
        results = await asyncio.to_thread(
            execute_vector_search, 
            step.node_type, 
            vec, 
            10, 
            step.embedding_property,
            0.7
        )
        logger.info(
            f"Completed vector search for label={step.node_type}, "
            f"normalized_results={len(results)}"
        )
        return results

    @listen("searches_done")
    async def deterministic_traversal(self):
        """Step 3: Deterministic Graph Traversal (Expansion) - Schema-driven approach"""
        logger.info("Running deterministic traversal...")
        
        if not self.state.route_plan or not self.state.route_plan.steps:
            logger.warning("No route plan found, skipping traversal.")
            return "traversal_done"

        for i, step in enumerate(self.state.route_plan.steps):
            if step.search_type != "deterministic":
                continue
                
            logger.info(f"Executing deterministic step {i}: {step.node_type} via path {step.path}")
            
            if not step.path or len(step.path) < 2:
                logger.warning(f"Step {i} missing or invalid 'path' (need at least 2 nodes), skipping.")
                continue

            # Determine start nodes based on dependencies
            start_nodes = []
            if step.depends_on:
                # Collect all node IDs from the specified previous steps
                source_ids = set()
                for dep_idx in step.depends_on:
                    if dep_idx in self.state.step_results:
                        source_ids.update(self.state.step_results[dep_idx])
                    else:
                        logger.warning(f"Step {i} depends on step {dep_idx}, but no results found for that step.")
                
                # Retrieve full node objects
                for nid in source_ids:
                    if nid in self.state.found_nodes:
                        start_nodes.append((nid, self.state.found_nodes[nid]))
            else:
                # Fallback: use nodes matching the first label in path
                source_label = step.path[0]
                for nid, node in self.state.found_nodes.items():
                    if node.label == source_label:
                        start_nodes.append((nid, node))
            
            if not start_nodes:
                logger.warning(f"Step {i}: No start nodes found. "
                             f"Expected nodes of type '{step.path[0]}' from dependencies {step.depends_on}.")
                continue
                
            # Limit start nodes to top K by score to prevent explosion
            top_start_nodes = sorted(start_nodes, key=lambda x: x[1].score, reverse=True)[:10]
            start_label = start_nodes[0][1].label
            logger.info(f"Step {i}: Starting traversal from {len(top_start_nodes)} nodes (type={start_label})")
            
            # Build Cypher pattern by looking up each hop in the schema
            cypher_hops = []
            all_rels = []
            
            for idx in range(len(step.path) - 1):
                source = step.path[idx]
                target = step.path[idx + 1]
                
                rel_info = _find_relationship_between_nodes(source, target, self.state.schema_info)
                
                if not rel_info:
                    logger.error(f"Step {i}: No relationship found in schema between '{source}' and '{target}'. "
                               f"Skipping this step.")
                    cypher_hops = None
                    break
                
                cypher_hops.append(rel_info['cypher_pattern'])
                all_rels.append(rel_info['relationship_name'])
                logger.info(f"Step {i}: {source} {rel_info['cypher_pattern']} {target} "
                          f"(direction: {rel_info['direction']})")
            
            if not cypher_hops:
                continue
            
            target_label = step.node_type
            
            # Execute traversal for each start node
            step_new_ids = []
            step_total_results = 0
            
            for nid, node in top_start_nodes:
                id_prop = _get_id_property_for_label(node.label)
                
                # Build the full path pattern
                path_pattern = "(s:{})".format(node.label)
                for hop_idx, cypher_hop in enumerate(cypher_hops):
                    next_label = step.path[hop_idx + 1]
                    path_pattern += cypher_hop
                    if hop_idx < len(cypher_hops) - 1:
                        # Intermediate node
                        path_pattern += f"(:{next_label})"
                    else:
                        # Final target node
                        path_pattern += "(t:{})".format(next_label)
                
                query = f"""
                MATCH (s:{node.label})
                WHERE coalesce(s.{id_prop}, s.id, s.uuid) = $id
                MATCH path = {path_pattern}
                WITH DISTINCT t
                WITH t, [k IN keys(t) WHERE k ENDS WITH '_embedding' OR k ENDS WITH '_upload_code'] AS hiddenKeys
                RETURN apoc.map.removeKeys(properties(t), hiddenKeys) AS t, 1.0 as score
                LIMIT 10
                """
                
                try:
                    res = await asyncio.to_thread(neo4j_client.execute_query, query, {"id": nid})
                    step_total_results += len(res)
                    
                    for row in res:
                        t = row.get("t")
                        if t:
                            tnid = get_node_id(t)
                            step_new_ids.append(tnid)
                            
                            if tnid not in self.state.found_nodes:
                                # Remove id props and internal keys
                                props = {k: v for k, v in t.items() if not k.endswith("_id") and k != "id"}
                                self.state.found_nodes[tnid] = NodeInfo(
                                    label=target_label,
                                    properties=props,
                                    score=node.score * 0.9
                                )
                except Exception as e:
                    logger.error(f"Step {i}, Node {nid}: Cypher query failed with error: {e}")
                    logger.error(f"Step {i}, Node {nid}: Failed query was:\n{query}")
            
            # Store results and provide appropriate feedback
            # Deduplicate IDs before storing to avoid polluting stats
            self.state.step_results[i] = list(set(step_new_ids))
            
            if len(step_new_ids) == 0:
                if step_total_results == 0:
                    logger.warning(
                        f"Step {i}: No nodes found in deterministic traversal. "
                        f"The Cypher queries executed successfully but returned no data. "
                        f"This could mean: (1) No graph data exists for the path {step.path}, "
                        f"or (2) The start nodes don't have connections along this path."
                    )
                else:
                    logger.info(f"Step {i}: Produced {len(step_new_ids)} unique nodes from {step_total_results} total results.")
            else:
                logger.info(f"Step {i}: Successfully produced {len(step_new_ids)} nodes.")

        return "traversal_done"

    @listen("traversal_done")
    async def gather_enriched_data(self):
        """Step 4: Gather Enriched Data for Found Nodes"""
        logger.info("Gathering enriched data for found nodes...")
        
        # Group found nodes by label
        nodes_by_label: Dict[str, List[str]] = {}
        for nid, node_info in self.state.found_nodes.items():
            if node_info.label not in nodes_by_label:
                nodes_by_label[node_info.label] = []
            nodes_by_label[node_info.label].append(nid)
        
        # Log the breakdown before enrichment
        label_counts = {label: len(ids) for label, ids in nodes_by_label.items()}
        logger.info(f"Nodes to enrich by label: {label_counts}")
            
        all_enriched_nodes = []
        
        for label, ids in nodes_by_label.items():
            if not ids:
                continue
                
            # Get ID property for this label
            id_prop = _get_id_property_for_label(label)
            
            # Build batch query using the helper
            # Note: helper returns a string query
            # We use summary_relationships=True to get aggregated counts instead of full details
            query = build_batch_query(label, id_prop, ids, summary_relationships=True)
            
            try:
                # Execute query (no params needed as ids are baked into the query string by the helper)
                # The helper generates a query that returns 'n' which contains the projected properties
                # and 'relationships'
                results = await asyncio.to_thread(neo4j_client.execute_query, query)
                
                for row in results:
                    node_data = row.get("n")
                    if node_data:
                        all_enriched_nodes.append(node_data)
                        
            except Exception as e:
                logger.error(f"Enrichment failed for label={label}: {e}")
        
        # Store the raw enriched data in the response
        self.state.response = {
            "query": self.state.query,
            "enriched_nodes": all_enriched_nodes
        }
        
        # Count nodes by label for summary logging
        node_counts = {}
        for node in all_enriched_nodes:
            label = node.get("node_label", "Unknown")
            node_counts[label] = node_counts.get(label, 0) + 1
        
        # Format the breakdown as a readable string
        breakdown = ", ".join([f"{count} {label}" for label, count in sorted(node_counts.items())])
            
        elapsed = time.time() - self.state.start_time
        logger.info(f"✅ Query Flow completed in {elapsed:.2f}s. Returned {len(all_enriched_nodes)} nodes: {breakdown}")
        return self.state.response


def create_query_flow() -> QueryFlow:
    return QueryFlow()
