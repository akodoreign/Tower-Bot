"""
SKILLS INTEGRATION GUIDE

How to use the project-wide skills system in any module.

=============================================================================
QUICK START
=============================================================================

The skills system is now centralized and accessible project-wide:

    from src import (
        load_all_skills,
        set_use_skills,
        build_system_prompt_with_skills,
        enhance_generation_with_skills,
    )

That's it! 27 SKILL.md files are automatically loaded and available.


=============================================================================
BASIC USAGE PATTERNS
=============================================================================

1. ENHANCE A SYSTEM PROMPT (Recommended for most use cases)

    from src import enhance_generation_with_skills
    
    base_prompt = "You are a creative writer"
    task = "news-generation"
    
    # Optionally enable skills globally first
    # from src import set_use_skills
    # set_use_skills(True)
    
    # Get enhanced prompt (only enhanced if skills enabled)
    enhanced_prompt = enhance_generation_with_skills(base_prompt, task)
    
    # Use enhanced_prompt with your LLM


2. LOAD ALL SKILLS AND SELECT ONE

    from src import load_all_skills, get_skill_for_task
    
    skills = load_all_skills()  # Dict[str, Skill]
    
    # Get best skill for your task
    skill = get_skill_for_task("mission generation", skills)
    
    if skill:
        print(f"Using skill: {skill.name}")
        print(f"Content: {skill.content[:500]}")


3. BUILD ENHANCED PROMPT WITH SPECIFIC SKILLS

    from src import (
        load_all_skills,
        build_system_prompt_with_skills,
    )
    
    skills = load_all_skills()
    
    base_system = "You are a creative writer for Tower of Last Chance"
    
    enhanced_system = build_system_prompt_with_skills(
        base_prompt=base_system,
        task="prose writing",
        skills=skills,
        use_multiple=True,  # Include 2-3 related skills, not just 1
    )
    
    # Now use enhanced_system for generation


4. GLOBAL ENABLE/DISABLE (Control at runtime)

    from src import set_use_skills, get_use_skills
    
    # Enable skills for all subsequent generations
    set_use_skills(True)
    
    # Check current status
    if get_use_skills():
        print("Skills enabled")
    
    # Disable when done
    set_use_skills(False)


5. LIST AVAILABLE SKILLS

    from src import list_available_skills
    
    skills_info = list_available_skills()
    
    for skill in skills_info:
        print(f"{skill['name']}: {skill['description']}")


6. GET SPECIFIC SKILL CONTENT

    from src import get_skill_content
    
    # Get content of a specific skill
    mission_content = get_skill_content("cw-mission-gen")
    
    # Use in your prompt
    prompt = f"Using these guidelines: {mission_content}\n\n{your_prompt}"


=============================================================================
MODULE-SPECIFIC EXAMPLES
=============================================================================

--- src/news_feed.py ---

Add skills to bulletin generation:

    from src import enhance_generation_with_skills
    
    def generate_bulletin():
        base_prompt = "Generate a world event for Tower of Last Chance"
        
        # Enhance with prose writing and news generation skills
        enhanced = enhance_generation_with_skills(
            base_prompt,
            task="news-generation",
        )
        
        # Use enhanced prompt with Ollama
        response = await ollama_call(prompt=enhanced)


--- src/mission_board.py ---

Add skills to mission posting:

    from src import load_all_skills, build_system_prompt_with_skills
    
    async def post_mission(mission):
        skills = load_all_skills()
        
        base_system = "You are writing a mission board post"
        
        system_prompt = build_system_prompt_with_skills(
            base_system,
            task="mission generation",
            skills=skills,
            use_multiple=False,
        )
        
        # Use system_prompt for mission text generation


--- src/character_profiles.py ---

Add skills to character generation:

    from src import enhance_generation_with_skills
    
    def generate_character_profile(char_name: str):
        prompt = f"Generate a detailed character profile for {char_name}"
        
        enhanced_prompt = enhance_generation_with_skills(
            prompt,
            task="prose writing",
        )
        
        # Generate character description with skills


--- src/npc_lifecycle.py ---

Add skills to NPC event generation:

    from src import get_skill_for_task, load_all_skills
    
    async def generate_npc_event(npc):
        skills = load_all_skills()
        prose_skill = get_skill_for_task("prose", skills)
        
        if prose_skill:
            # Use prose guidelines for NPC event text
            prompt = f"Using these prose principles: {prose_skill.content}\n\n{event_prompt}"


--- src/bounty_board.py ---

Add skills to bounty generation:

    from src import enhance_generation_with_skills
    
    def generate_bounty_post(bounty_info):
        prompt = f"Generate a bounty board posting: {bounty_info}"
        
        enhanced = enhance_generation_with_skills(
            prompt,
            task="mission generation",
        )
        
        return enhanced


--- src/cogs/missions.py (Discord command) ---

Allow users to enable/disable skills:

    from src import set_use_skills, get_use_skills
    import discord
    from discord import app_commands
    
    @app_commands.command(name="mission_skills")
    async def mission_skills(interaction: discord.Interaction, enable: bool):
        '''Toggle creative writing skills for mission generation'''
        set_use_skills(enable)
        status = "enabled" if enable else "disabled"
        await interaction.response.send_message(
            f"Mission generation skills: {status}"
        )


=============================================================================
AVAILABLE SKILLS (27 total)
=============================================================================

Core Creative Writing:
  - cw-mission-gen       → D&D mission structure, faction voice
  - cw-prose-writing    → Prose principles (specific, grounded, concise)
  - cw-news-gen         → In-world news generation
  - cw-story-critique   → Story quality evaluation

World & D&D:
  - dnd5e-srd           → D&D 5E rules and mechanics
  - dnd-mission-docx    → Mission document patterns
  - tower-bot           → Tower of Last Chance campaign context
  - tower-bot-files     → File organization patterns

Plus 19 others for specialized tasks...

Use: from src import list_available_skills()


=============================================================================
PERFORMANCE & CACHING
=============================================================================

Skills are cached after first load — subsequent calls are fast:

    from src import load_all_skills, clear_skills_cache
    
    # First call loads from disk
    skills = load_all_skills()  # ~50-100ms
    
    # Subsequent calls use cache
    skills = load_all_skills()  # ~1-2ms
    
    # Force reload
    clear_skills_cache()
    skills = load_all_skills()  # Disk load again


=============================================================================
BEST PRACTICES
=============================================================================

1. Use enhance_generation_with_skills() for simple cases
   - It handles enable/disable logic automatically
   - Returns original prompt if skills disabled

2. Load skills once at startup if using repeatedly
   - Cache is automatic, but explicit loading is faster
   - Store in module variable for reuse

3. Check get_use_skills() before expensive operations
   - Skip skill loading if disabled

4. Use use_multiple=True for complex generation
   - Provides 2-3 complementary skills instead of just 1

5. Task names should match skill keywords
   - "mission", "prose", "news", "writing", "dnd", etc.
   - See get_skill_for_task() for mapping

6. For Discord commands, allow users to toggle
   - Add `/mission_skills enable|disable` type commands
   - Store preference in user settings

Example setup function for modules:

    async def setup_skills():
        '''Called at module init'''
        from src import load_all_skills, clear_skills_cache
        global skills_cache
        clear_skills_cache()
        skills_cache = load_all_skills()
        logger.info(f"Skills ready: {len(skills_cache)} loaded")


=============================================================================
NEW FEATURES WITH SKILLS
=============================================================================

Enabled by centralized skills system:

• Mission generation with faction voice guidelines
• News bulletins with prose quality rules
• NPC events with character voice consistency
• Bounty posts with adventure hook structure
• Character profiles with personality consistency
• All generation now optional (can disable for baseline)
• User preferences for skill usage
• Consistent quality across all generated content


=============================================================================
TROUBLESHOOTING
=============================================================================

Q: Skills not being used?
A: Check get_use_skills() returns True, or call set_use_skills(True)

Q: Prompt too long after adding skills?
A: Use use_multiple=False to add only 1 skill instead of 2-3

Q: Need to reload skills?
A: Call clear_skills_cache() then load_all_skills()

Q: Import errors?
A: Ensure PyYAML is installed: pip install PyYAML>=6.0

Q: Want to disable skills for testing?
A: set_use_skills(False) will return original prompts unchanged


=============================================================================
NEXT STEPS
=============================================================================

1. Enable skills in news_feed.py for better prose
2. Add skill-based generation to mission_board.py
3. Create Discord command to let users toggle skills
4. Monitor generation quality with/without skills
5. Consider adding skill usage metrics/logging
