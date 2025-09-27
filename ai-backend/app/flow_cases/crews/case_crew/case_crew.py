from crewai import Agent, Crew, Task, LLM, Process
from crewai.project import CrewBase, agent, task, crew
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List, Type
from pydantic import BaseModel
from app.models.case_graph import CaseGraph


@CrewBase
class CaseCrew:
    agents: List[BaseAgent]
    tasks: List[Task]

    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    def __init__(self, file_path: str, filename: str, case_id: str, tools: list, replacements: dict | None = None):
        super().__init__()
        self.file_path = file_path
        self.filename = filename
        self.case_id = case_id
        self.tools = tools
        self.replacements = replacements or {}

    @agent
    def extract_agent_phase1(self) -> Agent:
        llm = LLM(model="gpt-4.1", temperature=0)
        return Agent(
            config=self.agents_config['extract_agent_phase1'],  # type: ignore[index]
            tools=self.tools,
            llm=llm
        )

    @agent
    def extract_agent_phase2(self) -> Agent:
        llm = LLM(model="gpt-4.1", temperature=0)
        return Agent(
            config=self.agents_config['extract_agent_phase2'],  # type: ignore[index]
            tools=self.tools,
            llm=llm
        )

    @task
    def extract_task_phase1(self) -> Task:
        cfg = self.tasks_config['extract_task_phase1'].copy()  # type: ignore[index]
        desc = (
            cfg['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        cfg['description'] = desc
        return Task(
            config=cfg,
            agent=self.extract_agent_phase1(),
            output_pydantic=CaseGraph
        )

    # Dynamic, per-node Phase 1 task with per-label instructions/examples and schema props
    def extract_task_phase1_single_node(self, description: str, output_model: Type[BaseModel]) -> Task:
        cfg = {
            "description": description,
            "expected_output": "JSON of properties only for the requested label"
        }
        return Task(
            config=cfg,
            agent=self.extract_agent_phase1(),
            output_pydantic=output_model
        )

    # Dynamic Phase 2 task for generating multiple Fact objects (no pydantic binding on Task)
    def extract_task_phase2_facts(self, description: str) -> Task:
        cfg = {
            "description": description,
            "expected_output": "A JSON object { facts: [ { ...properties... }, ... ] }"
        }
        return Task(
            config=cfg,
            agent=self.extract_agent_phase2(),
        )

    # Dynamic Phase 3 task for generating Witnesses and Evidence for a given Fact
    def extract_task_phase3_supports(self, description: str) -> Task:
        cfg = {
            "description": description,
            "expected_output": "A JSON object { witnesses: [ { node: {...}, support_strength: number } ], evidence: [ { node: {...}, support_strength: number } ] }"
        }
        return Task(
            config=cfg,
            agent=self.extract_agent_phase2(),
        )

    @task
    def extract_task_phase2(self) -> Task:
        cfg = self.tasks_config['extract_task_phase2'].copy()  # type: ignore[index]
        desc = (
            cfg['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        cfg['description'] = desc
        return Task(
            config=cfg,
            agent=self.extract_agent_phase2(),
            output_pydantic=CaseGraph
        )

    @agent
    def dedup_agent_phase2b(self) -> Agent:
        llm = LLM(model="gpt-4.1", temperature=0)
        return Agent(
            config=self.agents_config['dedup_agent_phase2b'],  # type: ignore[index]
            tools=[],
            llm=llm
        )

    @task
    def dedup_task_phase2b(self) -> Task:
        cfg = self.tasks_config['dedup_task_phase2b'].copy()  # type: ignore[index]
        desc = (
            cfg['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        cfg['description'] = desc
        return Task(
            config=cfg,
            agent=self.dedup_agent_phase2b(),
        )

    @agent
    def select_existing_agent_phase4(self) -> Agent:
        llm = LLM(model="gpt-4.1", temperature=0)
        return Agent(
            config=self.agents_config['select_existing_agent_phase4'],  # type: ignore[index]
            tools=[],
            llm=llm
        )

    @task
    def select_existing_task_phase4(self) -> Task:
        cfg = self.tasks_config['select_existing_task_phase4'].copy()  # type: ignore[index]
        desc = (
            cfg['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        cfg['description'] = desc
        return Task(
            config=cfg,
            agent=self.select_existing_agent_phase4(),
        )

    @agent
    def relationships_agent_phase3(self) -> Agent:
        llm = LLM(model="gpt-4.1", temperature=0)
        return Agent(
            config=self.agents_config['relationships_agent_phase3'],  # type: ignore[index]
            tools=[],
            llm=llm
        )

    @task
    def relationships_task_phase3(self) -> Task:
        cfg = self.tasks_config['relationships_task_phase3'].copy()  # type: ignore[index]
        desc = (
            cfg['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        cfg['description'] = desc
        return Task(
            config=cfg,
            agent=self.relationships_agent_phase3(),
        )

    @crew
    def crew(self) -> Crew:
        # Default crew: phase1 only. The flow will choose the right task explicitly.
        return Crew(
            agents=[
                self.extract_agent_phase1(),
                self.extract_agent_phase2(),
                self.dedup_agent_phase2b(),
                self.relationships_agent_phase3(),
                self.select_existing_agent_phase4(),
            ],
            tasks=[
                self.extract_task_phase1(),
                self.extract_task_phase2(),
                self.dedup_task_phase2b(),
                self.relationships_task_phase3(),
                self.select_existing_task_phase4(),
            ],
            process=Process.sequential
        )


