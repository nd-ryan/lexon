from crewai import Task
from typing import List
from app.models.search import StructuredSearchResponse, GeneratedCypherQueries

# NEW: Specialized tasks following one-agent-one-task pattern

def create_schema_analysis_task(agent, query: str):
    """Task 1: Retrieve the raw Neo4j schema."""
    return Task(
        description="Your one and only task is to call the `get_neo4j_schema` tool to retrieve the complete database schema. Then, return its direct output.",
        expected_output="The direct, raw, unmodified JSON output from the `get_neo4j_schema` tool. Nothing else.",
        agent=agent
    )

def create_query_generation_task(agent, query: str, context: list = None):
    """Task 2: Generate optimal Cypher queries based on schema and user query"""
    return Task(
        description=f"""
        Generate optimal Cypher queries for: "{query}" using the schema analysis from the previous task.
        
        You will receive the schema analysis results from the Schema Analyst agent as context.
        
        Your specific task is to:
        1. **Analyze the user query**: "{query}" to understand intent.
        2. **Use the provided schema analysis** to identify relevant node types and relationships.
        3. **Generate 3 distinct Cypher queries** following the guidance below:

        **Query Generation Guidance:**
        - **Use fuzzy search** for string matching (e.g., `CONTAINS` or `STARTS WITH`) and ensure all comparisons are **case-insensitive** by using `toLower()`.
        - If the user searches for a proper noun (e.g., a specific case name or doctrine), consider that it might be stored as an **acronym** in the database and include that in your search logic.
        - `primary_query`: The most direct query to answer the user's request.
        - `alternative_query`: A broader search including related concepts or synonyms.
        - `fallback_query`: A simpler, more general query to run if the others fail or return no results.

        4. **Format your output** as a single JSON object that strictly conforms to the `GeneratedCypherQueries` Pydantic model.
        """,
        expected_output="A single, valid JSON object with three keys: `primary_query`, `alternative_query`, and `fallback_query`, each containing a raw Cypher query string.",
        agent=agent,
        context=context,
        output_pydantic=GeneratedCypherQueries
    )

def create_query_execution_task(agent, context: list = None):
    """Task 3: Execute Cypher queries and return raw results"""
    return Task(
        description=f"""
        Execute the Cypher queries from the structured JSON object provided by the Query Generator agent.

        You will receive a JSON object with keys `primary_query`, `alternative_query`, and `fallback_query`. Your task is to execute them with conditional logic:
        
        1.  **Execute the Primary Query**: Run the query from the `primary_query` field.
        2.  **Check the Result**:
            - If the query returns a non-empty list or any data, STOP. Your task is complete.
            - If the query returns an empty list (`[]`) or no results, proceed to the next step.
        3.  **Execute the Alternative Query**: Run the query from the `alternative_query` field.
        4.  **Check the Result**:
            - If this query returns results, STOP.
            - If it returns no results, proceed to the next step.
        5.  **Execute the Fallback Query**: Run the query from the `fallback_query` field.
        
        **Your final output for this task must be ONLY the raw JSON results from the *first* query that successfully returned data.** Do not include any of your own text, explanations, or summaries.
        """,
        expected_output="The direct, raw, unmodified JSON output from the first successfully executed query that returned data. Nothing else.",
        agent=agent,
        context=context,
        output_pydantic=GeneratedCypherQueries
    )

# def create_results_analysis_task(agent, query: str, context: list = None):
#     """Task 4: Analyze raw query results to extract insights"""
#     return Task(
#         description=f"""
#         Analyze the raw Neo4j query results for: "{query}"
        
#         You will receive the raw query execution results from the previous task as context.
        
#         Your specific task:
#         1. **Process each result set** from the executed queries
#         2. **Extract key entities** and their properties
#         3. **Identify relationships** and connection patterns
#         4. **Categorize results** by relevance to the original query
#         5. **Format results** into user-friendly bullet points
#         6. **Identify patterns** and notable findings
        
#         Analysis focus:
#         - What entities were found and their significance
#         - How entities relate to each other
#         - Patterns or trends in the data
#         - Completeness and quality of results
#         - Any gaps or limitations in the data
        
#         Format ALL results (don't truncate) with clear structure.
#         """,
#         expected_output="Comprehensive results analysis containing: formatted list of all entities found, relationship mappings, relevance scoring, pattern identification, data quality assessment, and structured presentation of findings",
#         agent=agent,
#         context=context
#     )

