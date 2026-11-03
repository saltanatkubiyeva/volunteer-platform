"""Start DEMEU locally:  python run.py   ->  http://127.0.0.1:5000
The database with demo data is created automatically on the first start."""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
if not os.path.exists(os.path.join(BASE, "instance", "demeu.db")):
    subprocess.check_call([sys.executable, os.path.join(BASE, "seed.py")])

from demeu import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  DEMEU is running:  http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False)
