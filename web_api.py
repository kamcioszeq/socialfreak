"""
FastAPI backend for the newsautomation web panel.
Run in a thread from main.py; uses asyncio.run_coroutine_threadsafe to call bot logic.
"""
import asyncio
import logging
import os
import uuid
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List

import config

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("web_api")

# Shared state - same dicts as bot
from shared import (
    pending_adoption,
    pending_posts,
    ask_claude,
    ensure_cached_files,
    publish_to_channel,
    cleanup_cached_files,
    track_post,
)
from telegram_handlers import REPHRASE_INSTRUCTIONS
from x_handlers import X_INSTRUCTION, X_SYSTEM_PROMPT, X_GROK_INSTRUCTION, X_SOFT_INSTRUCTION
from facebook_handlers import FB_INSTRUCTION, FB_SYSTEM_PROMPT
from shared import SYSTEM_PROMPT, INITIAL_INSTRUCTION
import published_store
import scheduler
import rss_feeds
import templates
import scraper

app = FastAPI(title="Newsautomation Web API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    response = await call_next(request)
    log.info("%s %s %s", request.method, request.url.path, response.status_code)
    return response

# Set by main.py after startup
def set_bot_context(loop, bot, userbot):
    app.state.loop = loop
    app.state.bot = bot
    app.state.userbot = userbot
    log.info("Bot context set (web API ready)")


def _run(coro):
    loop = getattr(app.state, "loop", None)
    if not loop:
        log.error("Bot not connected (loop missing)")
        raise HTTPException(status_code=503, detail="Bot not connected")
    try:
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=90)
    except Exception as e:
        log.exception("Async call failed: %s", e)
        raise


def _serialize_post(key, post, in_progress=False):
    """Return JSON-serializable post (no Telethon messages)."""
    text = post.get("text") or ""
    platform = post.get("platform") or ""
    text_telegram = post.get("text_telegram") or (text if platform == "telegram" else "")
    text_x = post.get("text_x") or (text if platform == "x" else "")
    text_facebook = post.get("text_facebook") or (text if platform == "facebook" else "")
    def _status(txt):
        return "draft" if (txt or "").strip() else "empty"
    return {
        "id": str(key),
        "source": post.get("source", "?"),
        "original_text": post.get("original_text", ""),
        "text_telegram": text_telegram,
        "text_x": text_x,
        "text_facebook": text_facebook,
        "has_media": post.get("has_media", False),
        "media_count": len(post.get("cached_files") or []),
        "platform": platform,
        "created_at": post.get("created_at"),
        "in_progress": in_progress,
        "status_telegram": _status(text_telegram),
        "status_x": _status(text_x),
        "status_facebook": _status(text_facebook),
        "tags": post.get("tags") or [],
        "tone": post.get("tone") or "",
        "approval_status": post.get("approval_status") or "draft",
    }


@app.get("/api/posts")
def list_posts(tag: str = None):
    """List new posts (pending_adoption) and in-progress (pending_posts)."""
    log.info("GET /api/posts tag=%s", tag)
    new = [
        {"id": str(k), "source": v.get("source", "?"), "original_text": (v.get("original_text") or ""), "has_media": v.get("has_media", False), "created_at": v.get("created_at"), "tags": v.get("tags") or [], "tone": v.get("tone") or ""}
        for k, v in pending_adoption.items()
    ]
    in_progress = [
        _serialize_post(k, v, in_progress=True)
        for k, v in pending_posts.items()
    ]
    if tag:
        new = [p for p in new if tag in (p.get("tags") or [])]
        in_progress = [p for p in in_progress if tag in (p.get("tags") or [])]
    return {"new": new, "in_progress": in_progress}


def _get_post(post_id):
    """Resolve post from pending_adoption (int) or pending_posts (int or web_xxx)."""
    try:
        pid = int(post_id)
        if pid in pending_adoption:
            return pid, pending_adoption[pid], False
        if pid in pending_posts:
            return pid, pending_posts[pid], True
    except ValueError:
        pass
    if post_id in pending_posts:
        return post_id, pending_posts[post_id], True
    raise HTTPException(status_code=404, detail="Post not found")


