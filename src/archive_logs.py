#!/usr/bin/env python3
"""
archive_logs.py — Parse and archive bot logs.
Extracts key events, compresses full log, rotates.
"""

import os
import re
import gzip
import shutil
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# Paths
LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
ARCHIVES_DIR = Path(__file__).resolve().parent.parent / "campaign_docs" / "archives" / "logs"
STDERR_LOG = LOGS_DIR / "bot_stderr.log"

def ensure_archive_dir():
    ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)

def parse_log_events(log_path: Path) -> dict:
    """Parse log file and extract key statistics and events."""
    stats = {
        "total_lines": 0,
        "errors": [],
        "warnings": [],
        "bulletins_posted": 0,
        "missions_posted": 0,
        "missions_claimed": 0,
        "story_images": 0,
        "npc_lifecycle_runs": 0,
        "character_polls": 0,
        "tia_reactions": 0,
        "session_starts": [],
        "session_resumes": [],
    }
    
    if not log_path.exists():
        return stats
    
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stats["total_lines"] += 1
                
                # Extract timestamp and message
                if "ERROR" in line:
                    # Extract just the key part
                    match = re.search(r"ERROR.*?-> (.+)", line)
                    if match:
                        stats["errors"].append(match.group(1).strip()[:150])
                
                elif "WARNING" in line or "WARN" in line:
                    match = re.search(r"WARN.*?-> (.+)", line)
                    if match:
                        stats["warnings"].append(match.group(1).strip()[:150])
                
                # Count key events
                if "Bulletin posted" in line:
                    stats["bulletins_posted"] += 1
                elif "Mission posted" in line:
                    stats["missions_posted"] += 1
                elif "Mission claimed" in line:
                    stats["missions_claimed"] += 1
                elif "Story image posted" in line:
                    stats["story_images"] += 1
                elif "Lifecycle complete" in line:
                    stats["npc_lifecycle_runs"] += 1
                elif "Character monitor:" in line and "polling" in line:
                    stats["character_polls"] += 1
                elif "TIA reaction fired" in line:
                    stats["tia_reactions"] += 1
                elif "TOWER BOT STARTED" in line:
                    match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                    if match:
                        stats["session_starts"].append(match.group(1))
                elif "RESUMED session" in line:
                    match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                    if match:
                        stats["session_resumes"].append(match.group(1))
    except Exception as e:
        print(f"Error parsing log: {e}")
    
    return stats

def generate_summary(stats: dict) -> str:
    """Generate a human-readable summary of log stats."""
    lines = [
        "=" * 60,
        f"BOT LOG SUMMARY — Archived {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "=" * 60,
        "",
        f"Total log lines: {stats['total_lines']:,}",
        "",
        "## Activity Summary",
        f"  Bulletins posted:     {stats['bulletins_posted']}",
        f"  Missions posted:      {stats['missions_posted']}",
        f"  Missions claimed:     {stats['missions_claimed']}",
        f"  Story images:         {stats['story_images']}",
        f"  NPC lifecycle runs:   {stats['npc_lifecycle_runs']}",
        f"  Character polls:      {stats['character_polls']}",
        f"  TIA market reactions: {stats['tia_reactions']}",
        "",
        f"## Session Info",
        f"  Bot starts:   {len(stats['session_starts'])}",
        f"  Reconnects:   {len(stats['session_resumes'])}",
        "",
    ]
    
    # Add errors (deduplicated, max 20)
    if stats["errors"]:
        lines.append("## Errors (unique)")
        unique_errors = list(dict.fromkeys(stats["errors"]))[:20]
        for err in unique_errors:
            lines.append(f"  - {err}")
        if len(stats["errors"]) > 20:
            lines.append(f"  ... and {len(stats['errors']) - 20} more")
        lines.append("")
    
    # Add warnings (deduplicated, max 10)
    if stats["warnings"]:
        lines.append("## Warnings (sample)")
        unique_warnings = list(dict.fromkeys(stats["warnings"]))[:10]
        for warn in unique_warnings:
            lines.append(f"  - {warn}")
        if len(stats["warnings"]) > 10:
            lines.append(f"  ... and {len(stats['warnings']) - 10} more")
        lines.append("")
    
    lines.append("=" * 60)
    return "\n".join(lines)

def archive_log():
    """Archive the current stderr log with compression."""
    ensure_archive_dir()
    
    if not STDERR_LOG.exists() or STDERR_LOG.stat().st_size == 0:
        print("No log to archive")
        return
    
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    
    # Parse and generate summary
    print("Parsing log events...")
    stats = parse_log_events(STDERR_LOG)
    summary = generate_summary(stats)
    
    # Save summary
    summary_path = ARCHIVES_DIR / f"summary_{timestamp}.txt"
    summary_path.write_text(summary, encoding="utf-8")
    print(f"Summary saved: {summary_path.name}")
    
    # Compress full log with gzip
    archive_path = ARCHIVES_DIR / f"bot_stderr_{timestamp}.log.gz"
    print(f"Compressing log ({STDERR_LOG.stat().st_size / 1024:.1f}KB)...")
    
    with open(STDERR_LOG, "rb") as f_in:
        with gzip.open(archive_path, "wb", compresslevel=9) as f_out:
            shutil.copyfileobj(f_in, f_out)
    
    compressed_size = archive_path.stat().st_size
    original_size = STDERR_LOG.stat().st_size
    ratio = (1 - compressed_size / original_size) * 100
    
    print(f"Compressed: {archive_path.name} ({compressed_size / 1024:.1f}KB, {ratio:.0f}% reduction)")
    
    # Clear original log (keep file, just truncate)
    with open(STDERR_LOG, "w", encoding="utf-8") as f:
        f.write(f"# Log rotated at {datetime.now().isoformat()}\n")
        f.write(f"# Previous log archived to: {archive_path.name}\n\n")
    
    print(f"Original log cleared. Archive complete!")
    print(f"\nSummary:\n{summary}")

if __name__ == "__main__":
    archive_log()
