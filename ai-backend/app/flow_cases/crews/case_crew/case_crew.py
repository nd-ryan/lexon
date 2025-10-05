from crewai import Agent, Crew, Task, LLM, Process
from crewai.project import CrewBase, agent, task, crew
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List, Type
from pydantic import BaseModel
from app.models.case_graph import CaseGraph


@CrewBase
class CaseCrew:
    """
    Crew methods for case extraction flow.
    
    FLOW V2 PHASE MAPPING (case_extract_flow_v2.py):
    - Phase 1: Foundation (Case, Proceeding, Issue) 
      → uses phase1_extract_agent + phase1_extract_single/multi_node_task
    - Phase 2: Forum & Jurisdiction 
      → uses phase5_select_existing_agent/task
    - Phase 3: Parties 
      → uses phase8_party_agent/task
    - Phase 4: Issue Concepts (Doctrine/Policy/FactPattern) 
      → uses phase7_issue_related_agent/task
    - Phase 5: Holdings (NEW) 
      → uses phase1_extract_agent + phase1_extract_single_node_task
    - Phase 6: Ruling & Arguments (NEW) 
      → uses phase1_extract_agent + phase1_extract_single/multi_node_task
    - Phase 7: Laws 
      → uses phase6_law_agent/task
    - Phase 8: ReliefType 
      → uses phase5_select_existing_agent/task
    - Phase 9: Facts 
      → uses phase2_extract_agent + phase2_extract_facts_task
    - Phase 10: Evidence & Witnesses 
      → uses phase2_extract_agent + phase3_extract_supports_task
    
    Note: Method names reflect original phase numbers for backward compatibility.
    """
    agents: List[BaseAgent]
    tasks: List[Task]

    # LLM model configuration
    LLM_MODEL = "gpt-4.1"
    LLM_TEMPERATURE = 0

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
        """
        General-purpose extraction agent.
        
        Used in Flow V2 by:
        - Phase 1: Case, Proceeding, Issue extraction
        - Phase 5: Holdings extraction (NEW)
        - Phase 6: Ruling & Arguments extraction (NEW)
        """
        llm = LLM(model=self.LLM_MODEL, temperature=self.LLM_TEMPERATURE)
        return Agent(
            config=self.agents_config['phase1_extract_agent'],  # type: ignore[index]
            tools=self.tools,
            llm=llm
        )

    @agent
    def phase2_extract_agent(self) -> Agent:
        """
        Relationship extraction agent.
        
        Used in Flow V2 by:
        - Phase 9: Facts extraction
        - Phase 10: Evidence & Witnesses extraction
        """
        llm = LLM(model=self.LLM_MODEL, temperature=self.LLM_TEMPERATURE)
        return Agent(
            config=self.agents_config['phase2_extract_agent'],  # type: ignore[index]
            tools=self.tools,
            llm=llm
        )


    # Dynamic, per-node extraction task with per-label instructions/examples and schema props
    def phase1_extract_single_node_task(self, description: str, output_model: Type[BaseModel]) -> Task:
        """
        Extract a single node instance with validated properties.
        
        Used in Flow V2 by:
        - Phase 1: Case, Proceeding (single instances)
        - Phase 5: Holdings (one per Issue)
        - Phase 6: Ruling (one per Holding, with dedup)
        """
        cfg = {
            "description": description,
            "expected_output": "JSON of properties only for the requested label"
        }
        return Task(
            config=cfg,
            agent=self.phase1_extract_agent(),
            output_pydantic=output_model
        )

    # Dynamic, multi-node extraction task for labels that can occur multiple times
    def phase1_extract_multi_nodes_task(self, description: str, output_model: Type[BaseModel]) -> Task:
        """
        Extract multiple node instances (list) with validated properties.
        
        Used in Flow V2 by:
        - Phase 1: Issue (multiple per case)
        - Phase 6: Arguments (multiple per Holding)
        """
        cfg = {
            "description": description,
            "expected_output": "A JSON object { items: [ { ...properties... }, ... ] }"
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
    
    # Batch extraction tasks with Pydantic output models
    def batch_extract_task(self, description: str, output_model: Type[BaseModel]) -> Task:
        """
        Generic batch extraction task with Pydantic output model.
        Used for Phase 5, 6, 9, 10 batch operations.
        """
        cfg = {
            "description": description,
            "expected_output": f"JSON matching the {output_model.__name__} schema"
        }
        return Task(
            config=cfg,
            agent=self.phase1_extract_agent(),
            output_pydantic=output_model
        )

    

    @agent
    def phase5_select_existing_agent(self) -> Agent:
        llm = LLM(model=self.LLM_MODEL, temperature=self.LLM_TEMPERATURE)
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
        llm = LLM(model=self.LLM_MODEL, temperature=self.LLM_TEMPERATURE)
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
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        cfg['description'] = desc
        return Task(
            config=cfg,
            agent=self.phase3_relationships_agent(),
        )

    @agent
    def phase6_law_agent(self) -> Agent:
        llm = LLM(model=self.LLM_MODEL, temperature=self.LLM_TEMPERATURE)
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
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        cfg['description'] = desc
        return Task(
            config=cfg,
            agent=self.phase6_law_agent(),
        )

    @agent
    def phase7_issue_related_agent(self) -> Agent:
        llm = LLM(model=self.LLM_MODEL, temperature=self.LLM_TEMPERATURE)
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
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        cfg['description'] = desc
        return Task(
            config=cfg,
            agent=self.phase7_issue_related_agent(),
        )

    @agent
    def phase8_party_agent(self) -> Agent:
        llm = LLM(model=self.LLM_MODEL, temperature=self.LLM_TEMPERATURE)
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

    


