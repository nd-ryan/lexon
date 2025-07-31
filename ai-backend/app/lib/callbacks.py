"""
Agent callbacks and utility functions for CrewAI workflows.

This module contains callback functions and utilities that support
agent operations and workflow monitoring.
"""

from app.lib.logging_config import setup_logger
import time

# Use our custom logger setup
logger = setup_logger("agent-callbacks")

# Global tracking for agent timing
_crew_start_time = None
_agent_finish_times = []
_task_names = ["Query Generation", "Query Execution", "Insights Synthesis"]


def reset_agent_timing():
    """Reset agent timing for a new search job."""
    global _crew_start_time, _agent_finish_times
    _crew_start_time = time.time()
    _agent_finish_times = []
    logger.debug("🔄 Agent timing reset for new search")


def agent_step_callback(step):
    """
    Callback function to log each step of agent reasoning with timing.
    
    This function captures and logs agent thinking steps for monitoring
    and debugging purposes, including timing information.
    
    Args:
        step: The agent step object containing step information
        
    Returns:
        dict: Formatted step information for logging
    """
    current_time = time.time()
    step_class = step.__class__.__name__
    
    if step_class == "AgentAction":
        # Agent is about to use a tool
        tool_name = getattr(step, 'tool', 'unknown_tool')
        logger.info(f"🔧 Using tool: {tool_name}")
        
    elif step_class == "ToolResult": 
        # Tool execution completed - show results preview
        result = getattr(step, 'result', '')
        if isinstance(result, str) and len(result) > 100:
            result_preview = result[:100] + "..."
        else:
            result_preview = str(result)
        logger.info(f"✅ Tool result: {result_preview}")
        
    elif step_class == "AgentFinish":
        # Track AgentFinish events to calculate task durations
        _agent_finish_times.append(current_time)
        task_number = len(_agent_finish_times)
        task_name = _task_names[task_number - 1] if task_number <= len(_task_names) else f"Task {task_number}"
        
        if task_number == 1:
            # First agent - calculate duration from crew start time
            duration = current_time - _crew_start_time
            logger.info(f"✅ Agent Completed: {task_name} (took {duration:.2f}s)")
        else:
            # Calculate duration from previous agent finish time
            # This gives us the actual execution time for this agent
            previous_finish_time = _agent_finish_times[task_number - 2]
            duration = current_time - previous_finish_time
            logger.info(f"✅ Agent Completed: {task_name} (took {duration:.2f}s)")
    
    return {
        "step_type": step_class,
        "content": str(step),
        "timestamp": None,
        "agent_name": f"Agent-{len(_agent_finish_times) + 1}",
        "logged_at": current_time
    } 