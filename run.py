import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
if not os.path.exists(os.path.join(BASE, "instance", "demeu.db")):
    subprocess.check_call([sys.executable, os.path.join(BASE, "seed.py")])

from demeu import create_app
from demeu.backups import daily_backup

app = create_app()
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
daily_backup(app.config["DATABASE"])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    if os.environ.get("WERKZEUG_RUN_MAIN"):
        print(f"\n  DEMEU is running:  http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=True)
