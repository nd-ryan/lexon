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
      → uses phase9_party_agent / phase9_party_task
    - Phase 4: Ruling extraction
      → uses phase1_extract_agent + phase4_ruling_per_issue_task
    - Phase 5: Arguments per Ruling
      → uses phase1_extract_agent + phase5_arguments_per_ruling_task
    - Phase 6: Laws per Ruling
      → uses phase6_law_agent + phase6_laws_per_ruling_task
    - Phase 7: Concepts (Doctrine/Policy/FactPattern)
      → uses phase1_extract_agent + phase7_argument_concepts_task
    - Phase 8: Relief and ReliefType
      → uses phase1_extract_agent + phase8_relief_and_type_task
    - Phase 9: Domain selection
      → uses phase9_domain_agent + phase9_select_domain_task
    - Phase 10: Validation
      → validation only, no crew tasks needed
    """
    agents: List[BaseAgent]
    tasks: List[Task]

    # LLM model configuration
    LLM_MODEL = "gpt-4.1"
    LLM_MODEL_MINI = "gpt-4.1-mini"
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
            agent=self.phase1_extract_agent(),
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
            agent=self.phase1_extract_agent(),
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
            agent=self.phase1_extract_agent(),
            output_pydantic=output_model
        )

    def phase4_ruling_per_issue_task(self, output_model: Type[BaseModel]) -> Task:
        """
        Extract Ruling per Issue with in_favor relationship property (Phase 4).
        
        Replacements expected: CASE_TEXT, ISSUES_JSON, RULING_INSTRUCTIONS, RULING_EXAMPLES_JSON, RULING_SPEC_TEXT
        """
        task_spec = self.tasks_config['phase4_ruling_per_issue_task'].copy()  # type: ignore[index]
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
            agent=self.phase1_extract_agent(),
            output_pydantic=output_model
        )

    def phase5_arguments_per_ruling_task(self, output_model: Type[BaseModel]) -> Task:
        """
        Extract Arguments per Ruling with status relationship property (Phase 5).
        
        Replacements expected: CASE_TEXT, RULINGS_JSON, ARGUMENT_INSTRUCTIONS, ARGUMENT_EXAMPLES_JSON, ARGUMENT_SPEC_TEXT
        """
        task_spec = self.tasks_config['phase5_arguments_per_ruling_task'].copy()  # type: ignore[index]
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
            agent=self.phase1_extract_agent(),
            output_pydantic=output_model
        )

    def phase5b_disposition_task(self, output_model: Type[BaseModel]) -> Task:
        """
        Extract disposition_text for Arguments (Phase 5B).
        
        Replacements expected: CASE_TEXT, ARGUMENTS_JSON, ARGUMENT_EXAMPLES_JSON
        """
        task_spec = self.tasks_config['phase5b_disposition_task'].copy()  # type: ignore[index]
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
            agent=self.phase1_extract_agent(),
            output_pydantic=output_model
        )

    def phase6_laws_per_ruling_task(self) -> Task:
        """
        Select Laws per Ruling from catalog (Phase 6).
        
        Replacements expected: CASE_TEXT, RULINGS_JSON, LAW_SPEC_TEXT, CATALOGS_JSON
        """
        task_spec = self.tasks_config['phase6_laws_per_ruling_task'].copy()  # type: ignore[index]
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
            agent=self.phase6_law_agent(),
        )

    def phase7_argument_concepts_task(self, output_model: Type[BaseModel]) -> Task:
        """
        Assign Doctrine/Policy/FactPattern to Arguments from catalog (Phase 7).
        
        Replacements expected: ARGUMENTS_JSON, CATALOGS_JSON, SCHEMA_SPEC_TEXT, DOCTRINE_INSTRUCTIONS, 
                               DOCTRINE_EXAMPLES_JSON, POLICY_INSTRUCTIONS, POLICY_EXAMPLES_JSON,
                               FACTPATTERN_INSTRUCTIONS, FACTPATTERN_EXAMPLES_JSON
        """
        task_spec = self.tasks_config['phase7_argument_concepts_task'].copy()  # type: ignore[index]
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
            agent=self.phase1_extract_agent(),
            output_pydantic=output_model
        )

    def phase8_relief_and_type_task(self) -> Task:
        """
        Generate Relief nodes and assign ReliefType from catalog (Phase 8).
        
        Replacements expected: CASE_TEXT, RULINGS_JSON, RELIEF_SPEC_TEXT, RELIEF_INSTRUCTIONS,
                               RELIEF_EXAMPLES_JSON, RELIEFTYPE_INSTRUCTIONS, RELIEFTYPE_EXAMPLES_JSON, CATALOGS_JSON
        """
        task_spec = self.tasks_config['phase8_relief_and_type_task'].copy()  # type: ignore[index]
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
            agent=self.phase1_extract_agent(),
        )

    @agent
    def phase6_law_agent(self) -> Agent:
        """Agent for Phase 6: selecting Laws from catalog (uses mini model)"""
        llm = LLM(model=self.LLM_MODEL_MINI, temperature=self.LLM_TEMPERATURE)
        return Agent(
            config=self.agents_config['phase6_law_agent'],  # type: ignore[index]
            tools=[],
            llm=llm
        )

    @agent
    def phase2_select_forum_agent(self) -> Agent:
        """Agent for Phase 2: selecting Forum from catalog based on case text (uses mini model)"""
        llm = LLM(model=self.LLM_MODEL_MINI, temperature=self.LLM_TEMPERATURE)
        return Agent(
            config=self.agents_config['phase5_select_existing_agent'],  # type: ignore[index]
            tools=[],
            llm=llm
        )

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
            agent=self.phase2_select_forum_agent(),
            output_pydantic=output_model
        )

    @agent
    def phase9_party_agent(self) -> Agent:
        llm = LLM(model=self.LLM_MODEL, temperature=self.LLM_TEMPERATURE)
        return Agent(
            config=self.agents_config['phase9_party_agent'],  # type: ignore[index]
            tools=[],
            llm=llm
        )

    def phase9_party_task(self) -> Task:
        task_spec = self.tasks_config['phase9_party_task'].copy()  # type: ignore[index]
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
            agent=self.phase9_party_agent(),
        )

    @agent
    def phase9_domain_agent(self) -> Agent:
        """Agent for Phase 9: selecting Domain from catalog or options (uses mini model)"""
        llm = LLM(model=self.LLM_MODEL_MINI, temperature=self.LLM_TEMPERATURE)
        return Agent(
            config=self.agents_config['phase9_domain_agent'],  # type: ignore[index]
            tools=[],
            llm=llm
        )

    def phase9_select_domain_task(self, output_model: Type[BaseModel]) -> Task:
        """Task for Phase 9: select Domain from catalog or options"""
        task_spec = self.tasks_config['phase9_select_domain_task'].copy()  # type: ignore[index]
        desc = task_spec['description']
        for k, v in self.replacements.items():
            desc = desc.replace('{' + str(k) + '}', str(v))
        task_spec['description'] = desc
        return Task(
            config=task_spec,
            agent=self.phase9_domain_agent(),
            output_pydantic=output_model
        )

    


