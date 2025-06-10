from crewai import Agent
import os

def create_research_agent():
    return Agent(
        role="Research Analyst",
        goal="Conduct thorough research on given topics",
        backstory="You are an expert research analyst with years of experience in gathering and analyzing information from various sources.",
        verbose=True,
        allow_delegation=False,
    )

def create_writer_agent():
    return Agent(
        role="Content Writer",
        goal="Create engaging and informative content based on research",
        backstory="You are a skilled content writer who can transform research findings into compelling narratives.",
        verbose=True,
        allow_delegation=False,
    )