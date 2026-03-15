import os
import re
from telethon import events, Button
import config
from shared import (
    pending_adoption, pending_posts,
    ask_claude, cleanup_cached_files, track_post,
    make_x_buttons, make_edit_buttons, make_after_publish_buttons,
    show_loading, restore_buttons, recover_adoption, send_preview, ensure_cached_files, INITIAL_INSTRUCTION,
)

_FB_STANDARD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fb_standard.txt")
try:
    with open(_FB_STANDARD_PATH) as _f:
        X_STANDARD = _f.read()
except FileNotFoundError:
    X_STANDARD = ""


X_SYSTEM_PROMPT = (
    "Jesteś redaktorem polskojęzycznego konta na X (Twitter). "
    "ZAWSZE pisz PO POLSKU. "
    "Pisz zwięźle — max 280 znaków (limit tweeta). "
    "Styl: mocny, informacyjny, z 1-2 emoji. "
    "Formatowanie: plain text (X nie obsługuje HTML/bold). "
    "Bez hashtagów. Bez linków. "
    "Jeden krótki, uderzający tweet po polsku. "
    "NIGDY nie przekraczaj 280 znaków."
)

X_SOFT_PROMPT = (
    "Jesteś redaktorem polskojęzycznego konta na X (Twitter). "
    "ZAWSZE pisz PO POLSKU. "
    "Pisz zwięźle — max 280 znaków. "
    "Styl: neutralny, wyważony, informacyjny. Bez emocji, bez dramatyzmu. "
    "Formatowanie: plain text. Bez hashtagów. Bez linków. Bez emoji. "
    "NIGDY nie przekraczaj 280 znaków."
)

X_INSTRUCTION = (
    "Napisz tweet PO POLSKU na podstawie tego tekstu. Max 280 znaków. "
    "Krótko, mocno, z 1-2 emoji. Oto tekst:\n\n"
)

X_GROK_INSTRUCTION = (
    "Napisz tweet PO POLSKU w stylu Groka — sarkastyczny, ironiczny, cyniczny. "
    "Czarny humor, bez cenzury, bez PC. Emoji sarkastycznie (🤡🫠💀😏). "
    "Max 280 znaków. Oto tekst:\n\n"
)

X_SOFT_INSTRUCTION = (
    "Napisz ten tweet PO POLSKU od nowa — neutralny, wyważony, informacyjny. "
    "Bez emocji, bez sarkazmu, bez dramatyzmu. Suche fakty. "
    "Max 280 znaków. Oto tekst:\n\n"
)


