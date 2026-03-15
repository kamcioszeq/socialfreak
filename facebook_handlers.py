import os
import httpx
from telethon import events
import config
from shared import (
    pending_adoption, pending_posts,
    ask_claude, cleanup_cached_files, track_post,
    make_fb_buttons, make_edit_buttons, make_after_publish_buttons,
    show_loading, restore_buttons, recover_adoption, send_preview, ensure_cached_files, INITIAL_INSTRUCTION,
)

_FB_STANDARD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fb_standard.txt")
try:
    with open(_FB_STANDARD_PATH) as _f:
        FB_STANDARD = _f.read()
except FileNotFoundError:
    FB_STANDARD = ""


FB_HASHTAG_RULE = (
    "HASHTAGI: Na samym końcu dodaj JEDNĄ linię z hashtagami. "
    "Zawsze #wojnaipokoj + 1-2 tematyczne (np. #IranWar #Hezbollah #NATO). "
    "Hashtagi po angielsku, krótkie, bez spacji. Max 3 łącznie."
)

FB_SYSTEM_PROMPT = (
    "Jesteś redaktorem agencji prasowej (styl Associated Press / Reuters). "
    "ZAWSZE pisz PO POLSKU. "
    "Styl: zwięzły, faktograficzny, informacyjny. Suche fakty, zero emocji. "
    "Formatowanie: plain text (Facebook nie obsługuje HTML). "
    "Bez linków. Bez emoji. Bez opinii. "
    "Krótko — 2-3 zdania max. Kto, co, kiedy, gdzie.\n"
    + FB_HASHTAG_RULE
)

FB_GROK_PROMPT = (
    "Jesteś redaktorem polskojęzycznej strony na Facebooku. "
    "ZAWSZE pisz PO POLSKU. "
    "Styl: sarkastyczny, ironiczny, cyniczny. Czarny humor. "
    "Formatowanie: plain text. Bez linków. "
    "Emoji sarkastycznie (🤡🫠💀😏). 2-4 zdania.\n"
    + FB_HASHTAG_RULE
)

FB_SOFT_PROMPT = (
    "Jesteś redaktorem agencji prasowej. "
    "ZAWSZE pisz PO POLSKU. "
    "Styl: neutralny, wyważony, czysto informacyjny. Bez emocji, bez dramatyzmu. "
    "Formatowanie: plain text. Bez linków. Bez emoji. "
    "Suche fakty. 2-3 zdania.\n"
    + FB_HASHTAG_RULE
)

FB_INSTRUCTION = (
    "Napisz krótką notatkę prasową PO POLSKU na podstawie tego tekstu. "
    "Styl agencji prasowej — suche fakty, 2-3 zdania. Bez emoji. Oto tekst:\n\n"
)

FB_GROK_INSTRUCTION = (
    "Napisz post na Facebooka PO POLSKU w stylu Groka — sarkastyczny, ironiczny, cyniczny. "
    "Czarny humor, bez cenzury, bez PC. Emoji sarkastycznie (🤡🫠💀😏). "
    "Oto tekst:\n\n"
)

FB_SOFT_INSTRUCTION = (
    "Napisz ten post na Facebooka PO POLSKU od nowa — neutralny, wyważony, informacyjny. "
    "Bez emocji, bez sarkazmu, bez dramatyzmu. Suche fakty. 2-3 zdania. "
    "Oto tekst:\n\n"
)


