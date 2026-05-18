"""
module_generator.py — DEPRECATED

This module has been replaced by MissionCompiler in src/mission_compiler.py.

The old 14-pass system has been archived to:
  backups/archived_module_generator/module_generator_20260402.py

All mission generation now uses the new pipeline:
  1. Build JSON via MissionJsonBuilder
  2. Compile via MissionCompiler with agent enhancement
  3. Output docx via Python docx_builder

If you're seeing this error, update your import:
  OLD: from src.module_generator import generate_module
  NEW: from src.mission_compiler import compile_mission

For the cog entry point:
  from src.cogs.module_gen import generate_and_post_module
"""

raise ImportError(
    "module_generator.py is DEPRECATED. "
    "Use MissionCompiler from src.mission_compiler instead. "
    "See backups/archived_module_generator/ for the old code."
)
