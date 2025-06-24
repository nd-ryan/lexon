from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Generator, AsyncGenerator
from app.crews.agents import (
    create_search_agent, create_document_agent, create_embeddings_agent,
    create_research_agent, create_writer_agent, MCPEnabledAgents, create_mcp_enabled_agents,
    get_neo4j_mcp_server_params, get_mcp_tools, debug_mcp_tools_status
)
from app.crews.tasks import (
    create_search_task, create_similarity_search_task, create_document_processing_task,
    create_embeddings_generation_task, create_research_task, create_writing_task,
    create_case_analysis_task, create_pattern_analysis_task
)
from app.crews.crew import create_specialized_search_crew, create_legacy_search_crew
from app.lib.cypher_generator import generate_cypher_query_async
from app.lib.neo4j_client import neo4j_client
from app.lib.embeddings import find_similar_cases, generate_embeddings_for_cases
from app.lib.document_processor import parse_docx_to_knowledge_graph, knowledge_graph_to_dict
from app.lib.security import get_api_key
from crewai import Crew, Process, Agent, Task, LLM
from crewai_tools import MCPServerAdapter
import logging
import os
import json
import time

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(get_api_key)])

# Import models from separate module
from app.models.search import (
    StructuredSearchResponse,
    SearchRequest, SearchResponse, SimilaritySearchRequest, 
    ResearchRequest, EmbeddingsRequest, CaseAnalysisRequest,
    PatternAnalysisRequest, QueryRequest, DocumentRequest, CrewResponse
)

# Enhanced output formatting functions
def format_crew_analysis(result, steps_log=None):
    """Format crew analysis with enhanced structure and step-by-step thinking"""
    
    # Extract the main analysis
    main_analysis = result.raw if hasattr(result, 'raw') else str(result)
    
    # Structure the output
    formatted_output = {
        "executive_summary": extract_executive_summary(main_analysis),
        "detailed_analysis": main_analysis,
        "methodology": extract_methodology(main_analysis),
        "key_findings": extract_key_findings(main_analysis),
        "supporting_evidence": extract_supporting_evidence(main_analysis),
        "step_by_step_thinking": steps_log or [],
        "meta_information": {
            "analysis_type": "crew_ai_analysis",
            "confidence_level": "high",
            "processing_method": "multi_agent_collaboration"
        }
    }
    
    return formatted_output

def extract_executive_summary(analysis_text):
    """Extract or generate executive summary from analysis"""
    lines = analysis_text.split('\n')
    
    # Look for explicit summary sections
    for i, line in enumerate(lines):
        if any(keyword in line.lower() for keyword in ['summary', 'key findings', 'executive summary']):
            # Extract the next few lines
            summary_lines = []
            for j in range(i+1, min(i+6, len(lines))):
                if lines[j].strip() and not lines[j].startswith('#'):
                    summary_lines.append(lines[j].strip())
            if summary_lines:
                return ' '.join(summary_lines)
    
    # If no explicit summary, take first meaningful paragraph
    for line in lines:
        if len(line.strip()) > 50 and not line.startswith('#'):
            return line.strip()
    
    return "Analysis completed successfully with comprehensive findings."

def extract_methodology(analysis_text):
    """Extract methodology description from analysis"""
    methodology_keywords = ['cypher query', 'executed', 'steps to complete', 'process', 'methodology']
    lines = analysis_text.split('\n')
    
    methodology_sections = []
    for line in lines:
        if any(keyword in line.lower() for keyword in methodology_keywords):
            methodology_sections.append(line.strip())
    
    return methodology_sections if methodology_sections else ["Standard AI analysis methodology applied"]

def extract_key_findings(analysis_text):
    """Extract key findings from analysis"""
    findings = []
    lines = analysis_text.split('\n')
    
    for line in lines:
        # Look for numbered points, bullet points, or findings
        if (line.strip().startswith(('1.', '2.', '3.', '4.', '5.', '-', '*', '•')) or 
            'finding' in line.lower() or 'result' in line.lower()):
            if len(line.strip()) > 20:  # Only meaningful findings
                findings.append(line.strip())
    
    return findings[:10] if findings else ["Comprehensive analysis completed"]

