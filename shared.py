import hashlib
import json
import os
import re
import shutil
import time
import uuid
import httpx
from telethon import Button
from telethon.tl.types import MessageEntityBlockquote, MessageEntityBold
import config

# ─── Shared state ─────────────────────────────────────────

pending_adoption = {}  # msg_id -> {original_text, source, messages (list of msgs), has_media}
pending_posts = {}     # msg_id -> {text, original_text, source, messages, has_media}
source_entities = {}   # channel_username -> entity
last_seen_ids = {}     # channel_id -> last msg.id
forward_buffer = {}    # grouped_id -> {messages: [], source: str, timer: asyncio.Task}
reel_sessions = {}     # owner_id -> {items: [...], index: int, selected: set()}

MEDIA_DIR = "media_cache"
os.makedirs(MEDIA_DIR, exist_ok=True)

REELS_DIR = "reels_cache"
os.makedirs(REELS_DIR, exist_ok=True)
REELS_JSON = os.path.join(REELS_DIR, "reels_media.json")
REELS_TTL = 2592000  # 30 days

POLL_INTERVAL = 100
CLEANUP_INTERVAL = 1800
ADOPTION_TTL = 172800   # 2 days
POST_TTL = 86400        # 1 day


# ─── Reels persistent storage ────────────────────────────────

