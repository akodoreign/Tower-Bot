"""
src — Tower Bot core package.

Exports commonly-used utilities for easy project-wide access:

SKILLS SYSTEM (new unified skills access):
    from src.skills import (
        load_all_skills,              # Load all SKILL.md files
        get_skill_for_task,           # Select skill for task type
        build_system_prompt_with_skills,  # Enhance prompts with skills
        generate_with_skills,         # Ollama generation with skills
        set_use_skills,               # Enable/disable skills globally
        list_available_skills,        # List all available skills
        get_skill_content,            # Get specific skill content
    )

LOGGING:
    from src.log import logger        # Project logger

PROVIDERS (AI models):
    from src.providers import ProviderManager, ProviderType

MISSIONS:
    from src.mission_builder import generate_mission_async

NEWS & WORLD:
    from src.news_feed import (
        generate_bulletin,
        generate_story_image,
    )

EXAMPLE: Using skills in a module
    from src.skills import load_all_skills, build_system_prompt_with_skills
    
    def my_generation_function():
        skills = load_all_skills()
        system_prompt = build_system_prompt_with_skills(
            base_prompt="You are a writer",
            task="prose-writing",
            skills=skills,
        )
        # Use enhanced system_prompt with your LLM...
"""

# Skills system — project-wide access
from .skills import (
    load_all_skills,
    get_skill_for_task,
    build_system_prompt_with_skills,
    generate_with_skills,
    set_use_skills,
    get_use_skills,
    list_available_skills,
    get_skill_content,
    enhance_generation_with_skills,
    enhance_generation_async,
    clear_skills_cache,
    Skill,
)

# Logging
from .log import logger

__all__ = [
    # Skills
    "load_all_skills",
    "get_skill_for_task",
    "build_system_prompt_with_skills",
    "generate_with_skills",
    "set_use_skills",
    "list_available_skills",
    "get_skill_content",
    "enhance_generation_with_skills",
    "enhance_generation_async",
    "clear_skills_cache",
    "Skill",
    # Logging
    "logger",
]
