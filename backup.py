"""
Backs up trades.db (and any screenshots) to OneDrive on every app startup, so
a local disk failure, a lost/damaged machine, or a bad edit doesn't wipe out
the journal. Runs once at startup, not per-request or per-save - keeps this
simple and avoids the I/O cost of backing up on every trade change.
"""
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "trades.db"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"

BACKUP_ROOT = Path.home() / "OneDrive" / "LibertamBackups"
KEEP_LAST_N = 14


def _backup_database():
    if not DB_PATH.exists():
        return
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dest = BACKUP_ROOT / f"trades_{timestamp}.db"

    # Use SQLite's own backup API rather than a plain file copy, so the backup
    # is a consistent snapshot even if the app is mid-write when this runs.
    src_conn = sqlite3.connect(DB_PATH)
    dest_conn = sqlite3.connect(dest)
    with dest_conn:
        src_conn.backup(dest_conn)
    src_conn.close()
    dest_conn.close()

    # Rotation: keep only the most recent KEEP_LAST_N backups.
    backups = sorted(BACKUP_ROOT.glob("trades_*.db"))
    for old in backups[:-KEEP_LAST_N]:
        old.unlink()


def _backup_screenshots():
    """Additive only - never deletes a file from the backup, even if it was
    removed from the live screenshots folder, so this also doubles as a
    safety net against an accidental screenshot deletion."""
    if not SCREENSHOTS_DIR.exists():
        return
    dest_dir = BACKUP_ROOT / "screenshots"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for src_file in SCREENSHOTS_DIR.iterdir():
        if not src_file.is_file():
            continue
        dest_file = dest_dir / src_file.name
        if not dest_file.exists():
            shutil.copy2(src_file, dest_file)


def run_backup():
    """Best-effort: a missing/unavailable OneDrive folder must never block
    the app from starting."""
    try:
        _backup_database()
        _backup_screenshots()
    except Exception as e:
        print(f"[backup] skipped: {e}")