@app.get("/api/posts/{post_id}")
def get_post(post_id: str):
    log.info("GET /api/posts/%s", post_id)
    key, post, in_progress = _get_post(post_id)
    return _serialize_post(key, post, in_progress=in_progress)


@app.get("/api/posts/{post_id}/media/{index:int}")
def get_media(post_id: str, index: int):
    log.info("GET /api/posts/%s/media/%s", post_id, index)
    key, post, _ = _get_post(post_id)
    bot = getattr(app.state, "bot", None)
    userbot = getattr(app.state, "userbot", None)
    if not bot or not userbot:
        raise HTTPException(status_code=503, detail="Bot not connected")

    async def _ensure_and_serve():
        download_client = bot if post.get("forwarded") else userbot
        files = await ensure_cached_files(download_client, post)
        if index < 0 or index >= len(files):
            return None
        path = files[index]
        if not os.path.exists(path):
            return None
        return path

    path = _run(_ensure_and_serve())
    if not path:
        raise HTTPException(status_code=404, detail="Media not found")
    return FileResponse(path, media_type="application/octet-stream", filename=os.path.basename(path))


class AdoptBody(BaseModel):
    platform: str  # telegram | x | facebook


@app.post("/api/posts/{post_id}/adopt")
def adopt_post(post_id: str, body: AdoptBody):
    log.info("POST /api/posts/%s/adopt platform=%s", post_id, body.platform)
    if body.platform not in ("telegram", "x", "facebook"):
        raise HTTPException(status_code=400, detail="Invalid platform")
    key, post, in_progress = _get_post(post_id)
    if in_progress:
        raise HTTPException(status_code=400, detail="Post already adopted; use generate for another platform")
    # key is int (Telegram msg_id), post is from pending_adoption
    original = post.get("original_text", "")
    source = post.get("source", "?")

    if body.platform == "telegram":
        instruction = INITIAL_INSTRUCTION
        system = SYSTEM_PROMPT
    elif body.platform == "x":
        instruction = X_INSTRUCTION
        system = X_SYSTEM_PROMPT
    else:
        instruction = FB_INSTRUCTION
        system = FB_SYSTEM_PROMPT

    async def _adopt():
        from shared import ask_claude_tags
        rewritten = await ask_claude(original, source, instruction, system_prompt=system)
        tags = await ask_claude_tags(original, source)
        bot = app.state.bot
        userbot = app.state.userbot
        download_client = bot if post.get("forwarded") else userbot
        await ensure_cached_files(download_client, post)
        web_id = "web_" + uuid.uuid4().hex[:8]
        field = {"telegram": "text_telegram", "x": "text_x", "facebook": "text_facebook"}[body.platform]
        new_post = {
            "original_text": original,
            "source": source,
            "messages": post.get("messages", []),
            "has_media": post.get("has_media", False),
            "cached_files": post.get("cached_files", []),
            "forwarded": post.get("forwarded", False),
            "platform": body.platform,
            "phase1_msg_id": key,
            "text_telegram": "",
            "text_x": "",
            "text_facebook": "",
            "tags": tags,
        }
        new_post["text"] = rewritten
        new_post[field] = rewritten
        pending_posts[web_id] = track_post(pending_posts, new_post, sent_id=web_id)
        del pending_adoption[key]
        return web_id

    web_id = _run(_adopt())
    return {"id": web_id}


class GenerateBody(BaseModel):
    platform: str