def load_reels():
    try:
        with open(REELS_JSON, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_reels(reels):
    with open(REELS_JSON, "w") as f:
        json.dump(reels, f, indent=2)


def _file_hash(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def is_reel_duplicate(file_path):
    """Check if file already exists in reels (by content hash)."""
    new_hash = _file_hash(file_path)
    for r in load_reels():
        if os.path.exists(r["file_path"]) and _file_hash(r["file_path"]) == new_hash:
            return True
    return False


def add_reel_media(file_path, source):
    """Copy media to reels_cache and register in JSON. Returns the new entry or None if duplicate."""
    if is_reel_duplicate(file_path):
        return None

    ext = os.path.splitext(file_path)[1]
    reel_id = uuid.uuid4().hex[:12]
    dest = os.path.join(REELS_DIR, f"{reel_id}{ext}")
    shutil.copy2(file_path, dest)

    entry = {
        "id": reel_id,
        "file_path": dest,
        "source": source,
        "timestamp": time.time(),
        "used": False,
    }
    reels = load_reels()
    reels.append(entry)
    save_reels(reels)
    return entry


def get_unused_reels():
    return [r for r in load_reels() if not r.get("used") and os.path.exists(r["file_path"])]


def mark_reels_used(reel_ids):
    reels = load_reels()
    for r in reels:
        if r["id"] in reel_ids:
            r["used"] = True
    save_reels(reels)


def get_expired_reels():
    now = time.time()
    return [r for r in load_reels() if now - r.get("timestamp", now) > REELS_TTL and not r.get("used")]


def delete_reels(reel_ids):
    reels = load_reels()
    to_delete = [r for r in reels if r["id"] in reel_ids]
    for r in to_delete:
        if os.path.exists(r["file_path"]):
            os.remove(r["file_path"])
    reels = [r for r in reels if r["id"] not in reel_ids]
    save_reels(reels)

# ─── Claude API ──────────────────────────────────────────────

SYSTEM_PROMPT = (
    "Jesteś redaktorem kanału informacyjnego na Telegramie. "
    "Przerabiasz posty z innych kanałów. "
    "Formatowanie: HTML dla Telegrama. Używaj <b>bold</b> do pogrubień. NIGDY nie używaj kursywy. "
    "Cytaty formatuj jako <blockquote>tekst cytatu</blockquote>. "
    "NIGDY nie dodawaj źródła, linków, ani nazwy kanału źródłowego. "
    "\n"
    "NAGŁÓWEK (pierwsza linia):\n"
    "Musi być przyciągający uwagę, z 2 emoji nawiązującymi do tematu. Przykłady:\n"
    "<b>💥🇮🇱 Izrael uderza — eskalacja na granicy z Libanem</b>\n"
    "<b>⚡🇺🇦 Przełom na froncie — Ukraina odzyskuje teren</b>\n"
    "<b>🚨🇮🇷 Iran pod presją — nowa runda sankcji</b>\n"
    "<b>🔥💣 Bliski Wschód w ogniu — kolejne naloty</b>\n"
    "Nagłówek musi być krótki (max 8-10 słów), mocny i clickbaitowy ale oparty na faktach. "
    "Użyj 2 emoji na początku — flaga kraju + emoji nawiązujące do treści (💥⚡🔥🚨💣🛡️⚔️🎯). "
    "\n"
    "Po nagłówku zostaw pustą linię, potem treść. "
    "\n"
    "\n"
    "TREŚĆ:\n"
    "ZACHOWAJ STRUKTURĘ ORYGINAŁU. Jeśli oryginał to krótki akapit — napisz krótki akapit. "
    "Jeśli oryginał to lista — napisz listę. NIE zamieniaj krótkiego tekstu w długą listę punktów. "
    "Zachowaj podobną długość i formę do oryginału. Jeśli oryginał ma ponad 200 słów — skróć o 50%%. "
    "NIGDY nie stawiaj interpunkcji bezpośrednio po emoji — oddziel spacją. "
    "Jeśli w oryginale jest cytat — formatuj jako blockquote, np.:\n"
    "<blockquote>💬 Biden: 'nie szukamy eskalacji'</blockquote>\n"
    "Nie wymyślaj cytatów — tylko te z oryginału. "
    "Używaj emoji w tekście ale max 2-3 w całym tekście. "
    "\n"
    "WAŻNE: Tekst musi wyglądać jak ORYGINALNY artykuł, NIE jak tłumaczenie. "
    "Przeformułuj całkowicie, użyj innych słów. Nie kopiuj struktury oryginału słowo w słowo. "
    "\n"
    "STOPKA — DOKŁADNIE JEDNA LINIA na samym końcu, nic więcej po niej:\n"
    "<b>Nazwa Konfliktu</b> | @geopolitykapl\n"
    "UWAGA: zawsze pisz dokładnie '@geopolitykapl' — NIE 'geopolitika', NIE 'geopolityka'. Dokładnie: @geopolitykapl"
)


async def ask_claude(text: str, source_channel: str, instruction: str, *, system_prompt: str = None) -> str:
    prompt = (
        f"Kanał źródłowy: {source_channel}\n\n"
        f"Oryginalny tekst:\n{text}\n\n"
        f"Instrukcja: {instruction}"
    )

    body = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_prompt is not None:
        body["system"] = system_prompt
    else:
        body["system"] = SYSTEM_PROMPT

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": config.CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
            timeout=30,
        )

    data = response.json()
    if data.get("content"):
        texts = [b["text"] for b in data["content"] if b["type"] == "text"]
        return "\n".join(texts)
    return f"Błąd Claude: {data.get('error', {}).get('message', 'unknown')}"


INITIAL_INSTRUCTION = (
    "Przetłumacz na polski. Skróć o około 50% ale zachowaj kluczowe fakty. "
    "Nie może być za krótkie — minimum 2-3 zdania."
)


async def ask_claude_tags(text: str, source: str) -> list:
    """Ask Claude to return 1-3 topic tags for a post."""
    prompt = (
        f"Kanał źródłowy: {source}\n\n"
        f"Tekst:\n{text}\n\n"
        "Na podstawie tekstu i źródła zwróć 1-3 tagi tematyczne (po polsku lub angielsku). "
        "Przykłady: Ukraina, NATO, BliskiWschód, Iran, Izrael, Rosja, USA, Cyberwojna, Energetyka. "
        "Tylko lista tagów, po jednym w linii. Bez # i bez numeracji."
    )
    try:
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
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=15,
            )
        data = response.json()
        if data.get("content"):
            raw = data["content"][0]["text"]
            tags = [t.strip().lstrip("#").strip() for t in raw.strip().split("\n") if t.strip()]
            return tags[:3]
    except Exception as e:
        print(f"[TAGS] Błąd: {e}")
    return []


