from crewai import Task
from typing import List

# Search and Query Tasks
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
        expected_output="A comprehensive analysis including: how you interpreted the query, the methodology used (step-by-step process), formatted results as bullet points or lists (MUST include ALL results found - do not truncate, summarize, or filter out incomplete records), key insights from the search results, patterns identified in the data, any limitations or considerations, and the complete raw JSON results from your Neo4j queries.",
        agent=agent,
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