@app.post("/api/posts/{post_id}/generate")
def generate_for_platform(post_id: str, body: GenerateBody):
    log.info("POST /api/posts/%s/generate platform=%s", post_id, body.platform)
    if body.platform not in ("telegram", "x", "facebook"):
        raise HTTPException(status_code=400, detail="Invalid platform")
    key, post, in_progress = _get_post(post_id)
    if not in_progress:
        raise HTTPException(status_code=400, detail="Use adopt first")
    original = post.get("original_text", "")
    source = post.get("source", "?")

    if body.platform == "telegram":
        instruction = INITIAL_INSTRUCTION
        system = SYSTEM_PROMPT
    elif body.platform == "x":
        instruction = X_INSTRUCTION
        system = X_SYSTEM_PROMPT
    else:
        instruction = FB_INSTRUCTION
        system = FB_SYSTEM_PROMPT

    async def _gen():
        rewritten = await ask_claude(original, source, instruction, system_prompt=system)
        field = {"telegram": "text_telegram", "x": "text_x", "facebook": "text_facebook"}[body.platform]
        post[field] = rewritten
        return rewritten

    text = _run(_gen())
    return {"text": text}


class TextBody(BaseModel):
    platform: str
    text: str


@app.put("/api/posts/{post_id}/text")
def update_text(post_id: str, body: TextBody):
    log.info("PUT /api/posts/%s/text platform=%s", post_id, body.platform)
    if body.platform not in ("telegram", "x", "facebook"):
        raise HTTPException(status_code=400, detail="Invalid platform")
    key, post, in_progress = _get_post(post_id)
    if not in_progress:
        raise HTTPException(status_code=400, detail="Post not adopted yet")
    field = {"telegram": "text_telegram", "x": "text_x", "facebook": "text_facebook"}[body.platform]
    post[field] = body.text
    post["text"] = body.text
    post["platform"] = body.platform
    return {"ok": True}


class RephraseBody(BaseModel):
    style: str  # longer, shorter, retry, soft, grok, etc.


@app.post("/api/posts/{post_id}/rephrase")
def rephrase_post(post_id: str, body: RephraseBody):
    log.info("POST /api/posts/%s/rephrase style=%s", post_id, body.style)
    if body.style not in REPHRASE_INSTRUCTIONS:
        raise HTTPException(status_code=400, detail="Unknown style")
    key, post, in_progress = _get_post(post_id)
    if not in_progress:
        raise HTTPException(status_code=400, detail="Post not adopted yet")
    current = post.get("text") or post.get("text_telegram") or post.get("text_x") or post.get("text_facebook") or ""
    instruction = REPHRASE_INSTRUCTIONS[body.style] + current
    source = post.get("source", "?")

    async def _rephrase():
        from shared import SYSTEM_PROMPT
        rewritten = await ask_claude(current, source, instruction, system_prompt=SYSTEM_PROMPT)
        platform = post.get("platform") or "telegram"
        field = {"telegram": "text_telegram", "x": "text_x", "facebook": "text_facebook"}.get(platform, "text_telegram")
        post[field] = rewritten
        post["text"] = rewritten
        return rewritten

    text = _run(_rephrase())
    return {"text": text}


@app.post("/api/posts/{post_id}/publish/telegram")
def publish_telegram(post_id: str):
    log.info("POST /api/posts/%s/publish/telegram", post_id)
    key, post, _ = _get_post(post_id)
    text = post.get("text_telegram") or post.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="No Telegram text")

    async def _pub():
        bot = app.state.bot
        userbot = app.state.userbot
        await publish_to_channel(userbot, bot, post, text)
        if str(key).startswith("web_"):
            post["platform"] = "telegram"
        return True

    _run(_pub())
    return {"ok": True}


@app.post("/api/posts/{post_id}/publish/facebook")
def publish_facebook(post_id: str):
    log.info("POST /api/posts/%s/publish/facebook", post_id)
    key, post, _ = _get_post(post_id)
    text = post.get("text_facebook") or post.get("text", "")

    async def _pub():
        bot = app.state.bot
        userbot = app.state.userbot
        await ensure_cached_files(bot if post.get("forwarded") else userbot, post)
        from facebook_handlers import publish_to_facebook
        ok, result = await publish_to_facebook(post, text)
        if not ok:
            raise RuntimeError(str(result))
        return ok

    _run(_pub())
    return {"ok": True}


