"""
docx_builder.py — Wraps the Node.js docx generation script.

Provides:
- JSON to DOCX conversion via build_module_docx.js
- File path management
- Error handling for the Node subprocess
"""

from __future__ import annotations

import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "generated_modules"

# Ensure output directory exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


async def build_docx(
    module_data: dict,
    filename: Optional[str] = None,
    timeout: float = 60.0,
) -> Optional[Path]:
    """
    Build a .docx file from module data using the Node.js script.
    
    Args:
        module_data: Dict containing all module sections
        filename: Optional output filename (without extension)
        timeout: Subprocess timeout in seconds
    
    Returns:
        Path to the generated .docx file, or None on failure
    """
    if not filename:
        title = module_data.get("title", "mission")
        safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
        safe_title = safe_title.replace(" ", "_")[:50]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{safe_title}_{timestamp}"
    
    filename = filename.rsplit(".", 1)[0]
    
    output_path = OUTPUT_DIR / f"{filename}.docx"
    script_path = SCRIPTS_DIR / "build_module_docx.js"
    
    if not script_path.exists():
        logger.error(f"❌ DOCX build script not found: {script_path}")
        return None
    
    json_path = OUTPUT_DIR / f"{filename}_temp.json"
    
    try:
        json_path.write_text(json.dumps(module_data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"❌ Failed to write temp JSON: {e}")
        return None
    
    try:
        proc = await asyncio.create_subprocess_exec(
            "node",
            str(script_path),
            str(json_path),
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout
        )
        
        if proc.returncode != 0:
            logger.error(f"❌ DOCX build failed: {stderr.decode()}")
            return None
        
        if output_path.exists():
            logger.info(f"✅ DOCX generated: {output_path}")
            return output_path
        else:
            logger.error("❌ DOCX file not created")
            return None
            
    except asyncio.TimeoutError:
        logger.error(f"❌ DOCX build timed out after {timeout}s")
        return None
    except FileNotFoundError:
        logger.error("❌ Node.js not found. Ensure Node is installed.")
        return None
    except Exception as e:
        logger.error(f"❌ DOCX build error: {e}")
        return None
    finally:
        if json_path.exists():
            try:
                json_path.unlink()
            except Exception:
                pass


def format_module_for_docx(
    title: str,
    overview: str,
    acts_1_2: str,
    acts_3_4: str,
    act_5_rewards: str,
    metadata: Optional[dict] = None,
) -> dict:
    """
    Format module sections into the structure expected by build_module_docx.js.
    
    Args:
        title: Module title
        overview: Overview section text
        acts_1_2: Acts 1-2 text
        acts_3_4: Acts 3-4 text
        act_5_rewards: Act 5 and rewards text
        metadata: Optional metadata (faction, tier, cr, etc.)
    
    Returns:
        Dict formatted for the Node.js script
    """
    if metadata is None:
        metadata = {}
    
    return {
        "title": title,
        "metadata": {
            "faction": metadata.get("faction", "Unknown"),
            "tier": metadata.get("tier", "Standard"),
            "cr": metadata.get("cr", 5),
            "generated": datetime.now().isoformat(),
            "version": "2.0",
        },
        "sections": {
            "overview": overview,
            "acts_1_2": acts_1_2,
            "acts_3_4": acts_3_4,
            "act_5_rewards": act_5_rewards,
        },
        "raw_content": f"{overview}\n\n{acts_1_2}\n\n{acts_3_4}\n\n{act_5_rewards}",
    }


def validate_module_data(module_data: dict) -> bool:
    """
    Validate that module data has required sections.
    
    Returns True if valid, False otherwise.
    """
    required_sections = ["overview", "acts_1_2", "acts_3_4", "act_5_rewards"]
    
    sections = module_data.get("sections", {})
    
    for section in required_sections:
        if section not in sections or not sections[section]:
            logger.warning(f"⚠️ Missing or empty section: {section}")
            return False
    
    if not module_data.get("title"):
        logger.warning("⚠️ Missing module title")
        return False
    
    return True


def get_output_dir() -> Path:
    """Get the output directory path."""
    return OUTPUT_DIR


def list_generated_modules(limit: int = 10) -> list:
    """List recently generated module files."""
    if not OUTPUT_DIR.exists():
        return []
    
    files = sorted(
        OUTPUT_DIR.glob("*.docx"),
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )
    
    return [
        {
            "filename": f.name,
            "path": str(f),
            "size": f.stat().st_size,
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        }
        for f in files[:limit]
    ]


def cleanup_old_modules(days: int = 7) -> int:
    """
    Remove module files older than specified days.
    
    Returns count of deleted files.
    """
    if not OUTPUT_DIR.exists():
        return 0
    
    import time
    cutoff = time.time() - (days * 86400)
    deleted = 0
    
    for f in OUTPUT_DIR.glob("*.docx"):
        if f.stat().st_mtime < cutoff:
            try:
                f.unlink()
                deleted += 1
                logger.info(f"🗑️ Cleaned up old module: {f.name}")
            except Exception as e:
                logger.warning(f"⚠️ Could not delete {f.name}: {e}")
    
    return deleted
