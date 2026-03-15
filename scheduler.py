"""
Scheduler: queue posts for future publication.
Storage in data/scheduled.json, worker loop checks every 60s.
"""
import asyncio
import json
import os
import time
import uuid

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SCHEDULED_JSON = os.path.join(DATA_DIR, "scheduled.json")

os.makedirs(DATA_DIR, exist_ok=True)


def _load():
    try:
        with open(SCHEDULED_JSON, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(records):
    with open(SCHEDULED_JSON, "w") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def add_scheduled(post_id, platform, publish_at):
    """Add a post to the schedule queue. publish_at is ISO8601 string."""
    record = {
        "id": "sched_" + uuid.uuid4().hex[:8],
        "post_id": str(post_id),
        "platform": platform,
        "publish_at": publish_at,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    records = _load()
    records.append(record)
    _save(records)
    return record


def get_due():
    """Return scheduled items whose publish_at <= now."""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    records = _load()
    return [r for r in records if r.get("publish_at", "") <= now]


def remove_scheduled(sched_id):
    """Remove a scheduled item by id."""
    records = _load()
    records = [r for r in records if r.get("id") != sched_id]
    _save(records)


def list_scheduled(limit=100):
    """List all scheduled items, sorted by publish_at."""
    records = _load()
    records.sort(key=lambda r: r.get("publish_at", ""))
    return records[:limit]


async def run_scheduler_loop(bot, userbot, interval=60):
    """Background loop: check for due posts and publish them."""
    from shared import pending_posts, publish_to_channel
    from facebook_handlers import publish_to_facebook

    print("[SCHEDULER] Uruchomiono scheduler loop")
    while True:
        try:
            due = get_due()
            for item in due:
                post_id = item["post_id"]
                platform = item["platform"]
                post = pending_posts.get(post_id)
                if not post:
                    print(f"[SCHEDULER] Post {post_id} nie istnieje, pomijam")
                    remove_scheduled(item["id"])
                    continue

                text = post.get(f"text_{platform}") or post.get("text", "")
                if not text:
                    print(f"[SCHEDULER] Brak tekstu dla {post_id}/{platform}, pomijam")
                    remove_scheduled(item["id"])
                    continue

                try:
                    if platform == "telegram":
                        await publish_to_channel(userbot, bot, post, text)
                    elif platform == "facebook":
                        ok, result = await publish_to_facebook(post, text)
                        if not ok:
                            print(f"[SCHEDULER] Błąd FB: {result}")
                    print(f"[SCHEDULER] Opublikowano {post_id} na {platform}")
                except Exception as e:
                    print(f"[SCHEDULER] Błąd publikacji: {e}")

                remove_scheduled(item["id"])
        except Exception as e:
            print(f"[SCHEDULER] Błąd pętli: {e}")

        await asyncio.sleep(interval)
