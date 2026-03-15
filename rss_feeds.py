"""
RSS feed management: store feed URLs, poll for new entries, inject into pending_adoption.
Storage in data/rss_feeds.json.
"""
import asyncio
import json
import os
import time
import uuid
import hashlib

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FEEDS_JSON = os.path.join(DATA_DIR, "rss_feeds.json")
SEEN_JSON = os.path.join(DATA_DIR, "rss_seen.json")

os.makedirs(DATA_DIR, exist_ok=True)


def _load_feeds():
    try:
        with open(FEEDS_JSON, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_feeds(feeds):
    with open(FEEDS_JSON, "w") as f:
        json.dump(feeds, f, indent=2, ensure_ascii=False)


def _load_seen():
    try:
        with open(SEEN_JSON, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_seen(seen):
    with open(SEEN_JSON, "w") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)


def add_feed(url, name=None):
    """Add an RSS feed URL. Returns the feed record."""
    feeds = _load_feeds()
    for f in feeds:
        if f["url"] == url:
            return None  # already exists
    record = {
        "id": "rss_" + uuid.uuid4().hex[:8],
        "url": url,
        "name": name or url,
        "active": True,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    feeds.append(record)
    _save_feeds(feeds)
    return record


def remove_feed(feed_id):
    feeds = _load_feeds()
    feeds = [f for f in feeds if f.get("id") != feed_id]
    _save_feeds(feeds)


def list_feeds():
    return _load_feeds()


def toggle_feed(feed_id, active):
    feeds = _load_feeds()
    for f in feeds:
        if f.get("id") == feed_id:
            f["active"] = active
            break
    _save_feeds(feeds)


def _entry_hash(entry):
    """Create a unique hash for an RSS entry."""
    link = getattr(entry, "link", "") or ""
    title = getattr(entry, "title", "") or ""
    return hashlib.md5((link + title).encode()).hexdigest()


def poll_feed(feed):
    """Poll a single feed, return new entries (list of dicts with title, link, summary, source)."""
    try:
        import feedparser
    except ImportError:
        print("[RSS] feedparser not installed, skipping")
        return []

    url = feed["url"]
    name = feed.get("name", url)
    seen = _load_seen()
    feed_seen = set(seen.get(url, []))

    parsed = feedparser.parse(url)
    new_entries = []

    for entry in parsed.entries[:20]:
        h = _entry_hash(entry)
        if h in feed_seen:
            continue
        feed_seen.add(h)

        title = getattr(entry, "title", "") or ""
        link = getattr(entry, "link", "") or ""
        summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        # Strip HTML tags from summary (basic)
        import re
        summary = re.sub(r"<[^>]+>", "", summary).strip()

        text = f"{title}\n\n{summary}".strip()
        if link:
            text += f"\n\n{link}"

        new_entries.append({
            "text": text,
            "title": title,
            "link": link,
            "source": f"RSS: {name}",
        })

    seen[url] = list(feed_seen)
    _save_seen(seen)
    return new_entries


async def run_rss_poll_loop(interval=300):
    """Background loop: check RSS feeds and inject new entries into pending_adoption."""
    from shared import pending_adoption, track_post

    print(f"[RSS] Uruchomiono RSS poll loop (co {interval}s)")
    while True:
        try:
            feeds = _load_feeds()
            active = [f for f in feeds if f.get("active", True)]
            for feed in active:
                entries = poll_feed(feed)
                for entry in entries:
                    rss_id = int(time.time() * 1000) % (2**31)
                    post = {
                        "original_text": entry["text"],
                        "source": entry["source"],
                        "messages": [],
                        "has_media": False,
                        "cached_files": [],
                        "rss_link": entry.get("link", ""),
                    }
                    pending_adoption[rss_id] = track_post(pending_adoption, post, sent_id=rss_id)
                    print(f"[RSS] Nowy wpis z {entry['source']}: {entry['title'][:60]}")
        except Exception as e:
            print(f"[RSS] Błąd pętli: {e}")

        await asyncio.sleep(interval)