def create_insights_synthesis_task(agent, query: str, context: list = None):
    """Task 4: Analyze raw results and create the final response."""
    return Task(
        description=f"""
        Analyze the raw JSON results from the executed Cypher queries and generate a final, user-facing explanation. The original user query was: "{query}".

        You will receive the raw JSON data directly from the Query Executor agent as context. This data is a list of outputs from one or more Cypher queries.

        Your specific task is to:
        1.  Carefully examine the raw JSON results to understand what entities, properties, and relationships were found.
        2.  Synthesize these findings into a concise summary. Focus on what the data reveals in direct response to the user's query.
        3.  Write a single, continuous prose explanation that summarizes the key findings from the data. Do NOT explain the search process or the Cypher queries. The user only wants to understand the results.
        4.  Extract the Cypher queries that were run from the context.
        5.  Assemble the final output into the required Pydantic structure.
        """,
        expected_output="A single, valid JSON object that strictly conforms to the 'StructuredSearchResponse' Pydantic model. It must contain your prose 'explanation' summarizing the results, the raw JSON results, the executed Cypher queries, and the original query.",
        agent=agent,
        output_pydantic=StructuredSearchResponse,
        context=context
    )

# LEGACY: Keep original search task for backward compatibility
def create_search_task(agent, query: str, structured_output=False):
    """Create a task for natural language knowledge graph search using Neo4j MCP tools."""
    task = Task(
        description=f"""
        Execute a knowledge graph search for: "{query}"
        
        You MUST use the Neo4j MCP tools to complete this task:
        
        1. **First, call get-neo4j-schema** to understand the current Neo4j database schema:
           - Get all node types and their properties
           - Understand the relationships between node types
           - Use this schema information to inform your query construction
        
        2. **Then, construct an appropriate Cypher query** based on:
           - The user's natural language query: "{query}"
           - The schema information you obtained
           - Best practices for Cypher queries (use MATCH, WHERE, RETURN appropriately)
        
        3. **Execute the Cypher query using read-neo4j-cypher** with your constructed query
        
        4. **Process and interpret the results**:
           - CAPTURE the raw JSON results from your Neo4j queries
           - FORMAT **ALL** results into user-friendly bullet points or lists (do not truncate or summarize - include every single result found, even if some fields are null/empty)
           - For each result, provide key details like names, IDs, descriptions, and other relevant properties (show "N/A" or "Not available" for null fields)
           - Include incomplete records - do not filter out results with missing data
           - Provide insights and analysis of the findings
           - Explain what the results mean in the context of the original query
           - Identify any patterns or relationships in the data
           - Note any limitations or considerations
        
        Query to search: {query}
        
        IMPORTANT: Always start by calling get-neo4j-schema to understand the database structure before constructing any queries.
        """,
        expected_output="Structured analysis with comprehensive search results",
        agent=agent,
        output_pydantic=StructuredSearchResponse
    )
    
    return task

def create_similarity_search_task(agent, query_text: str, limit: int = 5):
    """Create a task for semantic similarity search."""
    return Task(
        description=f"""
        Find and analyze cases semantically similar to: "{query_text}"
        
        Steps to complete:
        1. Generate embeddings for the query text
        2. Retrieve the top {limit} most similar cases from the vector database
        3. Calculate and rank similarity scores
        4. Analyze common themes or patterns among the similar cases
        
        Query text: {query_text}
        Result limit: {limit}
        """,
        expected_output=f"A ranked list of the top {limit} most similar cases including: case identifiers, similarity scores, brief summaries, and analysis of common patterns or themes connecting these cases",
        agent=agent,
    )

# Document Processing Tasks  
def create_document_processing_task(agent, file_path: str, filename: str):
    """Create a task for AI-powered dynamic document processing."""
    return Task(
        description=f"""
        Process document "{filename}" using advanced AI-powered dynamic extraction that adapts to existing knowledge graph schema.
        
        Your process_document_tool now uses an enhanced 8-step AI-powered pipeline:
        1. **Schema Analysis**: Query Neo4j to understand existing node types, relationships, and properties
        2. **Document Text Extraction**: Extract clean text from the uploaded document
        3. **Node Identification**: Use AI to identify ALL possible entity types (nodes) in the document
        4. **Relationship Identification**: Use AI to identify ALL possible relationships between entities
        5. **Schema Alignment**: Compare document metadata with existing schema and align naming/structure
        6. **Content Extraction**: Use AI to extract actual data based on the aligned metadata structure
        7. **Cypher Generation**: Generate dynamic MERGE queries for seamless data integration
        8. **Neo4j Import**: Execute queries to merge new data with existing knowledge graph
        
        YOU MUST use the process_document_tool to complete this task. Call it exactly like this:
        
        process_document_tool(file_path="{file_path}", filename="{filename}")
        
        This tool will handle all 8 steps of the AI processing pipeline automatically.
        
        This AI approach ensures:
        - Consistency with existing schema where applicable
        - Discovery and integration of new entity types from documents
        - Flexible adaptation to different document formats
        - Intelligent relationship mapping
        
        Provide a comprehensive analysis of the AI processing results.
        """,
        expected_output="Comprehensive AI processing report containing: existing Neo4j schema analysis, complete inventory of identified document nodes/relationships, schema alignment results (what matched vs what's new), detailed extraction statistics by entity type, Cypher queries executed count, integration success status, and processing insights for optimization",
        agent=agent
    )

