import os
import sys

from demeu.backups import list_backups, restore_backup

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "demeu.db")

if __name__ == "__main__":
    backups = list_backups(DB)
    if not backups:
        sys.exit("No backups in instance/backups")
    if len(sys.argv) > 1:
        name = os.path.basename(sys.argv[1])
    else:
        for i, b in enumerate(backups, 1):
            print(f"{i:>2}. {b['name']}  {b['size'] // 1024} KB")
        choice = input("Number of the backup to restore: ").strip()
        if not choice.isdigit() or not 1 <= int(choice) <= len(backups):
            sys.exit("Cancelled")
        name = backups[int(choice) - 1]["name"]
    if input(f"Replace the current database with {name}? Type yes: ").strip().lower() != "yes":
        sys.exit("Cancelled")
    safety = restore_backup(DB, name)
    print("Restored from " + name)
    print("The previous state was saved as " + safety)