async def ask_claude_tone(text: str) -> str:
    """Ask Claude to detect tone: escalation, tension, or diplomacy."""
    prompt = (
        f"Tekst:\n{text}\n\n"
        "Określ ton tego tekstu. Odpowiedz JEDNYM słowem: escalation, tension, lub diplomacy."
    )
    try:
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
                    "max_tokens": 20,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=10,
            )
        data = response.json()
        if data.get("content"):
            raw = data["content"][0]["text"].strip().lower()
            for tone in ("escalation", "tension", "diplomacy"):
                if tone in raw:
                    return tone
            return raw
    except Exception as e:
        print(f"[TONE] Błąd: {e}")
    return ""


async def ask_claude_vision(image_path: str, context: str = "") -> str:
    """Send image to Claude for geopolitical/news analysis."""
    import base64
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode()

    ext = os.path.splitext(image_path)[1].lower()
    media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "image/jpeg")

    context_line = f"\nKontekst posta (tekst towarzyszący zdjęciu): {context}\n" if context else ""

    prompt = (
        f"Przeanalizuj ten obraz w kontekście geopolitycznym i informacyjnym.{context_line}\n"
        "1) Jeśli na obrazie jest tekst (screenshot, artykuł, tweet, post) — przeczytaj go i zwróć PEŁNĄ treść.\n"
        "2) Jeśli to zdjęcie/grafika — opisz CO WIDZISZ i JAKI KONTEKST POLITYCZNY/WOJSKOWY/GEOPOLITYCZNY to sugeruje.\n"
        "   Przykłady: zniszczony budynek → ostrzał/bombardowanie jakiego miasta/regionu; "
        "kolumna wojskowa → przemieszczanie sił; mapa → analiza terytoriów; "
        "protest → kontekst polityczny; politycy → kto z kim rozmawia i o czym.\n"
        "3) Podaj krótką notkę (3-5 zdań) po polsku: co widać + jaki kontekst geopolityczny.\n"
        "   Na końcu dodaj linię: <b>Ocena</b>: [eskalacja/deeskalacja/neutralne/dyplomacja/pomoc humanitarna]\n\n"
        "Pisz zwięźle, po polsku. Formatuj HTML (<b>bold</b>)."
    )

    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
        {"type": "text", "text": prompt},
    ]

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
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": content}],
            },
            timeout=30,
        )

    data = response.json()
    if data.get("content"):
        texts = [b["text"] for b in data["content"] if b["type"] == "text"]
        return "\n".join(texts)
    return f"Błąd Claude: {data.get('error', {}).get('message', 'unknown')}"


async def show_loading(event, label="Przerabiam..."):
    """Edit message buttons to a loading state so user sees visual feedback."""
    try:
        msg = await event.get_message()
        await msg.edit(buttons=[[Button.inline(f"⏳ {label}", b"_noop")]])
    except Exception:
        pass


async def restore_buttons(bot, msg_id, post):
    """Restore Phase 1 buttons on the original message after adopt/translate."""
    try:
        msg = await bot.get_messages(config.OWNER_ID, ids=msg_id)
        if msg:
            await msg.edit(buttons=make_adopt_buttons(has_media=post.get("has_media", False)))
    except Exception:
        pass


# ─── Buttons ─────────────────────────────────────────────────

def _media_row(has_media):
    """Common row with download + sushi buttons when post has media."""
    if not has_media:
        return []
    return [[Button.inline("💾", b"dl_media"), Button.inline("🍣", b"save_reel")]]


def make_adopt_buttons(has_media=False):
    row = [Button.inline("🔄 Tłumacz", b"translate_raw"), Button.inline("T/X", b"choose_platform")]
    if has_media:
        row.append(Button.inline("📷 Zdjęcie", b"photo_read"))
    rows = [row, [Button.inline("Odrzuć", b"reject")]]
    rows.extend(_media_row(has_media))
    return rows