def create_embeddings_generation_task(agent, case_ids: List[str]):
    """Create a task for generating embeddings for specific cases."""
    return Task(
        description=f"""
        Generate vector embeddings for these case IDs: {', '.join(case_ids)}
        
        Steps to complete:
        1. Retrieve case content and summaries from Neo4j for each case ID
        2. Generate high-quality vector embeddings using the configured embedding model
        3. Store embeddings in the vector database with proper indexing
        4. Verify successful embedding creation and storage
        5. Update case records with embedding metadata
        
        Case IDs to process: {', '.join(case_ids)}
        Total cases: {len(case_ids)}
        """,
        expected_output="Embedding generation report containing: processing status for each case ID, embedding dimensions and model used, storage confirmation, any failed cases with error details, and performance metrics",
        agent=agent,
    )

# Enhanced Research Tasks
def create_research_task(agent, topic: str):
    """Create an enhanced research task with knowledge graph capabilities."""
    return Task(
        description=f"""
        Conduct comprehensive research on: "{topic}"
        
        Steps to complete:
        1. Execute structured knowledge graph queries for direct topic matches
        2. Perform semantic similarity searches for conceptually related content
        3. Analyze entity relationships and network patterns relevant to the topic
        4. Cross-reference findings to identify trends, patterns, or gaps
        5. Synthesize all findings into comprehensive research insights
        
        Research topic: {topic}
        """,
        expected_output="Comprehensive research report containing: direct search results from knowledge graph, similar cases found through semantic analysis, relationship network analysis, key trends and patterns identified, and strategic insights with supporting evidence",
        agent=agent,
    )

def create_writing_task(agent, research_context: str = None):
    """Create a writing task that incorporates research findings."""
    return Task(
        description=f"""
        Create engaging legal content based on provided research findings.
        
        Steps to complete:
        1. Analyze the research data and key findings
        2. Structure content with logical flow and clear hierarchy
        3. Write content that balances legal accuracy with accessibility
        4. Include proper citations and legal references
        5. Review for clarity, accuracy, and engagement
        
        {f"Research context provided: {research_context}" if research_context else "Use any research context available from previous tasks."}
        """,
        expected_output="Polished legal content including: executive summary, detailed analysis sections, relevant case citations, clear conclusions, and recommendations - all written in an engaging yet professionally accurate style",
        agent=agent,
    )

# Comprehensive Analysis Tasks
def create_case_analysis_task(agent, case_id: str):
    """Create a task for comprehensive analysis of a specific case."""
    return Task(
        description=f"""
        Perform comprehensive analysis of case: {case_id}
        
        Steps to complete:
        1. Retrieve complete case information from the knowledge graph
        2. Find semantically similar cases using vector similarity
        3. Map all entity relationships (parties, provisions, doctrines, etc.)
        4. Analyze the case's position within the broader legal network
        5. Identify strategic implications and precedential value
        
        Target case ID: {case_id}
        """,
        expected_output="Detailed case analysis containing: complete case profile, list of similar cases with similarity analysis, relationship network diagram, legal context assessment, and strategic insights with actionable recommendations",
        agent=agent,
    )

def create_pattern_analysis_task(agent, entity_type: str):
    """Create a task for analyzing patterns in the knowledge graph."""
    return Task(
        description=f"""
        Analyze patterns and trends for entity type: {entity_type}
        
        Steps to complete:
        1. Query knowledge graph for all entities of type "{entity_type}"
        2. Calculate frequency distributions and statistical measures
        3. Identify relationship patterns and network clusters
        4. Detect anomalies, outliers, or unusual patterns
        5. Generate actionable insights and strategic recommendations
        
        Entity type to analyze: {entity_type}
        """,
        expected_output=f"Pattern analysis report for {entity_type} containing: statistical summary and distributions, common relationship patterns identified, notable anomalies or outliers, trend analysis over time (if applicable), and strategic recommendations based on patterns discovered",
        agent=agent,
    )