async def publish_to_facebook(post, text):
    """Publish text (and optionally first photo) to Facebook Page via Graph API."""
    if not config.FB_PAGE_ACCESS_TOKEN or not config.FB_PAGE_ID:
        return False, "Brak FB_PAGE_ACCESS_TOKEN lub FB_PAGE_ID w .env"

    async with httpx.AsyncClient(timeout=30) as client:
        files = [f for f in post.get("cached_files", []) if __import__("os").path.exists(f)]

        if files:
            with open(files[0], "rb") as f:
                resp = await client.post(
                    f"https://graph.facebook.com/v25.0/{config.FB_PAGE_ID}/photos",
                    data={
                        "caption": text,
                        "access_token": config.FB_PAGE_ACCESS_TOKEN,
                    },
                    files={"source": (files[0], f)},
                )
        else:
            resp = await client.post(
                f"https://graph.facebook.com/v25.0/{config.FB_PAGE_ID}/feed",
                data={
                    "message": text,
                    "access_token": config.FB_PAGE_ACCESS_TOKEN,
                },
            )

    data = resp.json()
    if "id" in data or "post_id" in data:
        fb_id = data.get("id") or data.get("post_id")
        # Record to published history
        try:
            from published_store import append_published
            append_published({
                "platform": "facebook",
                "source": post.get("source", "?"),
                "text": text,
                "original_text": post.get("original_text", ""),
                "post_id": str(post.get("phase1_msg_id", "")),
                "link": fb_id,
                "tags": post.get("tags", []),
            })
        except Exception as e:
            print(f"[PUBLISHED_STORE] Błąd zapisu FB: {e}")
        return True, fb_id
    return False, data.get("error", {}).get("message", str(data))


async def publish_story_to_facebook(file_path):
    """Publish a photo as a Facebook Page Story (Relacja). Two-step: upload unpublished, then publish as story."""
    if not config.FB_PAGE_ACCESS_TOKEN or not config.FB_PAGE_ID:
        return False, "Brak FB_PAGE_ACCESS_TOKEN lub FB_PAGE_ID w .env"

    ext = os.path.splitext(file_path)[1].lower()
    is_video = ext in (".mp4", ".mov", ".avi", ".webm")

    async with httpx.AsyncClient(timeout=60) as client:
        if is_video:
            resp = await client.post(
                f"https://graph.facebook.com/v25.0/{config.FB_PAGE_ID}/video_stories",
                data={
                    "upload_phase": "start",
                    "access_token": config.FB_PAGE_ACCESS_TOKEN,
                },
            )
            init_data = resp.json()
            video_id = init_data.get("video_id")
            upload_url = init_data.get("upload_url")
            if not video_id or not upload_url:
                return False, init_data.get("error", {}).get("message", str(init_data))

            file_size = os.path.getsize(file_path)
            with open(file_path, "rb") as f:
                resp = await client.post(
                    upload_url,
                    headers={
                        "offset": "0",
                        "file_size": str(file_size),
                        "Authorization": f"OAuth {config.FB_PAGE_ACCESS_TOKEN}",
                    },
                    content=f.read(),
                )
            upload_data = resp.json()
            if not upload_data.get("success"):
                return False, f"Upload failed: {upload_data}"

            resp = await client.post(
                f"https://graph.facebook.com/v25.0/{config.FB_PAGE_ID}/video_stories",
                data={
                    "upload_phase": "finish",
                    "video_id": video_id,
                    "access_token": config.FB_PAGE_ACCESS_TOKEN,
                },
            )
            pub_data = resp.json()
            if pub_data.get("success") or "post_id" in pub_data:
                return True, pub_data.get("post_id", video_id)
            return False, pub_data.get("error", {}).get("message", str(pub_data))
        else:
            with open(file_path, "rb") as f:
                resp = await client.post(
                    f"https://graph.facebook.com/v25.0/{config.FB_PAGE_ID}/photos",
                    data={
                        "published": "false",
                        "access_token": config.FB_PAGE_ACCESS_TOKEN,
                    },
                    files={"source": (file_path, f)},
                )
            photo_data = resp.json()
            photo_id = photo_data.get("id")
            if not photo_id:
                return False, photo_data.get("error", {}).get("message", str(photo_data))

            resp = await client.post(
                f"https://graph.facebook.com/v25.0/{config.FB_PAGE_ID}/photo_stories",
                data={
                    "photo_id": photo_id,
                    "access_token": config.FB_PAGE_ACCESS_TOKEN,
                },
            )
            story_data = resp.json()
            if story_data.get("success") or "post_id" in story_data:
                return True, story_data.get("post_id", photo_id)
            return False, story_data.get("error", {}).get("message", str(story_data))


