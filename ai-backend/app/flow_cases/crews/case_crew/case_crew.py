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
    def phase1_extract_agent(self) -> Agent:
        llm = LLM(model="gpt-4.1", temperature=0)
        return Agent(
            config=self.agents_config['phase1_extract_agent'],  # type: ignore[index]
            tools=self.tools,
            llm=llm
        )

    @agent
    def phase2_extract_agent(self) -> Agent:
        llm = LLM(model="gpt-4.1", temperature=0)
        return Agent(
            config=self.agents_config['phase2_extract_agent'],  # type: ignore[index]
            tools=self.tools,
            llm=llm
        )

    @task
    def phase1_extract_task(self) -> Task:
        cfg = self.tasks_config['phase1_extract_task'].copy()  # type: ignore[index]
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
            agent=self.phase1_extract_agent(),
            output_pydantic=CaseGraph
        )

    # Dynamic, per-node Phase 1 task with per-label instructions/examples and schema props
    def phase1_extract_single_node_task(self, description: str, output_model: Type[BaseModel]) -> Task:
        cfg = {
            "description": description,
            "expected_output": "JSON of properties only for the requested label"
        }
        return Task(
            config=cfg,
            agent=self.phase1_extract_agent(),
            output_pydantic=output_model
        )

    # Dynamic Phase 2 task for generating multiple Fact objects (no pydantic binding on Task)
    def phase2_extract_facts_task(self, description: str) -> Task:
        cfg = {
            "description": description,
            "expected_output": "A JSON object { facts: [ { ...properties... }, ... ] }"
        }
        return Task(
            config=cfg,
            agent=self.phase2_extract_agent(),
        )

    # Dynamic Phase 3 task for generating Witnesses and Evidence for a given Fact
    def phase3_extract_supports_task(self, description: str) -> Task:
        cfg = {
            "description": description,
            "expected_output": "A JSON object { witnesses: [ { node: {...}, support_strength: number } ], evidence: [ { node: {...}, support_strength: number } ] }"
        }
        return Task(
            config=cfg,
            agent=self.phase2_extract_agent(),
        )

    @task
    def phase2_extract_task(self) -> Task:
        cfg = self.tasks_config['phase2_extract_task'].copy()  # type: ignore[index]
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
            agent=self.phase2_extract_agent(),
            output_pydantic=CaseGraph
        )

    @agent
    def phase2b_dedup_agent(self) -> Agent:
        llm = LLM(model="gpt-4.1", temperature=0)
        return Agent(
            config=self.agents_config['phase2b_dedup_agent'],  # type: ignore[index]
            tools=[],
            llm=llm
        )

    @task
    def phase2b_dedup_task(self) -> Task:
        cfg = self.tasks_config['phase2b_dedup_task'].copy()  # type: ignore[index]
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
            agent=self.phase2b_dedup_agent(),
        )

    @agent
    def phase4_select_existing_agent(self) -> Agent:
        llm = LLM(model="gpt-4.1", temperature=0)
        return Agent(
            config=self.agents_config['phase4_select_existing_agent'],  # type: ignore[index]
            tools=[],
            llm=llm
        )

    @task
    def phase4_select_existing_task(self) -> Task:
        cfg = self.tasks_config['phase4_select_existing_task'].copy()  # type: ignore[index]
        desc = (
            cfg['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )

    @agent
    def phase5_select_existing_agent(self) -> Agent:
        llm = LLM(model="gpt-4.1", temperature=0)
        return Agent(
            config=self.agents_config['phase5_select_existing_agent'],  # type: ignore[index]
            tools=[],
            llm=llm
        )

    @task
    def phase5_select_existing_task(self) -> Task:
        cfg = self.tasks_config['phase5_select_existing_task'].copy()  # type: ignore[index]
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
            agent=self.phase5_select_existing_agent(),
        )

    @agent
    def phase3_relationships_agent(self) -> Agent:
        llm = LLM(model="gpt-4.1", temperature=0)
        return Agent(
            config=self.agents_config['phase3_relationships_agent'],  # type: ignore[index]
            tools=[],
            llm=llm
        )

    @task
    def phase3_relationships_task(self) -> Task:
        cfg = self.tasks_config['phase3_relationships_task'].copy()  # type: ignore[index]
        desc = (
            cfg['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )

    @agent
    def phase6_law_agent(self) -> Agent:
        llm = LLM(model="gpt-4.1", temperature=0)
        return Agent(
            config=self.agents_config['phase6_law_agent'],  # type: ignore[index]
            tools=[],
            llm=llm
        )

    @task
    def phase6_law_task(self) -> Task:
        cfg = self.tasks_config['phase6_law_task'].copy()  # type: ignore[index]
        desc = (
            cfg['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )

    @agent
    def phase7_issue_related_agent(self) -> Agent:
        llm = LLM(model="gpt-4.1", temperature=0)
        return Agent(
            config=self.agents_config['phase7_issue_related_agent'],  # type: ignore[index]
            tools=[],
            llm=llm
        )

    @task
    def phase7_issue_related_task(self) -> Task:
        cfg = self.tasks_config['phase7_issue_related_task'].copy()  # type: ignore[index]
        desc = (
            cfg['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )

    @agent
    def phase8_party_agent(self) -> Agent:
        llm = LLM(model="gpt-4.1", temperature=0)
        return Agent(
            config=self.agents_config['phase8_party_agent'],  # type: ignore[index]
            tools=[],
            llm=llm
        )

    @task
    def phase8_party_task(self) -> Task:
        cfg = self.tasks_config['phase8_party_task'].copy()  # type: ignore[index]
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
            agent=self.phase8_party_agent(),
        )

    