@app.post("/api/posts/{post_id}/publish/x")
def publish_x(post_id: str):
    # Bot has no real X publish yet
    return {"ok": True, "message": "Ready for X (API not implemented)"}


@app.post("/api/posts/{post_id}/reject")
def reject_post(post_id: str):
    log.info("POST /api/posts/%s/reject", post_id)
    key, post, in_progress = _get_post(post_id)
    if in_progress and key in pending_posts:
        cleanup_cached_files(pending_posts[key])
        del pending_posts[key]
    try:
        pid = int(post_id)
        if pid in pending_adoption:
            cleanup_cached_files(pending_adoption[pid])
            del pending_adoption[pid]
    except ValueError:
        pass
    return {"ok": True}


# ── Published history & analytics ──────────────────────────

@app.get("/api/published")
def get_published(limit: int = 50, offset: int = 0, platform: str = None, q: str = None):
    items, total = published_store.list_published(limit=limit, offset=offset, platform=platform, q=q)
    return {"items": items, "total": total}


@app.get("/api/analytics/summary")
def analytics_summary():
    return published_store.get_stats()


# ── Bulk actions ──────────────────────────────────────────

class BulkAdoptBody(BaseModel):
    ids: list
    platform: str


@app.post("/api/posts/bulk-adopt")
def bulk_adopt(body: BulkAdoptBody):
    log.info("POST /api/posts/bulk-adopt ids=%s platform=%s", body.ids, body.platform)
    if body.platform not in ("telegram", "x", "facebook"):
        raise HTTPException(status_code=400, detail="Invalid platform")

    adopted = []
    errors = []

    for post_id in body.ids:
        try:
            key, post, in_progress = _get_post(str(post_id))
            if in_progress:
                errors.append({"id": str(post_id), "error": "Already adopted"})
                continue

            original = post.get("original_text", "")
            source = post.get("source", "?")

            if body.platform == "telegram":
                instruction = INITIAL_INSTRUCTION
                system = SYSTEM_PROMPT
            elif body.platform == "x":
                instruction = X_INSTRUCTION
                system = X_SYSTEM_PROMPT
            else:
                instruction = FB_INSTRUCTION
                system = FB_SYSTEM_PROMPT

            async def _adopt_one(k, p, orig, src, instr, sys_prompt):
                from shared import ask_claude_tags
                rewritten = await ask_claude(orig, src, instr, system_prompt=sys_prompt)
                tags = await ask_claude_tags(orig, src)
                bot = app.state.bot
                userbot = app.state.userbot
                download_client = bot if p.get("forwarded") else userbot
                await ensure_cached_files(download_client, p)
                web_id = "web_" + uuid.uuid4().hex[:8]
                field = {"telegram": "text_telegram", "x": "text_x", "facebook": "text_facebook"}[body.platform]
                new_post = {
                    "original_text": orig,
                    "source": src,
                    "messages": p.get("messages", []),
                    "has_media": p.get("has_media", False),
                    "cached_files": p.get("cached_files", []),
                    "forwarded": p.get("forwarded", False),
                    "platform": body.platform,
                    "phase1_msg_id": k,
                    "text_telegram": "",
                    "text_x": "",
                    "text_facebook": "",
                    "tags": tags,
                }
                new_post["text"] = rewritten
                new_post[field] = rewritten
                pending_posts[web_id] = track_post(pending_posts, new_post, sent_id=web_id)
                del pending_adoption[k]
                return web_id

            web_id = _run(_adopt_one(key, post, original, source, instruction, system))
            adopted.append(web_id)
        except Exception as e:
            errors.append({"id": str(post_id), "error": str(e)})

    return {"adopted": adopted, "errors": errors}


class BulkRejectBody(BaseModel):
    ids: list