def make_platform_buttons(has_media=False):
    rows = [
        [Button.inline("Zaadoptuj T", b"adopt"), Button.inline("Zaadoptuj X", b"adopt_x"), Button.inline("Zaadoptuj F", b"adopt_fb")],
        [Button.inline("← Wróć", b"back_adopt"), Button.inline("Odrzuć", b"reject")],
    ]
    rows.extend(_media_row(has_media))
    return rows


def make_edit_buttons(has_media=False):
    top_row = [Button.inline("📷", b"pub_yes"), Button.inline("📝", b"pub_text_only")] if has_media else [Button.inline("Publikuj", b"pub_yes")]
    top_row.append(Button.inline("Odrzuć", b"pub_no"))
    rows = [
        top_row,
        [Button.inline("Wydłuż", b"longer"), Button.inline("Skróć", b"shorter"), Button.inline("Grok 😈", b"grok")],
        [Button.inline("Retry", b"retry"), Button.inline("Soft", b"soft"), Button.inline("Harder", b"harder")],
        [Button.inline("✨", b"beautify"), Button.inline("🕊️", b"pc"), Button.inline("🔄", b"translate"), Button.inline("Edytuj", b"pub_edit"), Button.inline("🌍", b"countries")],
    ]
    rows.extend(_media_row(has_media))
    return rows


def make_x_buttons(has_media=False):
    rows = [
        [Button.inline("Publikuj X", b"pub_x"), Button.inline("Odrzuć", b"pub_no")],
        [Button.inline("Retry", b"retry_x"), Button.inline("Grok 😈", b"grok_x"), Button.inline("😇", b"soft_x")],
        [Button.inline("🔗 Źródło", b"source_x"), Button.inline("✅ Verify(X)", b"verify_x")],
    ]
    rows.extend(_media_row(has_media))
    return rows


def make_fb_buttons(has_media=False):
    rows = [
        [Button.inline("Publikuj F", b"pub_fb"), Button.inline("Odrzuć", b"pub_no")],
        [Button.inline("Wydłuż", b"longer_fb"), Button.inline("Skróć", b"shorter_fb"), Button.inline("Retry", b"retry_fb")],
        [Button.inline("Grok 😈", b"grok_fb"), Button.inline("😇", b"soft_fb"), Button.inline("✨", b"beautify_fb")],
        [Button.inline("🔗 Źródło", b"source_fb"), Button.inline("✅ Verify(FB)", b"verify_fb")],
    ]
    rows.extend(_media_row(has_media))
    return rows


def make_after_publish_buttons(published_platform):
    """Buttons shown after publishing — allow adopting on the other platform."""
    btns = []
    if published_platform != "telegram":
        btns.append(Button.inline("➡️ Zaadoptuj T", b"continue_t"))
    if published_platform != "x":
        btns.append(Button.inline("➡️ Zaadoptuj X", b"continue_x"))
    if published_platform != "facebook":
        btns.append(Button.inline("➡️ Zaadoptuj F", b"continue_fb"))
    rows = [btns] if btns else []
    rows.append([Button.inline("Odrzuć", b"pub_no")])
    return rows


# Country bias pages
COUNTRIES_PAGE_1 = [
    [Button.inline("🇺🇸", b"bias_US"), Button.inline("🇵🇱", b"bias_PL"), Button.inline("🇮🇱", b"bias_IL"), Button.inline("🇮🇷", b"bias_IR")],
    [Button.inline("🇱🇧", b"bias_LB"), Button.inline("🇵🇸", b"bias_PS"), Button.inline("🇮🇶", b"bias_IQ"), Button.inline("🇦🇪", b"bias_AE")],
    [Button.inline("🇶🇦", b"bias_QA"), Button.inline("🇰🇼", b"bias_KW"), Button.inline("🇦🇿", b"bias_AZ"), Button.inline("🇴🇲", b"bias_OM")],
    [Button.inline("🇹🇷", b"bias_TR"), Button.inline("🇩🇪", b"bias_DE"), Button.inline("🇫🇷", b"bias_FR"), Button.inline("🇪🇸", b"bias_ES")],
    [Button.inline("Strona 2 →", b"countries_p2")],
]

