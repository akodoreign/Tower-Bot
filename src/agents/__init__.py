"""
src/agents/__init__.py — Tower of Last Chance Agent System

Provides KimiAgent and QwenAgent for Pi/OpenClaw integration.

Usage:
    from src.agents import KimiAgent, QwenAgent

    # Fast local tasks (rules lookup, style descriptions)
    qwen = QwenAgent()
    result = await qwen.complete(prompt)

    # Complex reasoning with subagent orchestration
    kimi = KimiAgent()
    result = await kimi.complete(prompt, use_subagents=True)

    # Quick helpers (recommended for news_feed, mission_board)
    from src.agents import generate_with_kimi, generate_bulletin
    text = await generate_with_kimi(prompt)
    bulletin = await generate_bulletin(news_type="rift", instruction="...")

Architecture:
    - QwenAgent: Fast local inference via Ollama (qwen model)
    - KimiAgent: Cloud-hosted 1T parameter MoE with subagent capabilities
    - Both use the OpenAI-compatible API at http://localhost:11434/v1
"""

from src.agents.base import BaseAgent, AgentConfig, AgentResponse
from src.agents.qwen_agent import QwenAgent
from src.agents.kimi_agent import KimiAgent
from src.agents.helpers import (
    generate_with_kimi,
    generate_with_qwen,
    generate_bulletin,
    generate_mission_text,
)

# Learning system agents (for self-learning autonomous improvement)
from src.agents.learning_agents import (
    AgentAnalysis,
    LearningSession,
    ProjectManagerAgent,
    PythonVeteranAgent,
    DNDExpertAgent,
    DNDVeteranAgent,
    AICriticAgent,
)
from src.agents.orchestrator import AgentOrchestrator

# News editorial agents
from src.agents.news_agents import (
    NewsEditorAgent,
    GossipEditorAgent,
    SportsColumnistAgent,
    BulletinResult,
    FactCheckerMixin,
    get_news_agent,
    generate_news_bulletin,
    generate_gossip_bulletin,
    generate_sports_bulletin,
)

__all__ = [
    "BaseAgent",
    "AgentConfig", 
    "AgentResponse",
    "QwenAgent",
    "KimiAgent",
    # Helpers
    "generate_with_kimi",
    "generate_with_qwen",
    "generate_bulletin",
    "generate_mission_text",
    # Learning system
    "AgentAnalysis",
    "LearningSession",
    "ProjectManagerAgent",
    "PythonVeteranAgent",
    "DNDExpertAgent",
    "DNDVeteranAgent",
    "AICriticAgent",
    "AgentOrchestrator",
    # News editorial agents
    "NewsEditorAgent",
    "GossipEditorAgent",
    "SportsColumnistAgent",
    "BulletinResult",
    "FactCheckerMixin",
    "get_news_agent",
    "generate_news_bulletin",
    "generate_gossip_bulletin",
    "generate_sports_bulletin",
]