@app.post("/api/posts/bulk-reject")
def bulk_reject(body: BulkRejectBody):
    log.info("POST /api/posts/bulk-reject ids=%s", body.ids)
    rejected = 0
    for post_id in body.ids:
        try:
            pid_str = str(post_id)
            # Try pending_posts first
            if pid_str in pending_posts:
                cleanup_cached_files(pending_posts[pid_str])
                del pending_posts[pid_str]
                rejected += 1
                continue
            try:
                pid = int(post_id)
                if pid in pending_adoption:
                    cleanup_cached_files(pending_adoption[pid])
                    del pending_adoption[pid]
                    rejected += 1
                elif pid in pending_posts:
                    cleanup_cached_files(pending_posts[pid])
                    del pending_posts[pid]
                    rejected += 1
            except ValueError:
                pass
        except Exception:
            pass
    return {"rejected": rejected}


# ── Scheduling ────────────────────────────────────────────

class ScheduleBody(BaseModel):
    platform: str
    publish_at: str  # ISO8601


@app.post("/api/posts/{post_id}/schedule")
def schedule_post(post_id: str, body: ScheduleBody):
    log.info("POST /api/posts/%s/schedule platform=%s at=%s", post_id, body.platform, body.publish_at)
    if body.platform not in ("telegram", "facebook", "x"):
        raise HTTPException(status_code=400, detail="Invalid platform")
    key, post, _ = _get_post(post_id)
    import time
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    if body.publish_at <= now:
        raise HTTPException(status_code=400, detail="publish_at must be in the future")
    record = scheduler.add_scheduled(str(key), body.platform, body.publish_at)
    return {"ok": True, "scheduled": record}


@app.get("/api/scheduled")
def get_scheduled():
    items = scheduler.list_scheduled()
    return {"items": items}


@app.delete("/api/scheduled/{sched_id}")
def delete_scheduled(sched_id: str):
    log.info("DELETE /api/scheduled/%s", sched_id)
    scheduler.remove_scheduled(sched_id)
    return {"ok": True}


# ── Tone detection ────────────────────────────────────────

@app.post("/api/posts/{post_id}/detect-tone")
def detect_tone(post_id: str):
    log.info("POST /api/posts/%s/detect-tone", post_id)
    key, post, _ = _get_post(post_id)
    text = post.get("original_text") or post.get("text") or ""

    async def _detect():
        from shared import ask_claude_tone
        tone = await ask_claude_tone(text)
        post["tone"] = tone
        return tone

    tone = _run(_detect())
    return {"tone": tone}


# ── Approval workflow ─────────────────────────────────────

class StatusBody(BaseModel):
    status: str  # draft | ready_for_review | approved


@app.put("/api/posts/{post_id}/status")
def update_status(post_id: str, body: StatusBody):
    log.info("PUT /api/posts/%s/status → %s", post_id, body.status)
    if body.status not in ("draft", "ready_for_review", "approved"):
        raise HTTPException(status_code=400, detail="Invalid status")
    key, post, in_progress = _get_post(post_id)
    if not in_progress:
        raise HTTPException(status_code=400, detail="Post not adopted yet")
    post["approval_status"] = body.status
    return {"ok": True, "approval_status": body.status}


# ── Recycle published post ────────────────────────────────

@app.post("/api/published/{pub_id}/recycle")
def recycle_published(pub_id: str):
    log.info("POST /api/published/%s/recycle", pub_id)
    items, _ = published_store.list_published(limit=9999)
    record = None
    for r in items:
        if r.get("id") == pub_id:
            record = r
            break
    if not record:
        raise HTTPException(status_code=404, detail="Published record not found")

    web_id = "web_" + uuid.uuid4().hex[:8]
    new_post = {
        "original_text": record.get("original_text", ""),
        "source": record.get("source", "?"),
        "messages": [],
        "has_media": False,
        "cached_files": [],
        "forwarded": False,
        "platform": record.get("platform", "telegram"),
        "text_telegram": record.get("text", "") if record.get("platform") == "telegram" else "",
        "text_x": record.get("text", "") if record.get("platform") == "x" else "",
        "text_facebook": record.get("text", "") if record.get("platform") == "facebook" else "",
        "text": record.get("text", ""),
        "tags": record.get("tags", []),
        "approval_status": "draft",
    }
    pending_posts[web_id] = track_post(pending_posts, new_post, sent_id=web_id)
    return {"id": web_id}


