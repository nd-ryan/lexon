from crewai import Task
from typing import List

# Search and Query Tasks
def create_search_task(agent, query: str):
    """Create a task for natural language knowledge graph search."""
    return Task(
        description=f"""
        Execute a knowledge graph search for: "{query}"
        
        Steps to complete:
        1. Convert this natural language query into an appropriate Cypher query
        2. Execute the query against the Neo4j knowledge graph  
        3. Process and interpret the raw results
        4. Identify the most relevant findings
        
        Query to search: {query}
        """,
        expected_output="A structured analysis containing: the generated Cypher query, key findings from the results, relevant entities and relationships discovered, and insights about the query results",
        agent=agent,
    )

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
def create_document_processing_task(agent, file_content: bytes, filename: str):
    """Create a task for processing documents into knowledge graphs."""
    return Task(
        description=f"""
        Process document "{filename}" and extract knowledge graph data.
        
        Steps to complete:
        1. Parse the document content to extract legal entities (cases, parties, provisions, doctrines, etc.)
        2. Identify and map relationships between extracted entities
        3. Structure the extracted data into knowledge graph format
        4. Validate data quality and completeness
        5. Load the structured data into Neo4j
        6. Generate summary statistics of extracted content
        
        Document to process: {filename}
        """,
        expected_output="Processing report containing: entity extraction counts by type, relationship mappings created, data quality assessment, Neo4j loading status, and any processing issues or recommendations",
        agent=agent,
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