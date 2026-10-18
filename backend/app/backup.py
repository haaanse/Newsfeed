"""Konsistentes SQLite-Backup im laufenden Betrieb: python -m app.backup <ziel.db>"""
import sqlite3
import sys

from .db import db_path

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "/data/backup.db"
    src = sqlite3.connect(db_path())
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    print(f"Backup geschrieben: {target}")