COUNTRIES_PAGE_2 = [
    [Button.inline("🇬🇧", b"bias_GB"), Button.inline("🇲🇽", b"bias_MX"), Button.inline("🇨🇴", b"bias_CO"), Button.inline("🇻🇪", b"bias_VE")],
    [Button.inline("🇨🇺", b"bias_CU"), Button.inline("🇮🇩", b"bias_ID"), Button.inline("🇨🇳", b"bias_CN"), Button.inline("🇷🇺", b"bias_RU")],
    [Button.inline("🇺🇦", b"bias_UA"), Button.inline("🇯🇵", b"bias_JP"), Button.inline("🇰🇷", b"bias_KR"), Button.inline("🇮🇳", b"bias_IN")],
    [Button.inline("← Strona 1", b"countries_p1")],
]

COUNTRY_NAMES = {
    "US": "USA", "PL": "Polska", "IL": "Izrael", "IR": "Iran",
    "LB": "Liban", "PS": "Palestyna", "IQ": "Irak", "AE": "Zjednoczone Emiraty Arabskie",
    "QA": "Katar", "KW": "Kuwejt", "AZ": "Azerbejdżan", "OM": "Oman",
    "TR": "Turcja", "DE": "Niemcy", "FR": "Francja", "ES": "Hiszpania",
    "GB": "Wielka Brytania", "MX": "Meksyk", "CO": "Kolumbia", "VE": "Wenezuela",
    "CU": "Kuba", "ID": "Indonezja", "CN": "Chiny", "RU": "Rosja",
    "UA": "Ukraina", "JP": "Japonia", "KR": "Korea Południowa", "IN": "Indie",
}


# ─── Helpers ─────────────────────────────────────────────────

def truncate_text(text, max_lines=3):
    """Return (display_text, extra_entities) where the overflow is in a collapsed blockquote."""
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text, []
    visible = "\n".join(lines[:max_lines])
    hidden = "\n".join(lines[max_lines:])
    full_text = f"{visible}\n{hidden}"
    collapsed_offset = len(visible) + 1
    collapsed_length = len(hidden)
    entity = MessageEntityBlockquote(offset=collapsed_offset, length=collapsed_length, collapsed=True)
    return full_text, [entity]


def make_preview(header, body_text):
    """Build preview text + entities with bold header, short excerpt, and entire body in a collapsed blockquote."""
    first_line = body_text.split("\n")[0][:80].strip()
    if not first_line:
        first_line = body_text[:80].strip()
    excerpt = f"💬 {first_line}{'…' if len(body_text) > len(first_line) else ''}"

    full_text = f"{header}\n{excerpt}\n\n{body_text}"
    header_len = len(header)
    body_offset = header_len + 1 + len(excerpt) + 2
    entities = [
        MessageEntityBold(offset=0, length=header_len),
        MessageEntityBlockquote(offset=body_offset, length=len(body_text), collapsed=True),
    ]
    return full_text, entities


def cleanup_cached_files(post):
    """Remove cached media files for a post."""
    for f in post.get("cached_files", []):
        if os.path.exists(f):
            os.remove(f)
    post["cached_files"] = []


def track_post(d, post, *, sent_id=None):
    """Add post to dict with created_at timestamp."""
    post.setdefault("created_at", time.time())
    if sent_id is not None:
        source = post.get("source", "?")
        text_preview = (post.get("original_text") or post.get("text", ""))[:50]
        print(f"[TRACK] msg_id={sent_id} → {source}: {text_preview}")
    return post