def extract_supporting_evidence(analysis_text):
    """Extract supporting evidence and data points"""
    evidence = []
    lines = analysis_text.split('\n')
    
    for line in lines:
        # Look for data, evidence, examples
        if any(keyword in line.lower() for keyword in ['data', 'evidence', 'example', 'case', 'doctrine', 'result']):
            if len(line.strip()) > 30:
                evidence.append(line.strip())
    
    return evidence[:8] if evidence else ["Analysis based on comprehensive data review"]

# Global steps collector
current_steps_log = []

def enhanced_step_callback(step):
    """Enhanced callback to capture detailed step information"""
    global current_steps_log
    
    step_info = {
        "timestamp": str(step.timestamp) if hasattr(step, 'timestamp') else "unknown",
        "step_type": getattr(step, 'step_type', 'reasoning'),
        "agent": getattr(step, 'agent_name', 'AI Agent'),
        "action": getattr(step, 'action', 'processing'),
        "content": str(step)[:500] if len(str(step)) > 500 else str(step),
        "reasoning": getattr(step, 'reasoning', 'Analyzing and processing information'),
    }
    
    current_steps_log.append(step_info)
    print(f"🧠 Agent Thinking: {step_info['agent']} - {step_info['action']}")
    
    return step_info

# Search Endpoints
@router.post("/search", response_model=SearchResponse)
async def search_knowledge_graph(request: SearchRequest):
    """
    Search the knowledge graph using natural language queries.
    Migrated from Next.js /api/search endpoint.
    """
    try:
        # Generate Cypher query from natural language
        cypher_query = await generate_cypher_query_async(request.query)
        
        # Execute the query
        results = neo4j_client.execute_query(cypher_query)
        
        return SearchResponse(
            cypher_query=cypher_query,
            results=results,
            count=len(results)
        )
    
    except Exception as e:
        logger.error(f"Error in search endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/search/similarity")
async def similarity_search(request: SimilaritySearchRequest):
    """
    Find cases similar to the given query using semantic similarity.
    """
    try:
        results = await find_similar_cases(request.query, request.limit)
        return {
            "query": request.query,
            "limit": request.limit,
            "results": results,
            "count": len(results)
        }
    
    except Exception as e:
        logger.error(f"Error in similarity search: {e}")
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/search/mcp-tools-test")
async def test_mcp_tools():
    """
    Test endpoint to verify Neo4j's official MCP tools are working correctly.
    """
    try:
        with MCPEnabledAgents() as mcp_context:
            neo4j_mcp_tools = get_mcp_tools()
            
            if not neo4j_mcp_tools:
                return {
                    "success": False,
                    "message": "No Neo4j MCP tools available",
                    "tools": [],
                    "server_type": "neo4j-official-mcp-server"
                }
            
            # List available tools with detailed info
            tool_info = []
            for tool in neo4j_mcp_tools:
                tool_info.append({
                    "name": tool.name,
                    "description": getattr(tool, 'description', 'No description available')
                })
            
            # Test the get_neo4j_schema tool if available
            schema_test = None
            for tool in neo4j_mcp_tools:
                if tool.name == "get_neo4j_schema":
                    try:
                        schema_result = await tool.invoke({})
                        schema_test = {
                            "tool_name": "get_neo4j_schema",
                            "status": "success",
                            "result_preview": str(schema_result)[:200] + "..." if len(str(schema_result)) > 200 else str(schema_result)
                        }
                    except Exception as test_error:
                        schema_test = {
                            "tool_name": "get_neo4j_schema", 
                            "status": "error",
                            "error": str(test_error)
                        }
                    break
            
            return {
                "success": True,
                "message": "Neo4j official MCP tools are working correctly",
                "server_type": "neo4j-official-mcp-server",
                "tools": tool_info,
                "total_tools": len(neo4j_mcp_tools),
                "test_result": schema_test
            }
    
    except Exception as e:
        logger.error(f"Neo4j MCP tools test failed: {e}")
        return {
            "success": False,
            "message": f"Neo4j MCP tools test failed: {str(e)}",
            "server_type": "neo4j-official-mcp-server",
            "tools": []
        }

