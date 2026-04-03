"""
skills.py — Project-wide skill management system.

Unified access to all SKILL.md files in the /skills folder.
Supports skill loading, selection, and prompt enhancement across the entire project.

Every module can import and use:
    from src.skills import (
        load_all_skills,
        get_skill_for_task,
        build_system_prompt_with_skills,
        generate_with_skills,
        get_skill_content,
        list_available_skills,
    )

For mission generation specifically:
    from src.skills import set_use_skills, enhance_generation_with_skills

Exported API:
    load_all_skills()                    — Load all 27+ SKILL.md files
    get_skill_for_task()                 — Select relevant skill(s) for a task
    build_system_prompt_with_skills()   — Enhance system prompt with skill context
    generate_with_skills()               — Generate content using Ollama with skills
    set_use_skills()                     — Enable/disable skills globally
    list_available_skills()              — List all loaded skills
    get_skill_content()                  — Get content of specific skill
    enhance_generation_with_skills()    — Helper for async skill-enhanced generation
"""

from __future__ import annotations

import os
import json
import asyncio
import re

# Make yaml optional — use simple fallback parser if not installed
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    yaml = None
    YAML_AVAILABLE = False
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from functools import lru_cache

logger = logging.getLogger(__name__)

# Global configuration
_USE_SKILLS = False  # Global flag for skill usage
_SKILLS_CACHE: Optional[Dict[str, Skill]] = None  # Cache loaded skills
_CACHE_LOCK = asyncio.Lock()  # Thread-safe caching

# Skill discovery
SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


# ─────────────────────────────────────────────────────────────────────────
# Skill Data Model
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class Skill:
    """Represents a loaded SKILL.md file with parsed metadata."""
    
    name: str                           # Skill directory name
    description: str                    # From YAML: description field
    path: Path                          # Full path to SKILL.md
    content: str                        # Markdown body
    metadata: Dict[str, Any]            # Parsed YAML frontmatter
    
    def __repr__(self) -> str:
        return f"<Skill {self.name}: {self.description[:60]}...>"


# ─────────────────────────────────────────────────────────────────────────
# Skill Loading & Storage
# ─────────────────────────────────────────────────────────────────────────

