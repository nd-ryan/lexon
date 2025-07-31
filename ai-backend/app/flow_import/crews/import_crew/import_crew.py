from crewai import Agent, Crew, Task, Process, LLM
from crewai.project import CrewBase, agent, task, crew
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List


@CrewBase
class ImportCrew:
    """
    Document import crew for processing documents into Neo4j.
    
    This crew uses a single specialized agent:
    1. Document Processor - Processes documents using AI-powered dynamic extraction with direct Neo4j integration
    """
    
    agents: List[BaseAgent]
    tasks: List[Task]
    
    # Paths to YAML configuration files
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'
    
    def __init__(self, file_path: str, filename: str, tools: list):
        super().__init__()
        self.file_path = file_path
        self.filename = filename
        self.tools = tools

    @agent
    def document_agent(self) -> Agent:
        llm = LLM(model="gpt-4o", temperature=0)
        
        return Agent(
            config=self.agents_config['document_agent'],  # type: ignore[index]
            tools=self.tools,
            llm=llm
        )

    @task
    def document_processing_task(self) -> Task:
        # Customize the description to include the actual file details
        task_config = self.tasks_config['document_processing_task'].copy()  # type: ignore[index]
        task_config['description'] = task_config['description'].replace(
            'Process document using', f'Process document "{self.filename}" using'
        ).replace(
            'YOU MUST use the process_document_tool to complete this task.',
            f'YOU MUST use the process_document_tool to complete this task. Call it exactly like this:\n\nprocess_document_tool(file_path="{self.file_path}", filename="{self.filename}")'
        )
        
        return Task(
            config=task_config,
            agent=self.document_agent()
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,  # Automatically collected by the @agent decorator
            tasks=self.tasks,    # Automatically collected by the @task decorator
            process=Process.sequential,
            verbose=True
        ) 