from fastapi import APIRouter, HTTPException
from app.crews.agents import create_research_agent, create_writer_agent
from app.crews.tasks import create_research_task, create_writing_task
from crewai import Crew, Process

router = APIRouter()

def create_research_crew(topic: str):
    # Create agents
    research_agent = create_research_agent()
    writer_agent = create_writer_agent()
    
    # Create tasks
    research_task = create_research_task(research_agent, topic)
    writing_task = create_writing_task(writer_agent)
    
    # Create crew
    crew = Crew(
        agents=[research_agent, writer_agent],
        tasks=[research_task, writing_task],
        process=Process.sequential,
        verbose=True,
    )
    
    return crew

@router.post("/research")
async def research(topic: str):
    try:
        crew = create_research_crew(topic)
        result = crew.kickoff()
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))