def _parse_simple_frontmatter(text: str) -> Dict[str, Any]:
    """
    Simple fallback parser for YAML frontmatter when PyYAML isn't installed.
    Handles basic key: value pairs and simple lists.
    """
    metadata = {}
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            # Handle simple lists: [item1, item2]
            if value.startswith("[") and value.endswith("]"):
                items = value[1:-1].split(",")
                metadata[key] = [item.strip().strip('"').strip("'") for item in items if item.strip()]
            # Handle quoted strings
            elif (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                metadata[key] = value[1:-1]
            else:
                metadata[key] = value
    return metadata


def load_skill_from_file(skill_file: Path) -> Optional[Skill]:
    """
    Parse a single SKILL.md file.
    
    Expected format:
        ---
        name: skill-name
        description: Short description
        keywords: [optional, list, of, keywords]
        ---
        
        # Skill Content (markdown)
        Actual skill body here...
    
    Args:
        skill_file: Path to SKILL.md file
    
    Returns:
        Skill object, or None on parse error
    """
    if not skill_file.exists():
        return None
    
    try:
        raw_content = skill_file.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not read {skill_file}: {e}")
        return None
    
    # Parse YAML frontmatter
    metadata = {}
    body = raw_content
    
    if raw_content.startswith("---"):
        parts = raw_content.split("---", 2)
        if len(parts) >= 3:
            frontmatter_text, body = parts[1], parts[2].strip()
            if YAML_AVAILABLE:
                try:
                    metadata = yaml.safe_load(frontmatter_text) or {}
                except yaml.YAMLError as e:
                    logger.warning(f"YAML parse error in {skill_file}: {e}")
                    metadata = {}
            else:
                # Simple fallback parser for basic key: value frontmatter
                metadata = _parse_simple_frontmatter(frontmatter_text)
    
    # Extract skill info
    skill_name = metadata.get("name") or skill_file.parent.name
    description = metadata.get("description", "No description provided")
    
    return Skill(
        name=skill_name,
        description=description,
        path=skill_file,
        content=body,
        metadata=metadata,
    )


def load_all_skills(skills_dir: Optional[Path] = None) -> Dict[str, Skill]:
    """
    Load all SKILL.md files from the skills directory.
    
    Recursively searches for SKILL.md files in all subdirectories.
    Results are cached for performance.
    
    Args:
        skills_dir: Override default skills directory path (for testing)
    
    Returns:
        Dict mapping skill name → Skill object
    """
    global _SKILLS_CACHE
    
    if _SKILLS_CACHE is not None:
        return _SKILLS_CACHE
    
    target_dir = skills_dir or SKILLS_DIR
    
    if not target_dir.exists():
        logger.error(f"Skills directory not found: {target_dir}")
        _SKILLS_CACHE = {}
        return {}
    
    skills: Dict[str, Skill] = {}
    skill_files = list(target_dir.rglob("SKILL.md"))
    
    logger.info(f"Found {len(skill_files)} SKILL.md files")
    
    for skill_file in skill_files:
        skill = load_skill_from_file(skill_file)
        if skill:
            skills[skill.name] = skill
            logger.debug(f"  ✓ {skill.name}")
    
    logger.info(f"Loaded {len(skills)} skills: {', '.join(skills.keys())}")
    
    _SKILLS_CACHE = skills
    return skills


def get_skill_for_task(task: str, skills: Optional[Dict[str, Skill]] = None) -> Optional[Skill]:
    """
    Select the best skill for a given task.
    
    Uses keyword matching and task-to-skill mapping.
    
    Args:
        task: Task description or type (e.g., "mission", "prose", "news")
        skills: Pre-loaded skills dict; if None, loads from cache
    
    Returns:
        Best-matching Skill or None
    """
    if skills is None:
        skills = load_all_skills()
    
    if not skills:
        return None
    
    task_lower = task.lower()
    
    # Direct task-to-skill mappings
    task_mappings = {
        "mission": "cw-mission-gen",
        "prose": "cw-prose-writing",
        "writing": "cw-prose-writing",
        "news": "cw-news-gen",
        "bulletin": "cw-news-gen",
        "character": "tower-bot",
        "npc": "tower-bot",
        "world": "dnd5e-srd",
        "d&d": "dnd5e-srd",
        "rules": "dnd5e-srd",
    }
    
    # Check exact matches
    for keyword, skill_name in task_mappings.items():
        if keyword in task_lower and skill_name in skills:
            return skills[skill_name]
    
    # Check keyword matching
    best_match = None
    best_score = 0
    
    for skill in skills.values():
        keywords = set(skill.metadata.get("keywords", []))
        if not keywords:
            keywords = {skill.name.lower().replace("-", " ")}
        
        score = sum(1 for kw in keywords if kw in task_lower)
        if score > best_score:
            best_score = score
            best_match = skill
    
    # Fallback to prose writing if no match
    if best_match is None and "cw-prose-writing" in skills:
        best_match = skills["cw-prose-writing"]
    
    return best_match


def list_available_skills(skills: Optional[Dict[str, Skill]] = None) -> List[Dict[str, Any]]:
    """
    List all available skills with metadata.
    
    Args:
        skills: Pre-loaded skills dict; if None, loads from cache
    
    Returns:
        List of dicts with skill info (name, description, path)
    """
    if skills is None:
        skills = load_all_skills()
    
    return [
        {
            "name": skill.name,
            "description": skill.description,
            "path": str(skill.path),
            "size": len(skill.content),
        }
        for skill in skills.values()
    ]


def get_skill_content(
    skill_name: str, 
    skills: Optional[Dict[str, Skill]] = None
) -> Optional[str]:
    """
    Get the markdown content of a specific skill.
    
    Args:
        skill_name: Name of the skill (e.g., "cw-mission-gen")
        skills: Pre-loaded skills dict
    
    Returns:
        Markdown content or None if not found
    """
    if skills is None:
        skills = load_all_skills()
    
    skill = skills.get(skill_name)
    return skill.content if skill else None


def build_system_prompt_with_skills(
    base_prompt: str,
    task: str,
    skills: Optional[Dict[str, Skill]] = None,
    use_multiple: bool = False,
) -> str:
    """
    Enhance a system prompt with relevant skill content.
    
    Selects 1 or more skills related to the task and appends their content
    to the system prompt for improved generation quality.
    
    Args:
        base_prompt: Starting system prompt
        task: Task description (used to select relevant skills)
        skills: Pre-loaded skills dict
        use_multiple: If True, use 2-3 related skills instead of just 1
    
    Returns:
        Enhanced system prompt with skill context
    """
    if skills is None:
        skills = load_all_skills()
    
    if not skills:
        return base_prompt
    
    # Select skills to use
    selected_skills = []
    primary_skill = get_skill_for_task(task, skills)
    
    if primary_skill:
        selected_skills.append(primary_skill)
        
        if use_multiple:
            # Add complementary skills
            if "prose" in task.lower() or "write" in task.lower():
                if "cw-prose-writing" in skills and skills["cw-prose-writing"] != primary_skill:
                    selected_skills.append(skills["cw-prose-writing"])
            
            if "mission" in task.lower():
                if "dnd5e-srd" in skills and skills["dnd5e-srd"] not in selected_skills:
                    selected_skills.append(skills["dnd5e-srd"])
    
    # Build enhanced prompt
    enhanced = base_prompt + "\n\n" + "="*80
    enhanced += "\n### CREATIVE WRITING SKILLS CONTEXT\n"
    enhanced += "="*80 + "\n"
    
    for i, skill in enumerate(selected_skills, 1):
        enhanced += f"\n**Skill {i}: {skill.name}**\n"
        enhanced += f"*{skill.description}*\n"
        enhanced += "-" * 80 + "\n"
        enhanced += skill.content
        enhanced += "\n"
    
    enhanced += "\n" + "="*80 + "\n"
    
    return enhanced


async def generate_with_skills(
    prompt: str,
    task: str,
    model_name: str = None,  # Uses OLLAMA_MODEL env var
    skills: Optional[Dict[str, Skill]] = None,
    use_tools: bool = False,
) -> Optional[str]:
    """
    Generate content using Ollama with skill-enhanced system prompt.
    
    Args:
        prompt: User prompt for generation
        task: Task type (used for skill selection)
        model_name: Ollama model to use (default: mistral)
        skills: Pre-loaded skills dict
        use_tools: If True, enable OpenClaw function calling (experimental)
    
    Returns:
        Generated text or None on error
    """
    import httpx
    
    if skills is None:
        skills = load_all_skills()
    
    # Build enhanced system prompt
    base_system = (
        "You are an expert creative writer for D&D campaigns. "
        "Create engaging, specific, grounded content with vivid details."
    )
    system_prompt = build_system_prompt_with_skills(base_system, task, skills)
    
    # Call Ollama
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                ollama_url,
                json={
                    "model": model_name,
                    "prompt": prompt,
                    "system": system_prompt,
                    "stream": False,
                    "temperature": 0.8,
                    "top_p": 0.95,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "").strip()
    except Exception as e:
        logger.error(f"Ollama generation error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────
# Global Control
# ─────────────────────────────────────────────────────────────────────────

def set_use_skills(enabled: bool) -> None:
    """
    Enable or disable skills usage globally.
    
    When disabled, generation functions use baseline prompts.
    
    Args:
        enabled: True to enable skills, False to disable
    """
    global _USE_SKILLS
    _USE_SKILLS = enabled
    logger.info(f"Skills usage: {'enabled' if enabled else 'disabled'}")


def get_use_skills() -> bool:
    """Get current global skills status."""
    return _USE_SKILLS


def clear_skills_cache() -> None:
    """Clear the skills cache (useful for testing or reloading)."""
    global _SKILLS_CACHE
    _SKILLS_CACHE = None
    logger.info("Skills cache cleared")


# ─────────────────────────────────────────────────────────────────────────
# Helper Functions for Common Modules
# ─────────────────────────────────────────────────────────────────────────

def enhance_generation_with_skills(
    prompt: str,
    task: str = "prose",
    use_skills: Optional[bool] = None,
) -> str:
    """
    Synchronous helper to enhance a prompt with skills.
    
    Use this when you need to optionally enhance a prompt but don't need
    async generation (e.g., you're passing the prompt elsewhere).
    
    Args:
        prompt: Base prompt to enhance
        task: Task type for skill selection
        use_skills: Override global setting (None = use global flag)
    
    Returns:
        Enhanced prompt if skills enabled, otherwise original prompt
    """
    if use_skills is None:
        use_skills = _USE_SKILLS
    
    if not use_skills:
        return prompt
    
    skills = load_all_skills()
    return build_system_prompt_with_skills(prompt, task, skills)


async def enhance_generation_async(
    prompt: str,
    task: str = "prose",
    use_skills: Optional[bool] = None,
) -> str:
    """
    Async helper to enhance a prompt with skills.
    
    Args:
        prompt: Base prompt to enhance
        task: Task type for skill selection
        use_skills: Override global setting (None = use global flag)
    
    Returns:
        Enhanced prompt if skills enabled, otherwise original prompt
    """
    if use_skills is None:
        use_skills = _USE_SKILLS
    
    if not use_skills:
        return prompt
    
    # Load skills asynchronously (if needed in future)
    skills = load_all_skills()
    return build_system_prompt_with_skills(prompt, task, skills)


# ─────────────────────────────────────────────────────────────────────────
# Discord Command Helpers
# ─────────────────────────────────────────────────────────────────────────

def format_skills_list_for_discord() -> str:
    """Format skills list for Discord embed/message."""
    skills = load_all_skills()
    if not skills:
        return "No skills loaded"
    
    lines = ["**Available Skills:**"]
    for skill in sorted(skills.values(), key=lambda s: s.name):
        desc = skill.description[:60] + ("..." if len(skill.description) > 60 else "")
        lines.append(f"• **{skill.name}** — {desc}")
    
    return "\n".join(lines[:25])  # Limit to 25 skills for embed


def format_skills_detail_for_discord(skill_name: str) -> str:
    """Format detailed skill info for Discord."""
    skills = load_all_skills()
    skill = skills.get(skill_name)
    
    if not skill:
        return f"Skill '{skill_name}' not found"
    
    # Show first 500 chars of content
    content_preview = skill.content[:500].split('\n')[0]
    
    detail = f"**{skill.name}**\n"
    detail += f"{skill.description}\n\n"
    detail += f"```\n{content_preview}\n```"
    
    return detail