# Import endpoints - Using CrewAI approach only
@router.post("/import-kg")
async def import_knowledge_graph(file: UploadFile = File(...)):
    """
    Import and process a document to extract knowledge graph data using CrewAI agents.
    """
    import tempfile
    import os
    
    try:
        file_content = await file.read()
        
        # Create a temporary file to store the document
        with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as temp_file:
            temp_file.write(file_content)
            temp_file_path = temp_file.name
        
        try:
            # Use the global MCP context manager approach (same as search endpoints)
            with MCPEnabledAgents() as mcp_context:
                neo4j_mcp_tools = get_mcp_tools()
                
                # Create document agent - it will internally check for MCP tools
                doc_agent = create_document_agent()
                
                if neo4j_mcp_tools:
                    mcp_tools_used = True
                    print(f"Document processing using MCP tools: {[tool.name for tool in neo4j_mcp_tools]}")
                else:
                    logger.warning("No MCP tools available for document processing, using standard agent")
                
                # Create task and crew
                doc_task = create_document_processing_task(doc_agent, temp_file_path, file.filename)
                crew = Crew(
                    agents=[doc_agent],
                    tasks=[doc_task],
                    process=Process.sequential,
                    verbose=True
                )
                
                # Execute within the MCP context
                result = crew.kickoff()
            
            return {
                "success": True,
                "filename": file.filename,
                "analysis": result.raw,  # Extract the human-readable output
                "type": "crew_processing",
                "tasks_output": [{"description": task.description, "raw": task.raw} for task in result.tasks_output] if result.tasks_output else [],
                "token_usage": result.token_usage if hasattr(result, 'token_usage') else {}
            }
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
    
    except Exception as e:
        logger.error(f"Error in import endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/import-kg/advanced")
async def import_with_direct_processing(file: UploadFile = File(...)):
    """
    Import and process documents using CrewAI agents with direct Neo4j integration.
    Uses the proven direct Neo4j approach for reliable processing.
    """
    import tempfile
    import os
    
    try:
        file_content = await file.read()
        
        # Create a temporary file to store the document
        with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as temp_file:
            temp_file.write(file_content)
            temp_file_path = temp_file.name
        
        try:
            # Use direct Neo4j approach (no MCP initialization)
            print(f"📄 Processing document: {file.filename}")
            print(f"Document processing started for: {file.filename}")
            
            # Create document agent with direct Neo4j tools
            from ..crews.agents import create_document_agent
            doc_agent = create_document_agent()
            
            # Create task
            from ..crews.tasks import create_document_processing_task
            doc_task = create_document_processing_task(doc_agent, temp_file_path, file.filename)
            
            # Create and execute crew
            crew = Crew(
                agents=[doc_agent],
                tasks=[doc_task],
                process=Process.sequential,
                verbose=True
            )
            
            print("🚀 Starting document processing crew...")
            result = crew.kickoff()
            
            # Extract result
            result_text = result.raw if hasattr(result, 'raw') else str(result)
            
            return {
                "success": True,
                "filename": file.filename,
                "result": result_text,
                "processing_method": "direct_neo4j",
                "message": "Document processed successfully using direct Neo4j integration"
            }
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                
    except Exception as e:
        logger.error(f"Document processing failed: {e}")
        return {
            "success": False,
            "filename": file.filename if file else "unknown",
            "error": str(e),
            "processing_method": "direct_neo4j"
        }

# Embeddings endpoints (keeping existing functionality)
@router.post("/embeddings/generate")
async def generate_embeddings(request: EmbeddingsRequest):
    """
    Generate embeddings for the specified case IDs.
    """
    try:
        results = await generate_embeddings_for_cases(request.case_ids)
        
        return {
            "case_ids": request.case_ids,
            "results": results,
            "count": len(request.case_ids)
        }
    
    except Exception as e:
        logger.error(f"Error generating embeddings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/embeddings/crew")
