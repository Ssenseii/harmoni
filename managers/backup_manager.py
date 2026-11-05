import os
import shutil
from datetime import datetime
from typing import Optional, List
from utils.logger import log_info, log_warning, log_error
from utils.jsonio import load_json, write_json_atomic
from constants import APP_DIR

# Default backup directory
BACKUP_DIR = os.path.join(APP_DIR, "data", "backups")

# Files that should be backed up
BACKUP_TARGETS = [
    os.path.join(APP_DIR, "data", "tracks.json"),
    os.path.join(APP_DIR, "data", "playlists.json"),
    os.path.join(APP_DIR, "data", "failed_downloads.json"),
    os.path.join(APP_DIR, "data", "download_history.json"),
]


def ensure_backup_dir():
    """Ensure the backup directory exists."""
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR, exist_ok=True)


def backup_json_file(filepath: str, config: dict = None) -> Optional[str]:
    """
    Create a timestamped backup of a JSON file.
    
    Args:
        filepath: Path to the file to backup
        config: Optional config dict for max_backups setting
    
    Returns:
        Path to the backup file, or None if backup failed
    """
    if not os.path.exists(filepath):
        return None
    
    # Check if auto_backup is enabled
    if config and not config.get("auto_backup", True):
        return None
    
    ensure_backup_dir()
    
    # Generate backup filename with timestamp
    basename = os.path.basename(filepath)
    name, ext = os.path.splitext(basename)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{name}_{timestamp}{ext}"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    
    try:
        shutil.copy2(filepath, backup_path)
        log_info(f"Created backup: {backup_name}")
        
        # Enforce max backup limit if config provided
        if config:
            max_backups = config.get("max_backups", 10)
            cleanup_old_backups(name, max_backups)
        
        return backup_path
    except Exception as e:
        log_error(f"Failed to create backup of {filepath}: {e}")
        return None


def backup_all(config: dict) -> dict:
    """
    Backup all important JSON files.
    
    Args:
        config: Configuration dict with auto_backup and max_backups settings
    
    Returns:
        Dict with backup results for each file
    """
    if not config.get("auto_backup", True):
        return {"skipped": True, "reason": "auto_backup disabled"}
    
    results = {}
    
    for filepath in BACKUP_TARGETS:
        if os.path.exists(filepath):
            backup_path = backup_json_file(filepath, config)
            results[filepath] = backup_path if backup_path else "failed"
        else:
            results[filepath] = "not_found"
    
    successful = sum(1 for v in results.values() if v not in ["failed", "not_found"])
    log_info(f"Backup complete: {successful}/{len(BACKUP_TARGETS)} files backed up")
    
    return results


def cleanup_old_backups(file_prefix: str, max_backups: int):
    """
    Remove old backups exceeding the maximum count.
    Keeps the most recent backups.
    
    Args:
        file_prefix: The base name of the file (e.g., "tracks" for tracks_*.json)
        max_backups: Maximum number of backups to keep
    """
    if max_backups <= 0:
        return  # Unlimited backups
    
    ensure_backup_dir()
    
    # Find all backups for this file
    backups = []
    for filename in os.listdir(BACKUP_DIR):
        if filename.startswith(file_prefix + "_") and filename.endswith(".json"):
            filepath = os.path.join(BACKUP_DIR, filename)
            backups.append((filepath, os.path.getmtime(filepath)))
    
    # Sort by modification time (newest first)
    backups.sort(key=lambda x: x[1], reverse=True)
    
    # Remove excess backups
    for filepath, _ in backups[max_backups:]:
        try:
            os.remove(filepath)
            log_info(f"Removed old backup: {os.path.basename(filepath)}")
        except OSError as e:
            log_warning(f"Could not remove old backup {filepath}: {e}")


def list_backups(file_prefix: Optional[str] = None) -> List[dict]:
    """
    List all available backups.
    
    Args:
        file_prefix: Optional filter by file name prefix
    
    Returns:
        List of backup info dicts with filename, path, size, and date
    """
    ensure_backup_dir()
    
    backups = []
    
    for filename in os.listdir(BACKUP_DIR):
        if not filename.endswith(".json"):
            continue
        
        if file_prefix and not filename.startswith(file_prefix + "_"):
            continue
        
        filepath = os.path.join(BACKUP_DIR, filename)
        
        try:
            stat = os.stat(filepath)
            backups.append({
                "filename": filename,
                "path": filepath,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "modified_timestamp": stat.st_mtime
            })
        except OSError:
            continue
    
    # Sort by modification time (newest first)
    backups.sort(key=lambda x: x["modified_timestamp"], reverse=True)
    
    return backups


def restore_backup(backup_path: str, target_path: str) -> bool:
    """
    Restore a backup file to its original location.
    
    Args:
        backup_path: Path to the backup file
        target_path: Path where to restore the file
    
    Returns:
        True if restore succeeded, False otherwise
    """
    if not os.path.exists(backup_path):
        log_error(f"Backup file not found: {backup_path}")
        return False
    
    try:
        data = load_json(backup_path, None)
        if data is None:
            log_error(f"Backup file is not valid JSON: {backup_path}")
            return False

        # Create backup of current file before overwriting
        if os.path.exists(target_path):
            current_backup = backup_json_file(target_path)
            if current_backup:
                log_info(f"Created backup of current file before restore")
        
        write_json_atomic(target_path, data, indent=2)
        log_info(f"Restored backup: {os.path.basename(backup_path)} -> {target_path}")
        return True
    
    except Exception as e:
        log_error(f"Failed to restore backup: {e}")
        return False


def get_backup_stats() -> dict:
    """
    Get statistics about backups.
    
    Returns:
        Dict with backup statistics
    """
    ensure_backup_dir()
    
    stats = {
        "total_backups": 0,
        "total_size": 0,
        "by_file": {},
        "oldest": None,
        "newest": None
    }
    
    all_backups = list_backups()
    
    if not all_backups:
        return stats
    
    stats["total_backups"] = len(all_backups)
    stats["total_size"] = sum(b["size"] for b in all_backups)
    stats["newest"] = all_backups[0]["modified"] if all_backups else None
    stats["oldest"] = all_backups[-1]["modified"] if all_backups else None
    
    # Group by file prefix
    for backup in all_backups:
        # Extract file prefix (e.g., "tracks" from "tracks_20250101_120000.json")
        parts = backup["filename"].rsplit("_", 2)
        if len(parts) >= 3:
            prefix = parts[0]
            if prefix not in stats["by_file"]:
                stats["by_file"][prefix] = {"count": 0, "size": 0}
            stats["by_file"][prefix]["count"] += 1
            stats["by_file"][prefix]["size"] += backup["size"]
    
    return stats


def clear_all_backups() -> int:
    """
    Remove all backup files.
    
    Returns:
        Number of backups removed
    """
    ensure_backup_dir()
    
    removed = 0
    for filename in os.listdir(BACKUP_DIR):
        if filename.endswith(".json"):
            filepath = os.path.join(BACKUP_DIR, filename)
            try:
                os.remove(filepath)
                removed += 1
            except OSError:
                pass
    
    log_info(f"Cleared {removed} backup files")
    return removed

