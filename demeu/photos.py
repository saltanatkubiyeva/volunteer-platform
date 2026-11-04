"""Real photographs for event covers and page imagery (Unsplash License: free to use,
no attribution required; we still credit Unsplash in the footer).

Photos are shown from the Unsplash CDN. Run `python download_photos.py` once with
internet to save them into static/img/photos/ — then the site shows them offline too.
If a photo cannot be loaded, the page falls back to the local illustration of the direction.
"""
import os

from flask import current_app, url_for

# direction slug -> Unsplash photo ids (candid, natural light)
PHOTOS = {
    "ecology": ["1758599668186-c47df67d025d", "1758599668429-121d54188b9c", "1758599668508-d8ec9eca1be3",
                "1758599668426-1cf242bb7667", "1598335624134-5bceb5de202d", "1710361006404-a13d01802ce9"],
    "animals": ["1542715234-bd0adb4249b7", "1675701917791-debd2d61cc4a", "1761943840993-1c38354e8603",
                "1604606363386-dd3f2357ad87"],
    "children": ["1780751987564-79489283d67b", "1771765812031-22653b4c70a6", "1758598737901-6d892a0cf533",
                 "1776243773206-a29b683c97fb"],
    "seniors": ["1773227059334-38d10a9075f2", "1762955911431-4c44c7c3f408", "1773227059780-5e865ce7fb13",
                "1758612897741-9fcb791f83ff"],
    "education": ["1583468982228-19f19164aee2", "1758687126375-e2c1683219e9", "1509062522246-3755977927d7"],
    "social": ["1599059813005-11265ba4b4ce", "1593113616828-6f22bca04804", "1593113598332-cd288d649433",
               "1783028104792-8506735c0383"],
    "culture": ["1544928147-79a2dbc1f389", "1782567531523-0144dc7352fc", "1760992003928-e2ed759fa846"],
    "health": ["1536856136534-bb679c52a9aa", "1615461066159-fea0960485d5", "1615461065624-21b562ee5566"],
    "sport": ["1745790289741-12a211a8325d", "1613936360976-8f35cf0e5461", "1682367905664-e36b30f15b19"],
    "emergency": ["1541710005980-7ea80ff232d6", "1600336153113-d66c79de3e91", "1604275689235-fdc521556c16"],
    "digital": ["1785780224428-1e71ec3a1199", "1765896387377-e293914d1e69", "1579389083046-e3df9c2b3325"],
}
HERO = "1758599668186-c47df67d025d"      # volunteers cleaning a park together
CITY = "1659651117607-d2b397cf100f"      # Almaty with the mountains

ALL_IDS = sorted({p for ids in PHOTOS.values() for p in ids} | {HERO, CITY})


def _local(photo_id):
    return os.path.exists(os.path.join(current_app.static_folder, "img", "photos", f"{photo_id}.jpg"))


def photo_url(photo_id, width=1000):
    if _local(photo_id):
        return url_for("static", filename=f"img/photos/{photo_id}.jpg")
    return (f"https://images.unsplash.com/photo-{photo_id}?auto=format&fit=crop&w={width}&q=70")


def direction_photo(slug, seed=0, width=1000):
    ids = PHOTOS.get(slug) or PHOTOS["ecology"]
    return photo_url(ids[(seed or 0) % len(ids)], width)


def fallback_url(slug):
    return url_for("static", filename=f"img/covers/{slug or 'ecology'}.svg")
