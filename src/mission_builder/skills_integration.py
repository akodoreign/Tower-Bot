"""
skills_integration.py — DEPRECATED — Use src.skills instead.

This module is kept for backward compatibility only.
All functionality has been moved to src.skills for project-wide access.

NEW CODE SHOULD USE:
    from src.skills import (
        load_all_skills,
        get_skill_for_task,
        build_system_prompt_with_skills,
        generate_with_skills,
        set_use_skills,
    )

BACKWARD COMPATIBILITY:
This file re-exports everything from src.skills so existing code importing 
from mission_builder.skills_integration will continue to work.
"""

# Re-export everything from src.skills
from src.skills import (
    Skill,
    load_skill_from_file,
    load_all_skills,
    get_skill_for_task,
    list_available_skills,
    get_skill_content,
    build_system_prompt_with_skills,
    generate_with_skills,
    set_use_skills,
    get_use_skills,
    clear_skills_cache,
    enhance_generation_with_skills,
    enhance_generation_async,
    SKILLS_DIR,
)

__all__ = [
    "Skill",
    "load_skill_from_file",
    "load_all_skills",
    "get_skill_for_task",
    "list_available_skills",
    "get_skill_content",
    "build_system_prompt_with_skills",
    "generate_with_skills",
    "set_use_skills",
    "get_use_skills",
    "clear_skills_cache",
    "enhance_generation_with_skills",
    "enhance_generation_async",
    "SKILLS_DIR",
]
