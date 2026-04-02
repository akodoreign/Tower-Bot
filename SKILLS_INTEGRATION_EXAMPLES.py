"""
SKILLS INTEGRATION EXAMPLES

Example implementations showing how different modules can use the skills system.

Copy patterns from these examples to add skills to other modules.
"""

# =============================================================================
# EXAMPLE 1: News Feed Integration
# =============================================================================

# File: src/news_feed.py (modified sections)

def example_news_feed_with_skills():
    """Example: Enhance bulletin generation with news/prose skills."""
    from src import enhance_generation_with_skills
    
    async def generate_bulletin_enhanced():
        """Generate bulletin using skill-enhanced prompt."""
        
        # Original prompt
        base_prompt = """Generate a world event for Tower of Last Chance.
        
        Include:
        - Specific location name (from city gazetteer)
        - At least 2 NPCs involved (with names)
        - Clear consequence for the world
        - Hook for adventurers
        """
        
        # Enhance with news generation + prose writing skills
        enhanced_prompt = enhance_generation_with_skills(
            prompt=base_prompt,
            task="news-generation",
        )
        # Now use enhanced_prompt instead of base_prompt
        
        response = await ollama_call(prompt=enhanced_prompt)
        return response


# =============================================================================
# EXAMPLE 2: Mission Board Integration
# =============================================================================

# File: src/mission_board.py (modified sections)

def example_mission_board_with_skills():
    """Example: Enhance mission posting with mission/prose skills."""
    from src import load_all_skills, build_system_prompt_with_skills
    
    async def post_mission_enhanced(mission_text: str):
        """Post mission to Discord using skill-enhanced writing."""
        
        # Load skills once at module init (do this in setup_hook)
        skills = load_all_skills()
        
        # Enhanced system prompt for mission writing
        system_prompt = build_system_prompt_with_skills(
            base_prompt="""\
                You are writing a mission board posting for adventurers.
                Be specific, grounded, and engaging.
                Include clear hooks and multiple resolution options.
            """,
            task="mission generation",  # Selects cw-mission-gen skill
            skills=skills,
            use_multiple=True,  # Include prose + mission skills
        )
        
        # Use system_prompt for mission text generation
        response = await ollama_call(
            prompt=mission_text,
            system=system_prompt,
        )
        return response


# =============================================================================
# EXAMPLE 3: Character Generation Integration
# =============================================================================

# File: src/character_profiles.py (modified sections)

def example_character_with_skills():
    """Example: Enhance character profile generation with prose skills."""
    from src import enhance_generation_with_skills
    
    def generate_character_description(char_data: dict):
        """Generate character description using prose skills."""
        
        base_prompt = f"""Create a vivid character profile for:
        Name: {char_data['name']}
        Class: {char_data['class']}
        Background: {char_data['background']}
        
        Include appearance, personality, and motivations.
        Be specific and grounded (use real details, not generic descriptions).
        """
        
        # Enhance with prose writing skills
        enhanced = enhance_generation_with_skills(
            prompt=base_prompt,
            task="prose writing",
        )
        
        # Generate with enhanced prompt
        response = generate_with_ollama(enhanced)
        return response


# =============================================================================
# EXAMPLE 4: NPC Lifecycle Integration
# =============================================================================

# File: src/npc_lifecycle.py (modified sections)

def example_npc_lifecycle_with_skills():
    """Example: Enhance NPC event generation with prose skills."""
    from src import get_skill_for_task, load_all_skills
    
    async def generate_npc_event_enhanced(npc_name: str, faction: str):
        """Generate an NPC life event using prose and world skills."""
        
        skills = load_all_skills()
        
        # Get the prose writing skill for specific writing guidance
        prose_skill = get_skill_for_task("prose", skills)
        dnd_skill = get_skill_for_task("dnd", skills)
        
        prompt = f"""Generate a significant life event for {npc_name} ({faction}).
        
        The event should:
        - Have specific, grounded consequences
        - Impact the faction or world
        - Create adventure hooks
        
        {prose_skill.content if prose_skill else ""}
        {dnd_skill.content if dnd_skill else ""}
        """
        
        response = await ollama_call(prompt)
        return response


