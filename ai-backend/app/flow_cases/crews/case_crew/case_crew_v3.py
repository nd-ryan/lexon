from crewai import Agent, Crew, Task, LLM, Process
from crewai.project import CrewBase, agent, task, crew
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List, Type
from pydantic import BaseModel
from app.models.case_graph import CaseGraph


@CrewBase
class CaseCrew:
    """
    Crew methods for case extraction flow (V3 - Production).
    
    PHASE MAPPING (case_extract_flow_v3.py):
    - Phase 1: Foundation (Case, Proceeding, Issue) 
      → uses phase1_extract_agent + phase1_extract_case_task / phase1_extract_proceeding_task / phase1_extract_issue_task
    - Phase 2: Forum & Jurisdiction 
      → uses phase2_select_forum_agent / phase2_select_forum_task
    - Phase 3: Parties 
      → uses phase8_party_agent / phase8_party_task
    - Phase 4: Ruling extraction
      → uses phase1_extract_agent + phase4_ruling_per_issue_task
    - Phase 5: Arguments and Laws
      → uses phase1_extract_agent + phase5_arguments_and_laws_task
    - Phase 6: Concepts (Doctrine/Policy/FactPattern)
      → uses phase1_extract_agent + phase6_argument_concepts_task
    - Phase 7: Relief and ReliefType
      → uses phase1_extract_agent + phase7_relief_and_type_task
    - Phase 8: Validation
      → validation only, no crew tasks needed
    """
    agents: List[BaseAgent]
    tasks: List[Task]

    # LLM model configuration
    LLM_MODEL = "gpt-4.1"
    LLM_TEMPERATURE = 0

    agents_config = 'config/agents_v3.yaml'
    tasks_config = 'config/tasks_v3.yaml'

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
        General-purpose extraction agent for Phase 1 and other extraction phases.
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
        """
        llm = LLM(model=self.LLM_MODEL, temperature=self.LLM_TEMPERATURE)
        return Agent(
            config=self.agents_config['phase2_extract_agent'],  # type: ignore[index]
            tools=self.tools,
            llm=llm
        )

    def phase1_extract_case_task(self, output_model: Type[BaseModel]) -> Task:
        """
        Extract Case node with validated properties.
        
        Replacements expected: PROPS_SPEC_TEXT, EXAMPLES_JSON, CASE_TEXT
        """
        task_spec = self.tasks_config['phase1_extract_case_task'].copy()  # type: ignore[index]
        desc = (
            task_spec['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        task_spec['description'] = desc
        return Task(
            config=task_spec,
            output_pydantic=output_model
        )

    def phase1_extract_proceeding_task(self, output_model: Type[BaseModel]) -> Task:
        """
        Extract Proceeding node with validated properties.
        
        Replacements expected: PROPS_SPEC_TEXT, EXAMPLES_JSON, CASE_TEXT
        """
        task_spec = self.tasks_config['phase1_extract_proceeding_task'].copy()  # type: ignore[index]
        desc = (
            task_spec['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        task_spec['description'] = desc
        return Task(
            config=task_spec,
            output_pydantic=output_model
        )

    def phase1_extract_issue_task(self, output_model: Type[BaseModel]) -> Task:
        """
        Extract multiple Issue nodes with validated properties.
        
        Replacements expected: PROPS_SPEC_TEXT, EXAMPLES_JSON, CASE_TEXT
        """
        task_spec = self.tasks_config['phase1_extract_issue_task'].copy()  # type: ignore[index]
        desc = (
            task_spec['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        task_spec['description'] = desc
        return Task(
            config=task_spec,
            output_pydantic=output_model
        )

    # Dynamic Phase 2 task for generating multiple Fact objects (no pydantic binding on Task)
    def phase2_extract_facts_task(self, description: str) -> Task:
        task_spec = {
            "description": description,
            "expected_output": "A JSON object { facts: [ { ...properties... }, ... ] }"
        }
        return Task(
            config=task_spec,
        )

    # Dynamic Phase 3 task for generating Witnesses and Evidence for a given Fact
    def phase3_extract_supports_task(self, description: str) -> Task:
        task_spec = {
            "description": description,
            "expected_output": "A JSON object { witnesses: [ { node: {...}, support_strength: number } ], evidence: [ { node: {...}, support_strength: number } ] }"
        }
        return Task(
            config=task_spec,
        )
    
    # Phase 5: Batch ruling and arguments extraction
    def phase5_batch_ruling_arguments_task(self, output_model: Type[BaseModel]) -> Task:
        """
        Batch extraction task for Ruling and Arguments per Issue.
        Used in Phase 5 for processing multiple issues at once.
        
        Replacements expected: CASE_TEXT, ISSUES_JSON, RULING_INSTRUCTIONS, RULING_EXAMPLES_JSON,
                               RULING_SPEC_TEXT, ARGUMENT_INSTRUCTIONS, ARGUMENT_EXAMPLES_JSON, ARGUMENT_SPEC_TEXT
        """
        task_spec = self.tasks_config['phase5_batch_ruling_arguments_task'].copy()  # type: ignore[index]
        desc = (
            task_spec['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        task_spec['description'] = desc
        return Task(
            config=task_spec,
            output_pydantic=output_model
        )

    

    @agent
    def phase2_select_forum_agent(self) -> Agent:
        """Agent for Phase 2: selecting Forum from catalog based on case text"""
        llm = LLM(model=self.LLM_MODEL, temperature=self.LLM_TEMPERATURE)
        return Agent(
            config=self.agents_config['phase5_select_existing_agent'],  # type: ignore[index]
            tools=[],
            llm=llm
        )

    @task
    def phase2_select_forum_task(self, output_model: Type[BaseModel]) -> Task:
        """Task for Phase 2: select Forum from catalog"""
        task_spec = self.tasks_config['phase2_select_forum_task'].copy()  # type: ignore[index]
        desc = (
            task_spec['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        task_spec['description'] = desc
        return Task(
            config=task_spec,
            output_pydantic=output_model
        )

    @agent
    def phase7_select_relief_type_agent(self) -> Agent:
        """Agent for Phase 7: selecting ReliefType from catalog based on ruling"""
        llm = LLM(model=self.LLM_MODEL, temperature=self.LLM_TEMPERATURE)
        return Agent(
            config=self.agents_config['phase5_select_existing_agent'],  # type: ignore[index]
            tools=[],
            llm=llm
        )

    @task
    def phase7_select_relief_type_task(self, output_model: Type[BaseModel]) -> Task:
        """Task for Phase 7: select ReliefType from catalog"""
        task_spec = self.tasks_config['phase7_select_relief_type_task'].copy()  # type: ignore[index]
        desc = (
            task_spec['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        task_spec['description'] = desc
        return Task(
            config=task_spec,
            output_pydantic=output_model
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
        task_spec = self.tasks_config['phase3_relationships_task'].copy()  # type: ignore[index]
        desc = (
            task_spec['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        task_spec['description'] = desc
        return Task(
            config=task_spec,
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
        task_spec = self.tasks_config['phase6_law_task'].copy()  # type: ignore[index]
        desc = (
            task_spec['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        task_spec['description'] = desc
        return Task(
            config=task_spec,
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
        task_spec = self.tasks_config['phase7_issue_related_task'].copy()  # type: ignore[index]
        desc = (
            task_spec['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        task_spec['description'] = desc
        return Task(
            config=task_spec,
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
        task_spec = self.tasks_config['phase8_party_task'].copy()  # type: ignore[index]
        desc = (
            task_spec['description']
            .replace('{FILENAME}', self.filename)
            .replace('{FILEPATH}', self.file_path)
        )
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        task_spec['description'] = desc
        return Task(
            config=task_spec,
        )

    


