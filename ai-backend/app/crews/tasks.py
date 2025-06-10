from crewai import Task

def create_research_task(topic: str, agent):
    return Task(
        description=f"Research the topic: {topic}. Gather key information, trends, and insights.",
        expected_output="A comprehensive research report with key findings and insights",
        agent=agent,
    )

def create_writing_task(research_context: str, agent):
    return Task(
        description=f"Based on this research: {research_context}, write an engaging article or summary.",
        expected_output="A well-written article or summary based on the research findings",
        agent=agent,
    )