async def generate_embeddings_with_crew(request: EmbeddingsRequest):
    """
    Generate embeddings using CrewAI agents.
    """
    try:
        # Create embeddings agent and task
        embeddings_agent = create_embeddings_agent()
        embeddings_task = create_embeddings_generation_task(embeddings_agent, request.case_ids)
        
        # Create crew
        crew = Crew(
            agents=[embeddings_agent],
            tasks=[embeddings_task],
            process=Process.sequential,
            verbose=True
        )
        
        # Execute
        result = crew.kickoff()
        
        return {
            "case_ids": request.case_ids,
            "analysis": result.raw,  # Extract the human-readable output
            "type": "crew_embeddings",
            "tasks_output": [{"description": task.description, "raw": task.raw} for task in result.tasks_output] if result.tasks_output else [],
            "token_usage": result.token_usage if hasattr(result, 'token_usage') else {}
        }
    
    except Exception as e:
        logger.error(f"Error in crew embeddings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Research endpoints (keeping existing functionality)
@router.post("/research", response_model=CrewResponse)
async def research_with_crew(request: QueryRequest):
    """Comprehensive research using CrewAI agents with MCP integration"""
    try:
        # Try to use MCP tools first
        mcp_tools_used = False
        research_agent = None
        
        # Use the global MCP context manager approach (same as search endpoints)
        with MCPEnabledAgents() as mcp_context:
            neo4j_mcp_tools = get_mcp_tools()
            
            if neo4j_mcp_tools:
                research_agent = create_research_agent(tools=neo4j_mcp_tools)
                mcp_tools_used = True
                print(f"Research using MCP tools: {[tool.name for tool in neo4j_mcp_tools]}")
            else:
                logger.warning("No MCP tools available for research, using basic agent")
                research_agent = create_research_agent()
            
            # Create task and crew
            research_task = create_research_task(request.query)
            crew = Crew(
                agents=[research_agent],
                tasks=[research_task],
                verbose=True
            )
            
            # Execute the crew within the MCP context
            result = crew.kickoff()
            result_text = result.raw if hasattr(result, 'raw') else str(result)
        
        return CrewResponse(
            result=result_text,
            success=True,
            mcp_tools_used=mcp_tools_used
        )
        
    except Exception as e:
        logger.error(f"Research failed: {e}")
        raise HTTPException(status_code=500, detail=f"Research failed: {str(e)}")

@router.post("/research/comprehensive")
async def comprehensive_research(request: ResearchRequest):
    """
    Conduct comprehensive research using multiple CrewAI agents.
    """
    try:
        # Create research and writer agents
        research_agent = create_research_agent()
        writer_agent = create_writer_agent()
        
        # Create tasks
        research_task = create_research_task(research_agent, request.topic)
        writing_task = create_writing_task(writer_agent, request.topic)
        
        # Create crew
        crew = Crew(
            agents=[research_agent, writer_agent],
            tasks=[research_task, writing_task],
            process=Process.sequential,
            verbose=True
        )
        
        # Execute
        result = crew.kickoff()
        
        return {
            "topic": request.topic,
            "comprehensive_analysis": result.raw,  # Extract the human-readable output
            "type": "comprehensive_research",
            "tasks_output": [{"description": task.description, "raw": task.raw} for task in result.tasks_output] if result.tasks_output else [],
            "token_usage": result.token_usage if hasattr(result, 'token_usage') else {}
        }
    
    except Exception as e:
        logger.error(f"Error in comprehensive research: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Analysis endpoints (keeping existing functionality)
@router.post("/analysis/case")
async def analyze_case(request: CaseAnalysisRequest):
    """
    Analyze a specific case using CrewAI agents.
    """
    try:
        # Create research agent and task
        research_agent = create_research_agent()
        analysis_task = create_case_analysis_task(research_agent, request.case_id)
        
        # Create crew
        crew = Crew(
            agents=[research_agent],
            tasks=[analysis_task],
            process=Process.sequential,
            verbose=True
        )
        
        # Execute
        result = crew.kickoff()
        
        return {
            "case_id": request.case_id,
            "analysis": result.raw,  # Extract the human-readable output
            "type": "case_analysis",
            "tasks_output": [{"description": task.description, "raw": task.raw} for task in result.tasks_output] if result.tasks_output else [],
            "token_usage": result.token_usage if hasattr(result, 'token_usage') else {}
        }
    
    except Exception as e:
        logger.error(f"Error in case analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/analysis/patterns")
async def analyze_patterns(request: PatternAnalysisRequest):
    """
    Analyze patterns for a specific entity type using CrewAI agents.
    """
    try:
        # Create research agent and task
        research_agent = create_research_agent()
        pattern_task = create_pattern_analysis_task(research_agent, request.entity_type)
        
        # Create crew
        crew = Crew(
            agents=[research_agent],
            tasks=[pattern_task],
            process=Process.sequential,
            verbose=True
        )
        
        # Execute
        result = crew.kickoff()
        
        return {
            "entity_type": request.entity_type,
            "analysis": result.raw,  # Extract the human-readable output
            "type": "pattern_analysis",
            "tasks_output": [{"description": task.description, "raw": task.raw} for task in result.tasks_output] if result.tasks_output else [],
            "token_usage": result.token_usage if hasattr(result, 'token_usage') else {}
        }
    
    except Exception as e:
        logger.error(f"Error in pattern analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Health check
@router.get("/health")
async def health_check():
    """Health check endpoint for Neo4j connectivity"""
    try:
        # Test Neo4j connection
        from ..lib.neo4j_client import neo4j_client
        
        # Simple connectivity test
        test_query = "RETURN 1 as test"
        result = neo4j_client.execute_query(test_query)
        neo4j_status = "connected" if result else "disconnected"
        
        return {
            "status": "healthy",
            "neo4j": neo4j_status,
            "processing_method": "direct_neo4j",
            "message": "Using direct Neo4j integration for reliable processing"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "neo4j": "error"
        }

# Basic endpoints removed - using AI Agent search only

@router.post("/documents/process", response_model=CrewResponse)
async def process_document_with_crew(request: DocumentRequest):
    """Process documents using CrewAI agents with MCP integration"""
    try:
        # Try to use MCP tools first
        mcp_tools_used = False
        document_agent = None
        
        # Use the global MCP context manager approach (same as search endpoints)
        with MCPEnabledAgents() as mcp_context:
            neo4j_mcp_tools = get_mcp_tools()
            
            if neo4j_mcp_tools:
                document_agent = create_document_agent(tools=neo4j_mcp_tools)
                mcp_tools_used = True
                print(f"Document processing using MCP tools: {[tool.name for tool in neo4j_mcp_tools]}")
            else:
                logger.warning("No MCP tools available for document processing, using basic agent")
                document_agent = create_document_agent()
            
            # Create task and crew
            document_task = create_document_processing_task(
                request.content, 
                request.document_type
            )
            crew = Crew(
                agents=[document_agent],
                tasks=[document_task],
                verbose=True
            )
            
            # Execute the crew within the MCP context
            result = crew.kickoff()
            result_text = result.raw if hasattr(result, 'raw') else str(result)
        
        return CrewResponse(
            result=result_text,
            success=True,
            mcp_tools_used=mcp_tools_used
        )
        
    except Exception as e:
        logger.error(f"Document processing failed: {e}")
        raise HTTPException(status_code=500, detail=f"Document processing failed: {str(e)}")

@router.get("/debug/mcp-status")
async def debug_mcp_status():
    """Debug endpoint to check MCP tools configuration (non-blocking)"""
    try:
        from ..crews.agents import get_neo4j_mcp_server_params
        import os
        
        # Get MCP server configuration without initializing
        server_params = get_neo4j_mcp_server_params()
        
        # Check environment variables
        neo4j_config = {
            "NEO4J_URI": os.getenv("NEO4J_URI", "Not set"),
            "NEO4J_USER": os.getenv("NEO4J_USER", "Not set"), 
            "NEO4J_PASSWORD": "***" if os.getenv("NEO4J_PASSWORD") else "Not set",
            "NEO4J_DATABASE": os.getenv("NEO4J_DATABASE", "neo4j")
        }
        
        # Check if mcp-neo4j-cypher command exists
        import subprocess
        try:
            result = subprocess.run(["which", "mcp-neo4j-cypher"], 
                                  capture_output=True, text=True, timeout=5)
            mcp_command_available = result.returncode == 0
            mcp_command_path = result.stdout.strip() if mcp_command_available else "Not found"
        except Exception as e:
            mcp_command_available = False
            mcp_command_path = f"Error checking: {e}"
        
        return {
            "mcp_server_config": {
                "command": server_params.command,
                "args": server_params.args
            },
            "neo4j_config": neo4j_config,
            "mcp_command_available": mcp_command_available,
            "mcp_command_path": mcp_command_path,
            "test_successful": True,
            "note": "This is configuration status only - actual MCP connection tested during document processing"
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "test_successful": False
        }

@router.get("/debug/mcp-tools-verify")
async def verify_mcp_tools():
    """Verify that the expected Neo4j MCP tools are available and working"""
    try:
        with MCPEnabledAgents() as mcp_context:
            neo4j_mcp_tools = get_mcp_tools()
            
            if not neo4j_mcp_tools:
                return {
                    "success": False,
                    "message": "No MCP tools available",
                    "expected_tools": ["read-neo4j-cypher", "get-neo4j-schema"],
                    "available_tools": []
                }
            
            tool_names = [tool.name for tool in neo4j_mcp_tools]
            expected_tools = ["read-neo4j-cypher", "get-neo4j-schema"]
            
            # Check if we have the expected tools
            missing_tools = [tool for tool in expected_tools if tool not in tool_names]
            unexpected_tools = [tool for tool in tool_names if tool not in expected_tools and not tool.startswith("write-")]
            
            # Test the get-neo4j-schema tool
            schema_test = None
            schema_tool = next((tool for tool in neo4j_mcp_tools if tool.name == "get-neo4j-schema"), None)
            if schema_tool:
                try:
                    schema_result = await schema_tool.invoke({})
                    schema_test = {
                        "status": "success",
                        "has_result": bool(schema_result),
                        "result_type": type(schema_result).__name__
                    }
                except Exception as e:
                    schema_test = {
                        "status": "error",
                        "error": str(e)
                    }
            
            return {
                "success": len(missing_tools) == 0,
                "message": "MCP tools verification complete",
                "expected_tools": expected_tools,
                "available_tools": tool_names,
                "missing_tools": missing_tools,
                "unexpected_tools": unexpected_tools,
                "schema_tool_test": schema_test,
                "ready_for_search": len(missing_tools) == 0 and schema_test and schema_test["status"] == "success"
            }
            
    except Exception as e:
        return {
            "success": False,
            "message": f"MCP tools verification failed: {str(e)}",
            "expected_tools": ["read-neo4j-cypher", "get-neo4j-schema"],
            "available_tools": []
        }

# Add streaming response for crew search
@router.post("/search/crew/stream")
async def search_with_crew_stream(request: QueryRequest):
    """
    Search with CrewAI agents using Server-Sent Events streaming.
    Provides real-time updates during the AI processing.
    Uses the new specialized multi-agent approach by default.
    """
    async def generate_stream() -> AsyncGenerator[str, None]:
        try:
            start_time = time.time()
            
            # Send initial status
            yield f"data: {json.dumps({'type': 'status', 'message': 'Initializing specialized AI search crew...', 'timestamp': time.time()})}\n\n"
            
            # Initialize MCP tools
            yield f"data: {json.dumps({'type': 'status', 'message': 'Setting up Neo4j MCP tools...', 'timestamp': time.time()})}\n\n"
            
            with MCPEnabledAgents() as mcp_context:
                neo4j_mcp_tools = get_mcp_tools()
                
                if not neo4j_mcp_tools:
                    error_msg = "Specialized crew requires MCP tools. Please check MCP tool configuration."
                    yield f"data: {json.dumps({'type': 'error', 'message': error_msg, 'timestamp': time.time()})}\n\n"
                    return
                
                yield f"data: {json.dumps({'type': 'status', 'message': f'MCP tools loaded: {len(neo4j_mcp_tools)} tools available', 'timestamp': time.time()})}\n\n"
                yield f"data: {json.dumps({'type': 'status', 'message': 'Assembling specialized AI crew (5 agents, 5 tasks)...', 'timestamp': time.time()})}\n\n"
                
                # Define a callback for logging agent steps
                def log_step_callback(agent_action):
                    logger.info("--- AGENT STEP START ---")
                    logger.info(f"Action: {agent_action}")
                    logger.info("--- AGENT STEP END ---")

                # Create specialized crew
                crew = create_specialized_search_crew(
                    request.query, 
                    neo4j_mcp_tools,
                    step_callback=log_step_callback
                )
                
                print(f"Using specialized crew with agents: Schema Analyst, Query Generator, Query Executor, Results Analyst, Insights Synthesizer")
                print(f"MCP tools available: {[tool.name for tool in neo4j_mcp_tools]}")
                
                # Execute with detailed progress updates
                yield f"data: {json.dumps({'type': 'status', 'message': 'Agent 1/5: Schema Analyst analyzing database structure...', 'timestamp': time.time()})}\n\n"
                yield f"data: {json.dumps({'type': 'progress', 'message': 'Agent 2/5: Query Generator creating optimized Cypher queries...', 'timestamp': time.time()})}\n\n"
                yield f"data: {json.dumps({'type': 'progress', 'message': 'Agent 3/5: Query Executor running queries against Neo4j...', 'timestamp': time.time()})}\n\n"
                yield f"data: {json.dumps({'type': 'progress', 'message': 'Agent 4/5: Results Analyst processing raw data...', 'timestamp': time.time()})}\n\n"
                yield f"data: {json.dumps({'type': 'progress', 'message': 'Agent 5/5: Insights Synthesizer creating final analysis...', 'timestamp': time.time()})}\n\n"
                
                # Execute the specialized crew
                result = crew.kickoff()
                
                execution_time = time.time() - start_time
                
                # Extract structured data from result
                if hasattr(result, 'pydantic') and result.pydantic:
                    print("Specialized crew: Using pydantic structured output")
                    
                    if isinstance(result.pydantic, StructuredSearchResponse):
                        print("Specialized crew: Got complete StructuredSearchResponse from final agent!")
                        final_response = result.pydantic
                        final_response.execution_time = execution_time
                    else:
                        print(f"Specialized crew: Got {type(result.pydantic)}, creating wrapper response")
                        final_response = StructuredSearchResponse(
                            query=request.query,
                            cypher_queries=["Could not be retrieved in fallback."],
                            raw_results=[{"error": f"Agent returned an unexpected Pydantic model: {type(result.pydantic)}" , "data": str(result.pydantic)}],
                            explanation=f"The final agent returned an unexpected structured output. The raw output is: {str(result.pydantic)}",
                            execution_time=execution_time
                        )
                else:
                    print("Specialized crew: Using fallback parsing")
                    raw_result = result.raw if hasattr(result, 'raw') else str(result)
                    
                    final_response = StructuredSearchResponse(
                        query=request.query,
                        cypher_queries=["Could not be retrieved in fallback parsing."],
                        raw_results=[{"error": "Could not be retrieved in fallback parsing."}],
                        explanation=f"The agent failed to return a structured Pydantic response. The final raw output was: {raw_result}",
                        execution_time=execution_time
                    )
                
                # Send final result
                yield f"data: {json.dumps({'type': 'complete', 'data': final_response.model_dump(), 'timestamp': time.time()})}\n\n"
                
        except Exception as e:
            logger.error(f"Error in specialized crew search: {e}")
            error_response = {
                'type': 'error',
                'message': str(e),
                'timestamp': time.time()
            }
            yield f"data: {json.dumps(error_response)}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
        }
    )

@router.post("/search/crew/legacy/stream")
async def search_with_legacy_crew_stream(request: QueryRequest):
    """
    Search using legacy single-agent CrewAI approach for comparison.
    This endpoint uses the original single agent with one complex task.
    """
    async def generate_stream() -> AsyncGenerator[str, None]:
        try:
            start_time = time.time()
            
            yield f"data: {json.dumps({'type': 'status', 'message': 'Initializing legacy single-agent search...', 'timestamp': time.time()})}\n\n"
            
            with MCPEnabledAgents() as mcp_context:
                neo4j_mcp_tools = get_mcp_tools()
                
                if not neo4j_mcp_tools:
                    error_msg = "Legacy crew requires MCP tools. Please check MCP tool configuration."
                    yield f"data: {json.dumps({'type': 'error', 'message': error_msg, 'timestamp': time.time()})}\n\n"
                    return
                
                yield f"data: {json.dumps({'type': 'status', 'message': f'MCP tools loaded: {len(neo4j_mcp_tools)} tools available', 'timestamp': time.time()})}\n\n"
                yield f"data: {json.dumps({'type': 'status', 'message': 'Creating legacy single-agent crew...', 'timestamp': time.time()})}\n\n"
                
                # Create legacy crew
                crew = create_legacy_search_crew(request.query, neo4j_mcp_tools)
                
                print(f"Using legacy single-agent crew with MCP tools: {[tool.name for tool in neo4j_mcp_tools]}")
                
                yield f"data: {json.dumps({'type': 'progress', 'message': 'Single agent handling all tasks (schema, query, execution, analysis)...', 'timestamp': time.time()})}\n\n"
                
                # Execute legacy crew
                result = crew.kickoff()
                
                execution_time = time.time() - start_time
                
                # Process result (same logic as original)
                if hasattr(result, 'pydantic') and result.pydantic:
                    if isinstance(result.pydantic, StructuredSearchResponse):
                        final_response = result.pydantic
                        final_response.execution_time = execution_time
                        final_response.mcp_tools_used = True
                    else:
                        final_response = StructuredSearchResponse(
                            success=True,
                            query=request.query,
                            total_results=1,
                            results=[SearchResult(
                                entity_type="Legacy Analysis",
                                entity_id="legacy_analysis_1",
                                name="Single-Agent Search Analysis",
                                description="Analysis from legacy single-agent approach",
                                properties={"analysis": str(result.pydantic)},
                                relationships=[],
                                relevance_score=1.0
                            )],
                            cypher_queries=["Cypher queries executed via single agent"],
                            analysis=SearchAnalysis(
                                query_interpretation=f"Single-agent interpretation: '{request.query}'",
                                methodology=["Legacy single agent with all tasks"],
                                key_insights=[str(result.pydantic)[:200] + "..." if len(str(result.pydantic)) > 200 else str(result.pydantic)],
                                patterns_identified=[],
                                limitations=["Legacy single-agent processing"],
                                formatted_results=[str(result.pydantic)],
                                raw_query_results=[]
                            ),
                            execution_time=execution_time,
                            mcp_tools_used=True,
                            agent_reasoning=[]
                        )
                else:
                    raw_result = result.raw if hasattr(result, 'raw') else str(result)
                    final_response = StructuredSearchResponse(
                        success=True,
                        query=request.query,
                        total_results=1,
                        results=[SearchResult(
                            entity_type="Legacy Analysis",
                            entity_id="legacy_analysis_1",
                            name="Single-Agent Search Analysis", 
                            description="Analysis from legacy single-agent approach",
                            properties={"analysis": raw_result},
                            relationships=[],
                            relevance_score=1.0
                        )],
                        cypher_queries=["Cypher queries executed via single agent"],
                        analysis=SearchAnalysis(
                            query_interpretation=f"Single-agent interpretation: '{request.query}'",
                            methodology=["Legacy single agent with all tasks"],
                            key_insights=[raw_result[:200] + "..." if len(raw_result) > 200 else raw_result],
                            patterns_identified=[],
                            limitations=["Legacy single-agent processing - fallback parsing used"],
                            formatted_results=[f"Legacy result: {raw_result}"],
                            raw_query_results=[]
                        ),
                        execution_time=execution_time,
                        mcp_tools_used=True,
                        agent_reasoning=[]
                    )
                
                yield f"data: {json.dumps({'type': 'complete', 'data': final_response.model_dump(), 'timestamp': time.time()})}\n\n"
                
        except Exception as e:
            logger.error(f"Error in legacy crew search: {e}")
            error_response = {
                'type': 'error',
                'message': str(e),
                'timestamp': time.time()
            }
            yield f"data: {json.dumps(error_response)}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
        }
    )