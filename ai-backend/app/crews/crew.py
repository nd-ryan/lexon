from crewai import Crew, Process
from .agents import create_research_agent, create_writer_agent
from .tasks import create_research_task, create_writing_task

def create_research_crew(topic: str):
    # Create agents
    research_agent = create_research_agent()
    writer_agent = create_writer_agent()
    
    # Create tasks
    research_task = create_research_task(topic, research_agent)
    writing_task = create_writing_task("Research findings", writer_agent)
    
    # Create crew
    crew = Crew(
        agents=[research_agent, writer_agent],
        tasks=[research_task, writing_task],
        process=Process.sequential,
        verbose=True,
    )
    
    return crew

async def run_research_crew(topic: str):
    crew = create_research_crew(topic)
    result = crew.kickoff()
    return result