# ── Best Time to Post ─────────────────────────────────────

@app.get("/api/analytics/best-times")
def analytics_best_times():
    return published_store.get_publish_time_distribution()


# ── RSS feeds ─────────────────────────────────────────────

@app.get("/api/rss")
def get_rss_feeds():
    return {"feeds": rss_feeds.list_feeds()}


class RssFeedBody(BaseModel):
    url: str
    name: str = ""


@app.post("/api/rss")
def add_rss_feed(body: RssFeedBody):
    record = rss_feeds.add_feed(body.url, body.name or None)
    if not record:
        raise HTTPException(status_code=409, detail="Feed already exists")
    return record


@app.delete("/api/rss/{feed_id}")
def delete_rss_feed(feed_id: str):
    rss_feeds.remove_feed(feed_id)
    return {"ok": True}


class RssToggleBody(BaseModel):
    active: bool


@app.put("/api/rss/{feed_id}/toggle")
def toggle_rss_feed(feed_id: str, body: RssToggleBody):
    rss_feeds.toggle_feed(feed_id, body.active)
    return {"ok": True}


# ── Templates ─────────────────────────────────────────────

@app.get("/api/templates")
def get_templates():
    return {"templates": templates.list_templates()}


class TemplateBody(BaseModel):
    name: str
    body: str
    platform: str = ""


@app.post("/api/templates")
def create_template(body: TemplateBody):
    record = templates.create_template(body.name, body.body, body.platform)
    return record


@app.put("/api/templates/{tpl_id}")
def update_template(tpl_id: str, body: TemplateBody):
    record = templates.update_template(tpl_id, body.name, body.body, body.platform)
    if not record:
        raise HTTPException(status_code=404, detail="Template not found")
    return record


@app.delete("/api/templates/{tpl_id}")
def delete_template(tpl_id: str):
    templates.delete_template(tpl_id)
    return {"ok": True}


# ── Calendar data ─────────────────────────────────────────

@app.get("/api/calendar")
def get_calendar(month: str = None):
    """Return published + scheduled posts grouped by day for a given month (YYYY-MM)."""
    import time as _time
    if not month:
        month = _time.strftime("%Y-%m")

    from_date = month + "-01T00:00:00"
    # End of month approximation
    to_date = month + "-31T23:59:59"

    items, _ = published_store.list_published(limit=9999, from_date=from_date, to_date=to_date)
    sched = scheduler.list_scheduled()

    days = {}
    for r in items:
        day = (r.get("published_at") or "")[:10]
        if day.startswith(month):
            days.setdefault(day, []).append({
                "type": "published",
                "platform": r.get("platform", ""),
                "text": (r.get("text") or "")[:80],
                "time": (r.get("published_at") or "")[11:16],
            })
    for r in sched:
        day = (r.get("publish_at") or "")[:10]
        if day.startswith(month):
            days.setdefault(day, []).append({
                "type": "scheduled",
                "platform": r.get("platform", ""),
                "post_id": r.get("post_id", ""),
                "time": (r.get("publish_at") or "")[11:16],
            })

    return {"month": month, "days": days}


# ── Creator: URL scraping & media upload ──────────────────

class ScrapeUrlBody(BaseModel):
    url: str


@app.post("/api/creator/scrape-url")
def creator_scrape_url(body: ScrapeUrlBody):
    """Read URL with Claude, extract text + media URLs."""
    log.info("POST /api/creator/scrape-url url=%s", body.url)

    async def _scrape():
        return await scraper.read_url_with_claude(body.url)

    result = _run(_scrape())
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@app.post("/api/creator/download-media")
def creator_download_media(body: dict):
    """Download media URLs to local cache. body: {urls: [...]}"""
    urls = body.get("urls", [])
    log.info("POST /api/creator/download-media count=%d", len(urls))

    async def _dl():
        results = []
        for url in urls[:20]:  # limit to 20
            path = await scraper.download_media_url(url)
            if path:
                results.append({"url": url, "path": path, "filename": os.path.basename(path)})
        return results

    downloaded = _run(_dl())
    return {"media": downloaded}


