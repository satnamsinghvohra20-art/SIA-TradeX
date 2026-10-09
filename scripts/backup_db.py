#!/usr/bin/env python3
"""
SIA-TradeX — Hot SQLite WAL Database Backup Script
Performs an online, non-blocking vacuum/backup of sia_tradex.db with timestamping and retention pruning.
"""

import os
import sys
import sqlite3
import datetime
import logging
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("DB_Backup")


def perform_backup(retention_days: int = 7) -> str:
    db_path = Path(settings.DB_PATH)
    if not db_path.exists():
        logger.error(f"Source database not found at {db_path}")
        return ""

    backup_dir = PROJECT_ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"sia_tradex_backup_{timestamp}.db"

    logger.info(f"Starting online hot backup from {db_path} to {backup_file}...")

    src_conn = sqlite3.connect(str(db_path))
    dst_conn = sqlite3.connect(str(backup_file))

    try:
        # Non-blocking SQLite online backup API
        with dst_conn:
            src_conn.backup(dst_conn, pages=100, sleep=0.01)
        logger.info(f"Backup successfully completed: {backup_file} ({backup_file.stat().st_size} bytes)")
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        if backup_file.exists():
            backup_file.unlink()
        raise
    finally:
        src_conn.close()
        dst_conn.close()

    # Retention pruning
    now = datetime.datetime.now(datetime.timezone.utc)
    for old_backup in backup_dir.glob("sia_tradex_backup_*.db"):
        mtime = datetime.datetime.fromtimestamp(old_backup.stat().st_mtime, tz=datetime.timezone.utc)
        if (now - mtime).days > retention_days:
            logger.info(f"Pruning expired backup: {old_backup.name}")
            old_backup.unlink()

    return str(backup_file)


if __name__ == "__main__":
    try:
        out_path = perform_backup()
        print(f"SUCCESS: Backup saved to {out_path}")
    except Exception as ex:
        print(f"FAILURE: Backup error: {ex}")
        sys.exit(1)
