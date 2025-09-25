from crewai import Agent, Crew, Task, LLM, Process
from crewai.project import CrewBase, agent, task, crew
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List
from app.models.case_graph import CaseGraph


@CrewBase
class CaseCrew:
    agents: List[BaseAgent]
    tasks: List[Task]

    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    def __init__(self, file_path: str, filename: str, case_id: str, tools: list, schema_spec_text: str = "", extra_instructions: str = ""):
        super().__init__()
        self.file_path = file_path
        self.filename = filename
        self.case_id = case_id
        self.tools = tools
        self.schema_spec_text = schema_spec_text
        self.extra_instructions = extra_instructions

    @agent
    def extract_agent(self) -> Agent:
        llm = LLM(model="gpt-4.1", temperature=0)
        return Agent(
            config=self.agents_config['extract_agent'],  # type: ignore[index]
            tools=self.tools,
            llm=llm
        )

    @task
    def extract_task(self) -> Task:
        cfg = self.tasks_config['extract_task'].copy()  # type: ignore[index]
        cfg['description'] = (
            cfg['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        ) + ("\n\nSCHEMA SPEC:\n" + (self.schema_spec_text or "")) + ("\n\n" + self.extra_instructions if self.extra_instructions else "")
        return Task(
            config=cfg,
            agent=self.extract_agent(),
            output_pydantic=CaseGraph
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=[self.extract_agent()],
            tasks=[self.extract_task()],
            process=Process.sequential
        )


