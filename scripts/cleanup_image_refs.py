"""
cleanup_image_refs.py — Trim old reference images to the new MAX_REFS=2 limit.

Deletes ref_003.png from all entity folders in:
  - campaign_docs/image_refs/npcs/
  - campaign_docs/image_refs/locations/
  - campaign_docs/image_refs/characters/
  
Also trims team/ folder to keep only the 2 most recent images.

Usage:
    python scripts/cleanup_image_refs.py           # Dry run (shows what would be deleted)
    python scripts/cleanup_image_refs.py --execute # Actually delete files
"""

import argparse
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"
REFS_DIR = DOCS_DIR / "image_refs"

# Directories to clean (entity-based structure with ref_001, ref_002, ref_003)
ENTITY_DIRS = ["npcs", "locations", "characters"]

# Max refs to keep (ref_001, ref_002 ... ref_N)
MAX_REFS = 2


def cleanup_entity_folders(dry_run: bool = True) -> dict:
    """
    Delete ref files beyond MAX_REFS from all entity folders.
    Returns stats dict.
    """
    stats = {"folders_checked": 0, "files_deleted": 0, "bytes_freed": 0, "errors": []}
    
    for entity_dir_name in ENTITY_DIRS:
        entity_dir = REFS_DIR / entity_dir_name
        if not entity_dir.exists():
            print(f"⚠️  {entity_dir_name}/ does not exist, skipping")
            continue
            
        for entity_folder in entity_dir.iterdir():
            if not entity_folder.is_dir():
                continue
                
            stats["folders_checked"] += 1
            
            # Find all ref_NNN.png files
            for ref_file in entity_folder.glob("ref_*.png"):
                # Extract the ref number
                try:
                    num = int(ref_file.stem.split("_")[1])
                except (IndexError, ValueError):
                    continue
                    
                # Delete if beyond MAX_REFS
                if num > MAX_REFS:
                    file_size = ref_file.stat().st_size
                    stats["bytes_freed"] += file_size
                    
                    if dry_run:
                        print(f"🗑️  [DRY RUN] Would delete: {ref_file.relative_to(REFS_DIR)} ({file_size // 1024} KB)")
                    else:
                        try:
                            ref_file.unlink()
                            print(f"🗑️  Deleted: {ref_file.relative_to(REFS_DIR)} ({file_size // 1024} KB)")
                            stats["files_deleted"] += 1
                        except Exception as e:
                            stats["errors"].append(f"{ref_file}: {e}")
                            print(f"❌ Failed to delete {ref_file}: {e}")
    
    return stats


def cleanup_team_folder(dry_run: bool = True) -> dict:
    """
    Trim team/ folder to keep only the 2 most recent team images.
    Returns stats dict.
    """
    stats = {"files_deleted": 0, "bytes_freed": 0, "errors": []}
    
    team_dir = REFS_DIR / "team"
    if not team_dir.exists():
        print(f"⚠️  team/ does not exist, skipping")
        return stats
    
    # Get all team*.png files, sorted by modification time (newest first)
    team_files = sorted(
        [f for f in team_dir.glob("team*.png") if f.is_file()],
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )
    
    # Keep only MAX_REFS most recent
    files_to_delete = team_files[MAX_REFS:]
    
    for team_file in files_to_delete:
        file_size = team_file.stat().st_size
        stats["bytes_freed"] += file_size
        
        if dry_run:
            print(f"🗑️  [DRY RUN] Would delete: team/{team_file.name} ({file_size // 1024} KB)")
        else:
            try:
                team_file.unlink()
                print(f"🗑️  Deleted: team/{team_file.name} ({file_size // 1024} KB)")
                stats["files_deleted"] += 1
            except Exception as e:
                stats["errors"].append(f"{team_file}: {e}")
                print(f"❌ Failed to delete {team_file}: {e}")
    
    return stats


def main():
    parser = argparse.ArgumentParser(description="Cleanup old image references")
    parser.add_argument("--execute", action="store_true", help="Actually delete files (default is dry run)")
    args = parser.parse_args()
    
    dry_run = not args.execute
    
    if dry_run:
        print("=" * 60)
        print("🔍 DRY RUN MODE — No files will be deleted")
        print("   Run with --execute to actually delete files")
        print("=" * 60)
    else:
        print("=" * 60)
        print("🗑️  EXECUTE MODE — Files will be permanently deleted")
        print("=" * 60)
    
    print()
    
    # Clean entity folders
    print("📁 Cleaning entity folders (npcs, locations, characters)...")
    entity_stats = cleanup_entity_folders(dry_run)
    
    print()
    
    # Clean team folder
    print("📁 Cleaning team folder...")
    team_stats = cleanup_team_folder(dry_run)
    
    print()
    print("=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)
    print(f"Folders checked:  {entity_stats['folders_checked']}")
    total_deleted = entity_stats['files_deleted'] + team_stats['files_deleted']
    total_bytes = entity_stats['bytes_freed'] + team_stats['bytes_freed']
    
    if dry_run:
        print(f"Files to delete:  {total_deleted} files ({total_bytes / 1024 / 1024:.2f} MB)")
    else:
        print(f"Files deleted:    {total_deleted} files")
        print(f"Space freed:      {total_bytes / 1024 / 1024:.2f} MB")
    
    all_errors = entity_stats.get('errors', []) + team_stats.get('errors', [])
    if all_errors:
        print(f"Errors:           {len(all_errors)}")
        for err in all_errors:
            print(f"  - {err}")


if __name__ == "__main__":
    main()
