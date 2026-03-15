"""
Creator/Scraper: read URLs via Claude, handle uploaded media, generate posts.
Uses Claude to read webpage content directly (no internal scraping).
Caches uploaded/downloaded media in data/creator_media/.
"""
import base64
import hashlib
import os
import re
import uuid

import httpx

import config

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CREATOR_MEDIA_DIR = os.path.join(DATA_DIR, "creator_media")
os.makedirs(CREATOR_MEDIA_DIR, exist_ok=True)


async def read_url_with_claude(url: str) -> dict:
    """Ask Claude to read a URL and extract article text + list media URLs found."""
    prompt = (
        f"Odwiedź i przeczytaj tę stronę: {url}\n\n"
        "Zadanie:\n"
        "1) Wyodrębnij PEŁNY tekst artykułu/posta (bez menu, reklam, nagłówków strony).\n"
        "2) Wylistuj wszystkie istotne URL-e do obrazów/wideo znalezionych w treści (nie ikony, nie logo).\n"
        "3) Oceń jakość kontekstu od 1-10 (1=mało info, 10=pełny artykuł).\n\n"
        "Odpowiedz w formacie:\n"
        "TEKST:\n<pełny tekst artykułu>\n\n"
        "MEDIA:\n<url1>\n<url2>\n...\n\n"
        "KONTEKST_OCENA: <liczba 1-10>\n"
        "TYTUL: <tytuł artykułu>"
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": config.CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )

    data = response.json()
    if not data.get("content"):
        error_msg = data.get("error", {}).get("message", "unknown")
        return {"error": error_msg}

    raw = "\n".join(b["text"] for b in data["content"] if b["type"] == "text")

    # Parse structured response
    text = ""
    media_urls = []
    context_score = 5
    title = ""

    text_match = re.search(r"TEKST:\s*\n(.*?)(?=\nMEDIA:|\nKONTEKST_OCENA:|\Z)", raw, re.DOTALL)
    if text_match:
        text = text_match.group(1).strip()

    media_match = re.search(r"MEDIA:\s*\n(.*?)(?=\nKONTEKST_OCENA:|\nTYTUL:|\Z)", raw, re.DOTALL)
    if media_match:
        for line in media_match.group(1).strip().splitlines():
            line = line.strip().lstrip("- ")
            if line.startswith("http"):
                media_urls.append(line)

    score_match = re.search(r"KONTEKST_OCENA:\s*(\d+)", raw)
    if score_match:
        context_score = int(score_match.group(1))

    title_match = re.search(r"TYTUL:\s*(.*)", raw)
    if title_match:
        title = title_match.group(1).strip()

    return {
        "text": text,
        "title": title,
        "media_urls": media_urls,
        "context_score": context_score,
        "url": url,
    }


async def download_media_url(url: str) -> str | None:
    """Download a media URL to creator_media, return local path."""
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(url, timeout=30)
            if resp.status_code != 200:
                return None
            ct = resp.headers.get("content-type", "")
            if "image" in ct:
                ext = ".jpg"
                if "png" in ct:
                    ext = ".png"
                elif "webp" in ct:
                    ext = ".webp"
                elif "gif" in ct:
                    ext = ".gif"
            elif "video" in ct:
                ext = ".mp4"
            else:
                ext = ".bin"
            name = hashlib.md5(url.encode()).hexdigest()[:12] + ext
            path = os.path.join(CREATOR_MEDIA_DIR, name)
            if not os.path.exists(path):
                with open(path, "wb") as f:
                    f.write(resp.content)
            return path
    except Exception as e:
        print(f"[SCRAPER] Download failed {url}: {e}")
        return None


async def analyze_uploaded_media(file_path: str, context: str = "") -> dict:
    """Use Claude vision to analyze uploaded media. Returns text + context_score."""
    from shared import ask_claude_vision
    description = await ask_claude_vision(file_path, context=context)

    # Try to extract a context score from the description
    score = 5
    # If description is short or vague, lower the score
    word_count = len(description.split())
    if word_count < 20:
        score = 2
    elif word_count < 50:
        score = 4
    elif word_count > 150:
        score = 8

    return {
        "description": description,
        "context_score": score,
        "needs_context": score < 5,
    }


def save_uploaded_file(file_bytes: bytes, filename: str) -> str:
    """Save uploaded file to creator_media, return path."""
    ext = os.path.splitext(filename)[1] or ".bin"
    name = uuid.uuid4().hex[:12] + ext
    path = os.path.join(CREATOR_MEDIA_DIR, name)
    with open(path, "wb") as f:
        f.write(file_bytes)
    return path
