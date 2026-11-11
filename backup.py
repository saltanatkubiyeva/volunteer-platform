import os
import sys

from demeu.backups import create_backup, list_backups

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "demeu.db")

if __name__ == "__main__":
    if not os.path.exists(DB):
        sys.exit("Database not found: " + DB)
    if "--list" in sys.argv:
        for b in list_backups(DB):
            print(f"{b['name']}  {b['size'] // 1024} KB")
    else:
        name = create_backup(DB, "manual")
        print("Backup created: instance/backups/" + name)