@app.post("/api/creator/upload")
async def creator_upload(file: UploadFile = File(...)):
    """Upload a file (screenshot/photo/video) for analysis."""
    log.info("POST /api/creator/upload filename=%s", file.filename)
    contents = await file.read()
    if len(contents) > 50 * 1024 * 1024:  # 50MB limit
        raise HTTPException(status_code=413, detail="File too large")
    path = scraper.save_uploaded_file(contents, file.filename or "upload.bin")
    return {"path": path, "filename": os.path.basename(path)}


class AnalyzeMediaBody(BaseModel):
    path: str
    context: str = ""


@app.post("/api/creator/analyze-media")
def creator_analyze_media(body: AnalyzeMediaBody):
    """Use Claude vision to analyze uploaded/downloaded media."""
    log.info("POST /api/creator/analyze-media path=%s", body.path)
    if not os.path.exists(body.path):
        raise HTTPException(status_code=404, detail="File not found")

    async def _analyze():
        return await scraper.analyze_uploaded_media(body.path, context=body.context)

    result = _run(_analyze())
    return result


class CreatorGenerateBody(BaseModel):
    text: str
    source: str = "creator"
    platforms: List[str]  # ["telegram", "x", "facebook"]
    media_paths: List[str] = []


@app.post("/api/creator/generate")
def creator_generate(body: CreatorGenerateBody):
    """Generate post texts for selected platforms from scraped/uploaded content, create pending_post."""
    log.info("POST /api/creator/generate platforms=%s", body.platforms)
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="No text provided")

    valid_platforms = [p for p in body.platforms if p in ("telegram", "x", "facebook")]
    if not valid_platforms:
        raise HTTPException(status_code=400, detail="No valid platforms")

    async def _gen():
        from shared import ask_claude_tags
        results = {}
        for platform in valid_platforms:
            if platform == "telegram":
                instruction = INITIAL_INSTRUCTION
                system = SYSTEM_PROMPT
            elif platform == "x":
                from x_handlers import X_INSTRUCTION, X_SYSTEM_PROMPT as XSP
                instruction = X_INSTRUCTION
                system = XSP
            else:
                from facebook_handlers import FB_INSTRUCTION, FB_SYSTEM_PROMPT as FBSP
                instruction = FB_INSTRUCTION
                system = FBSP
            rewritten = await ask_claude(body.text, body.source, instruction, system_prompt=system)
            results[platform] = rewritten

        tags = await ask_claude_tags(body.text, body.source)

        # Verify media paths exist
        cached_files = [p for p in body.media_paths if os.path.exists(p)]

        web_id = "web_" + uuid.uuid4().hex[:8]
        new_post = {
            "original_text": body.text,
            "source": body.source,
            "messages": [],
            "has_media": len(cached_files) > 0,
            "cached_files": cached_files,
            "forwarded": False,
            "platform": valid_platforms[0],
            "phase1_msg_id": None,
            "text_telegram": results.get("telegram", ""),
            "text_x": results.get("x", ""),
            "text_facebook": results.get("facebook", ""),
            "text": results.get(valid_platforms[0], ""),
            "tags": tags,
            "approval_status": "draft",
        }
        pending_posts[web_id] = track_post(pending_posts, new_post, sent_id=web_id)
        return {"id": web_id, "texts": results, "tags": tags}

    return _run(_gen())


@app.get("/api/creator/media/{filename}")
def creator_serve_media(filename: str):
    """Serve a cached creator media file."""
    path = os.path.join(scraper.CREATOR_MEDIA_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, media_type="application/octet-stream", filename=filename)


# Frontend is served by separate container (nginx on port 5173). API only serves /api/*
