"""
Agent callbacks and utility functions for CrewAI workflows.

This module contains callback functions and utilities that support
agent operations and workflow monitoring.
"""


def agent_step_callback(step):
    """
    Callback function to log each step of agent reasoning.
    
    This function captures and logs agent thinking steps for monitoring
    and debugging purposes.
    
    Args:
        step: The agent step object containing step information
        
    Returns:
        dict: Formatted step information for logging
    """
    print(f"🤔 Agent Step: {step}")
    return {
        "step_type": getattr(step, 'step_type', 'unknown'),
        "content": str(step),
        "timestamp": str(step.timestamp) if hasattr(step, 'timestamp') else None,
        "agent_name": getattr(step, 'agent_name', 'unknown')
    } 