async def recover_adoption(bot, msg_id):
    """Try to recover a post from the Telegram message after bot restart."""
    try:
        msg = await bot.get_messages(config.OWNER_ID, ids=msg_id)
        if not msg:
            return None

        text = msg.text or msg.message or ""
        if not text:
            return None

        source_match = re.search(r'(?:post|Tłumaczenie|Post) z (@?\S+?)[:)]', text)
        source = source_match.group(1) if source_match else "recovered"

        lines = text.split('\n')
        original_text = text
        for i, line in enumerate(lines):
            if line.startswith('💬 '):
                rest = '\n'.join(lines[i + 1:]).strip()
                if rest:
                    original_text = rest
                break

        has_media = bool(msg.photo or msg.video)
        cached_files = []
        if has_media:
            path = await bot.download_media(msg, file=MEDIA_DIR)
            if path:
                cached_files = [path]

        post = {
            "original_text": original_text,
            "source": source,
            "messages": [msg] if has_media else [],
            "has_media": has_media,
            "cached_files": cached_files,
            "forwarded": True,
        }

        pending_adoption[msg_id] = track_post(pending_adoption, post, sent_id=msg_id)
        print(f"[RECOVER] Odtworzono post msg_id={msg_id} z {source} (media: {has_media})")
        return post

    except Exception as e:
        print(f"[RECOVER] Błąd: {e}")
        return None


async def ensure_cached_files(userbot, post):
    """Download media files if not already cached. Returns list of file paths."""
    files = [f for f in post.get("cached_files", []) if os.path.exists(f)]
    if files:
        return files

    for msg in post.get("messages", []):
        if msg.photo or msg.video:
            path = await userbot.download_media(msg, file=MEDIA_DIR)
            if path:
                files.append(path)
    post["cached_files"] = list(files)
    return files


async def publish_to_channel(userbot, bot, post, text):
    """Publish final post to channel with media."""
    download_client = bot if post.get("forwarded") else userbot
    files = await ensure_cached_files(download_client, post)

    if len(files) > 1:
        await userbot.send_file(config.CHANNEL_ID, files)
        await userbot.send_message(config.CHANNEL_ID, text, parse_mode='html')
    elif len(files) == 1:
        if len(text) > 1024:
            await userbot.send_file(config.CHANNEL_ID, files[0])
            await userbot.send_message(config.CHANNEL_ID, text, parse_mode='html')
        else:
            await userbot.send_file(config.CHANNEL_ID, files[0], caption=text, parse_mode='html')
    else:
        await userbot.send_message(config.CHANNEL_ID, text, parse_mode='html')

    # Record to published history
    try:
        from published_store import append_published
        append_published({
            "platform": "telegram",
            "source": post.get("source", "?"),
            "text": text,
            "original_text": post.get("original_text", ""),
            "post_id": str(post.get("phase1_msg_id", "")),
            "tags": post.get("tags", []),
        })
    except Exception as e:
        print(f"[PUBLISHED_STORE] Błąd zapisu: {e}")


async def send_preview(bot, userbot, post, text, buttons, *, download_media=False, formatting_entities=None, reply_to=None):
    """Send preview to owner. Always one message. With media when download_media=True."""
    if post.get("has_media") and download_media:
        download_client = bot if post.get("forwarded") else userbot
        files = await ensure_cached_files(download_client, post)

        if files:
            extra = f"\n\n📎 +{len(files) - 1} więcej" if len(files) > 1 else ""
            caption = text + extra
            if len(caption) > 1024:
                caption = caption[:1020] + "…"
            return await bot.send_file(config.OWNER_ID, files[0], caption=caption, buttons=buttons, parse_mode='html', reply_to=reply_to)

    elif post.get("has_media") and not download_media:
        text = (text.rstrip() + "\n\n📎 załącznik — pobierz po Zaadoptuj").strip()

    if formatting_entities:
        return await bot.send_message(config.OWNER_ID, text, buttons=buttons, formatting_entities=formatting_entities, reply_to=reply_to)
    return await bot.send_message(config.OWNER_ID, text, buttons=buttons, parse_mode='html', reply_to=reply_to)
