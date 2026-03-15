"""
Persistent storage for published posts history.
Stores records in data/published.json.
"""
import json
import os
import time
import uuid

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PUBLISHED_JSON = os.path.join(DATA_DIR, "published.json")

os.makedirs(DATA_DIR, exist_ok=True)


def _load():
    try:
        with open(PUBLISHED_JSON, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(records):
    with open(PUBLISHED_JSON, "w") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def append_published(record):
    """Append a published record. Auto-adds id and published_at if missing."""
    record.setdefault("id", "pub_" + uuid.uuid4().hex[:8])
    record.setdefault("published_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    records = _load()
    records.append(record)
    _save(records)
    return record


def list_published(limit=50, offset=0, platform=None, q=None, from_date=None, to_date=None):
    """List published records with optional filters. Returns (items, total)."""
    records = _load()
    # newest first
    records.reverse()

    if platform:
        records = [r for r in records if r.get("platform") == platform]
    if q:
        ql = q.lower()
        records = [r for r in records if ql in (r.get("text") or "").lower() or ql in (r.get("original_text") or "").lower()]
    if from_date:
        records = [r for r in records if (r.get("published_at") or "") >= from_date]
    if to_date:
        records = [r for r in records if (r.get("published_at") or "") <= to_date]

    total = len(records)
    items = records[offset:offset + limit]
    return items, total


def get_stats():
    """Basic stats: count per platform, last 7 days breakdown."""
    records = _load()
    by_platform = {}
    for r in records:
        p = r.get("platform", "unknown")
        by_platform[p] = by_platform.get(p, 0) + 1

    # last 7 days
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 7 * 86400))
    last_7 = [r for r in records if (r.get("published_at") or "") >= cutoff]
    by_day = {}
    for r in last_7:
        day = (r.get("published_at") or "")[:10]
        by_day[day] = by_day.get(day, 0) + 1

    return {"by_platform": by_platform, "last_7_days": by_day, "total": len(records)}


def get_publish_time_distribution():
    """Analyse publishing hours from history. Returns hour→count map and suggested best hours."""
    records = _load()
    hour_counts = {}
    for r in records:
        pa = r.get("published_at", "")
        if len(pa) >= 13:
            try:
                h = int(pa[11:13])
                hour_counts[h] = hour_counts.get(h, 0) + 1
            except ValueError:
                pass

    if not hour_counts:
        return {"hours": {}, "best_hours": [], "total_analysed": 0}

    sorted_hours = sorted(hour_counts.items(), key=lambda x: -x[1])
    best = [h for h, _ in sorted_hours[:3]]
    return {"hours": hour_counts, "best_hours": best, "total_analysed": len(records)}