def register_facebook_handlers(bot, userbot):
    """Register all Facebook-platform handlers on the bot."""

    @bot.on(events.CallbackQuery)
    async def on_fb_button(event):
        sender = await event.get_sender()
        if sender.id != config.OWNER_ID:
            return

        msg_id = event.message_id
        data = event.data.decode()

        # ── Adopt for Facebook ──

        if data == "adopt_fb":
            post = pending_adoption.get(msg_id)
            if not post:
                post = await recover_adoption(bot, msg_id)
            if not post:
                return
            await event.answer("Przerabiam na Facebook...")
            await show_loading(event, "Przerabiam na Facebook...")
            print(f"[ADOPT_FB] Przerabiam post z {post['source']}...")

            rewritten = await ask_claude(
                post["original_text"], post["source"], FB_INSTRUCTION,
                system_prompt=FB_SYSTEM_PROMPT,
            )
            print(f"[ADOPT_FB] Gotowe.")

            sent = await send_preview(bot, userbot, post, rewritten, make_fb_buttons(has_media=post.get("has_media", False)), download_media=post.get("has_media", False), reply_to=msg_id)

            pending_posts[sent.id] = track_post(pending_posts, {
                "text": rewritten,
                "original_text": post["original_text"],
                "source": post["source"],
                "messages": post["messages"],
                "has_media": post["has_media"],
                "cached_files": post.get("cached_files", []),
                "forwarded": post.get("forwarded", False),
                "edit_chain": ["adopt_fb"],
                "platform": "facebook",
                "phase1_msg_id": msg_id,
            }, sent_id=sent.id)
            await restore_buttons(bot, msg_id, post)
            return

        # ── Longer FB ──

        if data == "longer_fb":
            post = pending_posts.get(msg_id)
            if not post or post.get("platform") != "facebook":
                return
            await event.answer("Wydłużam...")
            await show_loading(event, "Wydłużam...")
            print(f"[LONGER_FB] Przerabiam post z {post['source']}...")

            rewritten = await ask_claude(
                post["original_text"], post["source"],
                "Rozbuduj ten post — dodaj więcej szczegółów, kontekstu, tła wydarzeń. "
                "Zachowaj styl agencji prasowej. PO POLSKU. Oto tekst:\n\n" + post["text"],
                system_prompt=FB_SYSTEM_PROMPT,
            )
            print(f"[LONGER_FB] Gotowe.")

            anchor = post.get("phase1_msg_id")
            sent = await send_preview(bot, userbot, post, rewritten, make_fb_buttons(has_media=post.get("has_media", False)), download_media=post.get("has_media", False), reply_to=anchor)

            post["text"] = rewritten
            post.setdefault("edit_chain", []).append("longer_fb")
            del pending_posts[msg_id]
            pending_posts[sent.id] = track_post(pending_posts, post, sent_id=sent.id)

            try:
                await (await event.get_message()).delete()
            except Exception:
                pass
            return

        # ── Shorter FB ──

        if data == "shorter_fb":
            post = pending_posts.get(msg_id)
            if not post or post.get("platform") != "facebook":
                return
            await event.answer("Skracam...")
            await show_loading(event, "Skracam...")
            print(f"[SHORTER_FB] Przerabiam post z {post['source']}...")

            rewritten = await ask_claude(
                post["original_text"], post["source"],
                "Skróć ten post MINIMUM o 50%%. Zostaw tylko najważniejsze fakty. "
                "Styl agencji prasowej. PO POLSKU. Oto tekst:\n\n" + post["text"],
                system_prompt=FB_SYSTEM_PROMPT,
            )
            print(f"[SHORTER_FB] Gotowe.")

            anchor = post.get("phase1_msg_id")
            sent = await send_preview(bot, userbot, post, rewritten, make_fb_buttons(has_media=post.get("has_media", False)), download_media=post.get("has_media", False), reply_to=anchor)

            post["text"] = rewritten
            post.setdefault("edit_chain", []).append("shorter_fb")
            del pending_posts[msg_id]
            pending_posts[sent.id] = track_post(pending_posts, post, sent_id=sent.id)

            try:
                await (await event.get_message()).delete()
            except Exception:
                pass
            return

        # ── Retry FB ──

        if data == "retry_fb":
            post = pending_posts.get(msg_id)
            if not post or post.get("platform") != "facebook":
                return
            await event.answer("Retry FB...")
            await show_loading(event, "Retry FB...")
            print(f"[RETRY_FB] Przerabiam post z {post['source']}...")

            rewritten = await ask_claude(
                post["original_text"], post["source"],
                "Napisz ten post na Facebooka ZUPEŁNIE OD NOWA — inny styl, inny kąt. PO POLSKU. Oto tekst:\n\n" + post["original_text"],
                system_prompt=FB_SYSTEM_PROMPT,
            )
            print(f"[RETRY_FB] Gotowe.")

            anchor = post.get("phase1_msg_id")
            sent = await send_preview(bot, userbot, post, rewritten, make_fb_buttons(has_media=post.get("has_media", False)), download_media=post.get("has_media", False), reply_to=anchor)

            post["text"] = rewritten
            post.setdefault("edit_chain", []).append("retry_fb")
            del pending_posts[msg_id]
            pending_posts[sent.id] = track_post(pending_posts, post, sent_id=sent.id)

            try:
                await (await event.get_message()).delete()
            except Exception:
                pass
            return

        # ── Grok FB ──

        if data == "grok_fb":
            post = pending_posts.get(msg_id)
            if not post or post.get("platform") != "facebook":
                return
            await event.answer("Grok FB 😈...")
            await show_loading(event, "Grok FB 😈...")
            print(f"[GROK_FB] Przerabiam post z {post['source']}...")

            rewritten = await ask_claude(
                post["original_text"], post["source"],
                FB_GROK_INSTRUCTION + post["original_text"],
                system_prompt=FB_GROK_PROMPT,
            )
            print(f"[GROK_FB] Gotowe.")

            anchor = post.get("phase1_msg_id")
            sent = await send_preview(bot, userbot, post, rewritten, make_fb_buttons(has_media=post.get("has_media", False)), download_media=post.get("has_media", False), reply_to=anchor)

            post["text"] = rewritten
            post.setdefault("edit_chain", []).append("grok_fb")
            del pending_posts[msg_id]
            pending_posts[sent.id] = track_post(pending_posts, post, sent_id=sent.id)

            try:
                await (await event.get_message()).delete()
            except Exception:
                pass
            return

        # ── Beautify FB ──

        if data == "beautify_fb":
            post = pending_posts.get(msg_id)
            if not post or post.get("platform") != "facebook":
                return
            await event.answer("Ulepszam ✨...")
            await show_loading(event, "Ulepszam ✨...")
            print(f"[BEAUTIFY_FB] Przerabiam post z {post['source']}...")

            rewritten = await ask_claude(
                post["original_text"], post["source"],
                "Przebuduj wizualnie ten post na Facebooka:\n"
                "• Dodaj mocny NAGŁÓWEK na górze — krótki, z 2 emoji nawiązującymi do tematu (np. 🔥🇺🇦, ⚡🇮🇱)\n"
                "• Rozdziel tekst na krótkie akapity\n"
                "• Użyj emoji jako bullet points (➡️ 📌 🔹 ⚠️) przy kluczowych punktach\n"
                "• Dodaj emoji przy ważnych frazach (💥⚡🚨🛡️⚔️🎯)\n"
                "• Zachowaj wszystkie fakty, zmień TYLKO wizualną prezentację\n"
                "• Formatowanie: plain text (Facebook nie obsługuje HTML)\n"
                "PO POLSKU. Oto tekst:\n\n" + post["text"],
                system_prompt=FB_SYSTEM_PROMPT,
            )
            print(f"[BEAUTIFY_FB] Gotowe.")

            anchor = post.get("phase1_msg_id")
            sent = await send_preview(bot, userbot, post, rewritten, make_fb_buttons(has_media=post.get("has_media", False)), download_media=post.get("has_media", False), reply_to=anchor)

            post["text"] = rewritten
            post.setdefault("edit_chain", []).append("beautify_fb")
            del pending_posts[msg_id]
            pending_posts[sent.id] = track_post(pending_posts, post, sent_id=sent.id)

            try:
                await (await event.get_message()).delete()
            except Exception:
                pass
            return

        # ── Soft FB ──

        if data == "soft_fb":
            post = pending_posts.get(msg_id)
            if not post or post.get("platform") != "facebook":
                return
            await event.answer("Soft FB 😇...")
            await show_loading(event, "Soft FB 😇...")
            print(f"[SOFT_FB] Przerabiam post z {post['source']}...")

            rewritten = await ask_claude(
                post["original_text"], post["source"],
                FB_SOFT_INSTRUCTION + post["original_text"],
                system_prompt=FB_SOFT_PROMPT,
            )
            print(f"[SOFT_FB] Gotowe.")

            anchor = post.get("phase1_msg_id")
            sent = await send_preview(bot, userbot, post, rewritten, make_fb_buttons(has_media=post.get("has_media", False)), download_media=post.get("has_media", False), reply_to=anchor)

            post["text"] = rewritten
            post.setdefault("edit_chain", []).append("soft_fb")
            del pending_posts[msg_id]
            pending_posts[sent.id] = track_post(pending_posts, post, sent_id=sent.id)

            try:
                await (await event.get_message()).delete()
            except Exception:
                pass
            return

        # ── Source FB — append source to post ──

        if data == "source_fb":
            post = pending_posts.get(msg_id)
            if not post or post.get("platform") != "facebook":
                return
            print(f"[SOURCE_FB] msg_id={msg_id} → dodaję źródło z {post['source']}")
            source = post.get("source", "")
            if source and not post["text"].endswith(source):
                post["text"] = post["text"].rstrip() + f"\n\n{source}"
            await event.answer("Dodano źródło")
            try:
                original_msg = await event.get_message()
                await original_msg.edit(post["text"], buttons=make_fb_buttons(has_media=post.get("has_media", False)))
            except Exception:
                pass
            return

        # ── Verify FB — check against community standards ──

        if data == "verify_fb":
            post = pending_posts.get(msg_id)
            if not post or post.get("platform") != "facebook":
                return
            await event.answer("Weryfikuję...")
            await show_loading(event, "Weryfikuję zgodność...")
            print(f"[VERIFY_FB] Sprawdzam post z {post['source']}...")

            verify_instruction = (
                "Oceń poniższy post na Facebooka pod kątem zgodności ze standardami społeczności.\n\n"
                "STANDARDY:\n" + FB_STANDARD + "\n\n"
                "POST DO OCENY:\n" + post["text"] + "\n\n"
                "Odpowiedz TYLKO w jednej linii w formacie:\n"
                "WYNIK/RYZYKO|REGUŁY|KOMENTARZ\n"
                "Przykład: 15/SAFE|BRAK|Post informacyjny, brak naruszeń.\n"
                "Przykład: 72/MEDIUM|AUT_02,VIO_03|Potencjalna dezinformacja i gloryfikacja przemocy.\n"
                "WYNIK to liczba 0-100. RYZYKO: SAFE/LOW/MEDIUM/HIGH. Pisz PO POLSKU."
            )
            result = await ask_claude(
                post["text"], post["source"], verify_instruction,
                system_prompt="Jesteś ekspertem od moderacji treści na Facebooku. Oceniasz posty pod kątem zgodności ze standardami społeczności. Odpowiadaj JEDNĄ LINIĄ w podanym formacie.",
            )
            print(f"[VERIFY_FB] Gotowe: {result[:80]}")

            import re
            score_match = re.search(r'(\d+)\s*/\s*(SAFE|LOW|MEDIUM|HIGH)', result)
            if score_match:
                score = score_match.group(1)
                risk = score_match.group(2)
                verify_label = f"✅ Verify({score}/{risk})"
            else:
                verify_label = f"✅ Verify(?)"

            from telethon import Button
            buttons = [
                [Button.inline("Publikuj F", b"pub_fb"), Button.inline("Odrzuć", b"pub_no")],
                [Button.inline("Wydłuż", b"longer_fb"), Button.inline("Skróć", b"shorter_fb"), Button.inline("Retry", b"retry_fb")],
                [Button.inline("Grok 😈", b"grok_fb"), Button.inline("😇", b"soft_fb"), Button.inline("🔗 Źródło", b"source_fb")],
                [Button.inline(verify_label, b"verify_fb_detail")],
            ]
            if post.get("has_media"):
                buttons.append([Button.inline("💾", b"dl_media"), Button.inline("🍣", b"save_reel")])

            post["_verify_result"] = result
            try:
                msg = await bot.get_messages(config.OWNER_ID, ids=msg_id)
                if msg:
                    await msg.edit(buttons=buttons)
            except Exception:
                pass
            return

        if data == "verify_fb_detail":
            post = pending_posts.get(msg_id)
            if not post:
                return
            detail = post.get("_verify_result", "Brak wyniku")
            await event.answer(detail[:200], alert=True)
            return

        # ── Publish FB ──

        if data == "pub_fb":
            post = pending_posts.get(msg_id)
            if not post or post.get("platform") != "facebook":
                return
            await event.answer("Publikuję na Facebooku...")
            await show_loading(event, "Publikuję na FB...")
            print(f"[PUB_FB] Tekst: {post['text'][:100]}")

            if post.get("has_media"):
                download_client = bot if post.get("forwarded") else userbot
                await ensure_cached_files(download_client, post)

            ok, result = await publish_to_facebook(post, post["text"])
            original_msg = await event.get_message()

            if ok:
                await original_msg.edit(
                    original_msg.text + f"\n\n✅ OPUBLIKOWANO NA FB (id: {result})",
                    buttons=make_after_publish_buttons("facebook"),
                )
                post["platform"] = "fb_done"
                print(f"[PUB_FB] Opublikowano: {result}")
            else:
                await original_msg.edit(
                    original_msg.text + f"\n\n❌ BŁĄD FB: {result}",
                    buttons=make_fb_buttons(has_media=post.get("has_media", False)),
                )
                print(f"[PUB_FB] Błąd: {result}")
            return

        # ── Continue to Facebook after T/X ──

        if data == "continue_fb":
            post = pending_posts.get(msg_id)
            if not post:
                await event.answer("Post wygasł")
                return
            await event.answer("Przerabiam na Facebook...")
            await show_loading(event, "Przerabiam na Facebook...")
            print(f"[CONTINUE_FB] Przerabiam post z {post['source']} na Facebook...")

            rewritten = await ask_claude(post["original_text"], post["source"], FB_INSTRUCTION, system_prompt=FB_SYSTEM_PROMPT)
            print(f"[CONTINUE_FB] Gotowe.")

            anchor = post.get("phase1_msg_id")

            new_post = {
                "text": rewritten,
                "original_text": post["original_text"],
                "source": post["source"],
                "messages": post["messages"],
                "has_media": post["has_media"],
                "cached_files": post.get("cached_files", []),
                "forwarded": post.get("forwarded", False),
                "edit_chain": ["adopt_fb"],
                "platform": "facebook",
                "phase1_msg_id": anchor,
            }
            sent = await send_preview(bot, userbot, new_post, rewritten, make_fb_buttons(has_media=post.get("has_media", False)), download_media=post.get("has_media", False), reply_to=anchor)

            del pending_posts[msg_id]
            pending_posts[sent.id] = track_post(pending_posts, new_post, sent_id=sent.id)

            try:
                await (await event.get_message()).delete()
            except Exception:
                pass
            return
