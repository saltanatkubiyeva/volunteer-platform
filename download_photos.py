import os
import sys
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from demeu.photos import ALL_IDS

folder = os.path.join(BASE, "demeu", "static", "img", "photos")
os.makedirs(folder, exist_ok=True)
ok = 0
for pid in ALL_IDS:
    path = os.path.join(folder, f"{pid}.jpg")
    if os.path.exists(path):
        ok += 1
        continue
    url = f"https://images.unsplash.com/photo-{pid}?auto=format&fit=crop&w=1400&q=72&fm=jpg"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DEMEU student project"})
        with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
            f.write(r.read())
        ok += 1
        print("saved", pid)
    except Exception as e:
        print("failed", pid, e)
print(f"{ok}/{len(ALL_IDS)} photos available offline")