def register_x_handlers(bot, userbot):
    """Register all X/Twitter-platform handlers on the bot."""

    @bot.on(events.CallbackQuery)
    async def on_x_button(event):
        sender = await event.get_sender()
        if sender.id != config.OWNER_ID:
            return

        msg_id = event.message_id
        data = event.data.decode()

        # ── Adopt for X ──

        if data == "adopt_x":
            post = pending_adoption.get(msg_id)
            if not post:
                post = await recover_adoption(bot, msg_id)
            if not post:
                return
            await event.answer("Przerabiam na X...")
            await show_loading(event, "Przerabiam na X...")
            print(f"[ADOPT_X] Przerabiam post z {post['source']}...")

            rewritten = await ask_claude(
                post["original_text"], post["source"], X_INSTRUCTION,
                system_prompt=X_SYSTEM_PROMPT,
            )
            print(f"[ADOPT_X] Gotowe.")

            sent = await send_preview(bot, userbot, post, rewritten, make_x_buttons(has_media=post.get("has_media", False)), download_media=post.get("has_media", False), reply_to=msg_id)

            pending_posts[sent.id] = track_post(pending_posts, {
                "text": rewritten,
                "original_text": post["original_text"],
                "source": post["source"],
                "messages": post["messages"],
                "has_media": post["has_media"],
                "cached_files": post.get("cached_files", []),
                "forwarded": post.get("forwarded", False),
                "edit_chain": ["adopt_x"],
                "platform": "x",
                "phase1_msg_id": msg_id,
            }, sent_id=sent.id)
            await restore_buttons(bot, msg_id, post)
            return

        # ── Retry X ──

        if data == "retry_x":
            post = pending_posts.get(msg_id)
            if not post or post.get("platform") != "x":
                return
            await event.answer("Retry X...")
            await show_loading(event, "Retry X...")
            print(f"[RETRY_X] Przerabiam post z {post['source']}...")

            rewritten = await ask_claude(
                post["original_text"], post["source"],
                "Napisz ten tweet ZUPEŁNIE OD NOWA — inny styl, inny kąt. Max 280 znaków. Oto tekst:\n\n" + post["original_text"],
                system_prompt=X_SYSTEM_PROMPT,
            )
            print(f"[RETRY_X] Gotowe.")

            anchor = post.get("phase1_msg_id")
            sent = await send_preview(bot, userbot, post, rewritten, make_x_buttons(has_media=post.get("has_media", False)), download_media=post.get("has_media", False), reply_to=anchor)

            post["text"] = rewritten
            post.setdefault("edit_chain", []).append("retry_x")
            del pending_posts[msg_id]
            pending_posts[sent.id] = track_post(pending_posts, post, sent_id=sent.id)

            try:
                await (await event.get_message()).delete()
            except Exception:
                pass
            return

        # ── Grok X ──

        if data == "grok_x":
            post = pending_posts.get(msg_id)
            if not post or post.get("platform") != "x":
                return
            await event.answer("Grok X 😈...")
            await show_loading(event, "Grok X 😈...")
            print(f"[GROK_X] Przerabiam post z {post['source']}...")

            rewritten = await ask_claude(
                post["original_text"], post["source"],
                X_GROK_INSTRUCTION + post["original_text"],
                system_prompt=X_SYSTEM_PROMPT,
            )
            print(f"[GROK_X] Gotowe.")

            anchor = post.get("phase1_msg_id")
            sent = await send_preview(bot, userbot, post, rewritten, make_x_buttons(has_media=post.get("has_media", False)), download_media=post.get("has_media", False), reply_to=anchor)

            post["text"] = rewritten
            post.setdefault("edit_chain", []).append("grok_x")
            del pending_posts[msg_id]
            pending_posts[sent.id] = track_post(pending_posts, post, sent_id=sent.id)

            try:
                await (await event.get_message()).delete()
            except Exception:
                pass
            return

        # ── Soft X ──

        if data == "soft_x":
            post = pending_posts.get(msg_id)
            if not post or post.get("platform") != "x":
                return
            await event.answer("Soft X 😇...")
            await show_loading(event, "Soft X 😇...")
            print(f"[SOFT_X] Przerabiam post z {post['source']}...")

            rewritten = await ask_claude(
                post["original_text"], post["source"],
                X_SOFT_INSTRUCTION + post["original_text"],
                system_prompt=X_SOFT_PROMPT,
            )
            print(f"[SOFT_X] Gotowe.")

            anchor = post.get("phase1_msg_id")
            sent = await send_preview(bot, userbot, post, rewritten, make_x_buttons(has_media=post.get("has_media", False)), download_media=post.get("has_media", False), reply_to=anchor)

            post["text"] = rewritten
            post.setdefault("edit_chain", []).append("soft_x")
            del pending_posts[msg_id]
            pending_posts[sent.id] = track_post(pending_posts, post, sent_id=sent.id)

            try:
                await (await event.get_message()).delete()
            except Exception:
                pass
            return

        # ── Source X — append source to tweet ──

        if data == "source_x":
            post = pending_posts.get(msg_id)
            if not post or post.get("platform") != "x":
                return
            print(f"[SOURCE_X] msg_id={msg_id} → dodaję źródło z {post['source']}")
            source = post.get("source", "")
            if source and not post["text"].endswith(source):
                post["text"] = post["text"].rstrip() + f"\n\n{source}"
            await event.answer("Dodano źródło")
            try:
                original_msg = await event.get_message()
                await original_msg.edit(post["text"], buttons=make_x_buttons(has_media=post.get("has_media", False)))
            except Exception:
                pass
            return

        # ── Verify X — check against community standards + char limit ──

        if data == "verify_x":
            post = pending_posts.get(msg_id)
            if not post or post.get("platform") != "x":
                return
            await event.answer("Weryfikuję...")
            await show_loading(event, "Weryfikuję zgodność...")
            print(f"[VERIFY_X] Sprawdzam post z {post['source']}...")

            char_count = len(post["text"])
            char_note = f"DŁUGOŚĆ: {char_count}/280 znaków — {'OK' if char_count <= 280 else 'PRZEKROCZONO LIMIT!'}\n"

            verify_instruction = (
                "Oceń poniższy tweet pod kątem zgodności ze standardami platformy X/Twitter.\n\n"
                "STANDARDY:\n" + X_STANDARD + "\n\n"
                "POST DO OCENY:\n" + post["text"] + "\n\n"
                + char_note +
                "Odpowiedz TYLKO w jednej linii w formacie:\n"
                "WYNIK/RYZYKO|REGUŁY|KOMENTARZ\n"
                "Przykład: 15/SAFE|BRAK|Tweet informacyjny, brak naruszeń.\n"
                "WYNIK to liczba 0-100. RYZYKO: SAFE/LOW/MEDIUM/HIGH. Pisz PO POLSKU."
            )
            result = await ask_claude(
                post["text"], post["source"], verify_instruction,
                system_prompt="Jesteś ekspertem od moderacji treści na X/Twitter. Oceniasz tweety pod kątem zgodności ze standardami. Odpowiadaj JEDNĄ LINIĄ w podanym formacie.",
            )
            print(f"[VERIFY_X] Gotowe: {result[:80]}")

            score_match = re.search(r'(\d+)\s*/\s*(SAFE|LOW|MEDIUM|HIGH)', result)
            if score_match:
                score = score_match.group(1)
                risk = score_match.group(2)
                char_warn = "⚠️" if char_count > 280 else ""
                verify_label = f"✅ Verify({score}/{risk} {char_count}zn){char_warn}"
            else:
                verify_label = f"✅ Verify(? {char_count}zn)"

            buttons = [
                [Button.inline("Publikuj X", b"pub_x"), Button.inline("Odrzuć", b"pub_no")],
                [Button.inline("Retry", b"retry_x"), Button.inline("Grok 😈", b"grok_x"), Button.inline("😇", b"soft_x")],
                [Button.inline("🔗 Źródło", b"source_x"), Button.inline(verify_label, b"verify_x_detail")],
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

        if data == "verify_x_detail":
            post = pending_posts.get(msg_id)
            if not post:
                return
            detail = post.get("_verify_result", "Brak wyniku")
            await event.answer(detail[:200], alert=True)
            return

        # ── Publish X ──

        if data == "pub_x":
            post = pending_posts.get(msg_id)
            if not post or post.get("platform") != "x":
                return
            await event.answer("TODO: publikacja na X")
            print(f"[PUB_X] Tekst do opublikowania: {post['text'][:100]}")
            original_msg = await event.get_message()
            await original_msg.edit(original_msg.text + "\n\n✅ GOTOWE DO X", buttons=make_after_publish_buttons("x"))
            post["platform"] = "x_done"
            return

        # ── Continue to Telegram after X ──

        if data == "continue_t":
            post = pending_posts.get(msg_id)
            if not post:
                await event.answer("Post wygasł")
                return
            await event.answer("Przerabiam na Telegram...")
            await show_loading(event, "Przerabiam na Telegram...")
            print(f"[CONTINUE_T] Przerabiam post z {post['source']} na Telegram...")

            rewritten = await ask_claude(post["original_text"], post["source"], INITIAL_INSTRUCTION)
            print(f"[CONTINUE_T] Gotowe.")

            anchor = post.get("phase1_msg_id")
            sent = await send_preview(bot, userbot, post, rewritten, make_edit_buttons(has_media=post.get("has_media")), download_media=True, reply_to=anchor)

            new_post = {
                "text": rewritten,
                "original_text": post["original_text"],
                "source": post["source"],
                "messages": post["messages"],
                "has_media": post["has_media"],
                "cached_files": post.get("cached_files", []),
                "forwarded": post.get("forwarded", False),
                "edit_chain": ["adopt"],
                "platform": "telegram",
                "phase1_msg_id": anchor,
            }
            del pending_posts[msg_id]
            pending_posts[sent.id] = track_post(pending_posts, new_post, sent_id=sent.id)

            try:
                await (await event.get_message()).delete()
            except Exception:
                pass
            return