# =============================================================================
# EXAMPLE 5: Discord Command Integration
# =============================================================================

# File: src/cogs/world.py (modified sections)

def example_discord_command_with_skills():
    """Example: Add Discord command to toggle skills globally."""
    from src import set_use_skills, get_use_skills
    from discord.ext import commands
    import discord
    from discord import app_commands
    
    class WorldCog(commands.Cog):
        def __init__(self, client):
            self.client = client
        
        @app_commands.command(name="skills")
        @app_commands.describe(
            action="Enable or disable creative writing skills"
        )
        async def toggle_skills(
            self,
            interaction: discord.Interaction,
            action: str,
        ):
            """Toggle AI generation skills globally."""
            
            if action.lower() in ("enable", "on", "true", "yes"):
                set_use_skills(True)
                embed = discord.Embed(
                    title="Skills ENABLED",
                    description="Creative writing skills activated for all generation.",
                    color=discord.Color.green(),
                )
            elif action.lower() in ("disable", "off", "false", "no"):
                set_use_skills(False)
                embed = discord.Embed(
                    title="Skills DISABLED",
                    description="Generation using baseline prompts.",
                    color=discord.Color.red(),
                )
            else:
                embed = discord.Embed(
                    title="Skills Status",
                    description=f"Currently: {'ENABLED' if get_use_skills() else 'DISABLED'}",
                    color=discord.Color.blue(),
                )
            
            await interaction.response.send_message(embed=embed)


# =============================================================================
# EXAMPLE 6: Module Startup Integration
# =============================================================================

# File: src/bot.py (add to setup_hook or similar)

def example_bot_startup_with_skills():
    """Example: Initialize skills system when bot starts."""
    from src import load_all_skills, set_use_skills, logger as src_logger
    
    async def setup_skills():
        """Called when bot initializes."""
        try:
            # Load all skills at startup
            skills = load_all_skills()
            src_logger.info(f"Skills system ready: {len(skills)} skills loaded")
            
            # Enable skills by default
            set_use_skills(True)
            src_logger.info("Skills enabled for all generation")
            
        except Exception as e:
            src_logger.error(f"Failed to initialize skills: {e}")
            src_logger.warning("Generation will continue without skills")


# =============================================================================
# EXAMPLE 7: Conditional Pattern (Skills Optional)
# =============================================================================

# File: Any module

def example_conditional_skills():
    """Example: Use skills only if enabled globally."""
    from src import get_use_skills, enhance_generation_with_skills
    
    def generate_with_optional_skills(prompt: str, task: str):
        """
        Generate content, optionally using skills.
        
        If skills enabled globally, enhances prompt.
        Otherwise returns unchanged prompt.
        """
        
        if get_use_skills():
            prompt = enhance_generation_with_skills(prompt, task)
        
        # Now use prompt for generation
        return prompt


# =============================================================================
# EXAMPLE 8: Metrics/Logging
# =============================================================================

# File: Any module

def example_logging_with_skills():
    """Example: Log when skills are used."""
    from src import get_use_skills, load_all_skills
    from src.log import logger
    
    def generate_with_metrics(prompt: str, task: str):
        """Generate content and log skill usage."""
        
        skills_enabled = get_use_skills()
        skills = load_all_skills() if skills_enabled else {}
        
        logger.info(f"Generating {task}...")
        logger.info(f"  Skills: {'enabled' if skills_enabled else 'disabled'}")
        if skills_enabled:
            logger.info(f"  Skills available: {len(skills)}")
        
        # Perform generation
        # ...
        
        logger.info(f"  Generation complete")


# =============================================================================
# Copy-Paste Template: Quick Integration
# =============================================================================

"""
QUICK COPY-PASTE TEMPLATE:

To add skills to any module:

1. At top of file:
    from src import enhance_generation_with_skills

2. In your generation function:
    prompt = enhance_generation_with_skills(
        prompt="your existing prompt",
        task="mission",  # or "prose", "news", etc.
    )
    
    # Then use enhanced prompt as normal
    response = await llm_call(prompt=prompt)

That's it! Skills will be used if enabled globally, otherwise returns 
the original prompt unchanged.
"""
