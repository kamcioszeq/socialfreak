import asyncio
import os
import time
from telethon import TelegramClient, events
import config

from shared import (
    pending_adoption, pending_posts, source_entities, last_seen_ids, forward_buffer,
    reel_sessions,
    MEDIA_DIR, REELS_DIR, POLL_INTERVAL, CLEANUP_INTERVAL, ADOPTION_TTL, POST_TTL,
    ask_claude, ask_claude_vision, INITIAL_INSTRUCTION,
    make_adopt_buttons, make_platform_buttons, make_edit_buttons,
    make_preview, cleanup_cached_files, track_post,
    send_preview, show_loading, recover_adoption, ensure_cached_files,
    add_reel_media, get_unused_reels, mark_reels_used, get_expired_reels, delete_reels,
)


# ─── Main ────────────────────────────────────────────────────

async def main():
    userbot = TelegramClient("session/userbot", config.API_ID, config.API_HASH)
    bot = TelegramClient("session/bot", config.API_ID, config.API_HASH)

    # ─── Polling: check for new posts ────────────────────────

    async def poll_channels():
        for ch_id, entity in list(source_entities.items()):
            username = f"@{entity.username}" if getattr(entity, "username", None) else str(ch_id)
            last_id = last_seen_ids.get(ch_id, 0)

            new_messages = []
            async for msg in userbot.iter_messages(entity, min_id=last_id, limit=50):
                new_messages.append(msg)

            if not new_messages:
                continue

            max_id = max(m.id for m in new_messages)
            last_seen_ids[ch_id] = max_id

            groups = {}
            singles = []
            for msg in new_messages:
                if msg.grouped_id:
                    groups.setdefault(msg.grouped_id, []).append(msg)
                else:
                    singles.append(msg)

            for gid, msgs in groups.items():
                msgs.sort(key=lambda m: m.id)
                text = next((m.text for m in msgs if m.text), "(brak tekstu)")
                has_media = any(m.photo or m.video for m in msgs)

                print(f"[NEW] Album ({len(msgs)} media) z {username}")
                preview, preview_ents = make_preview(f"Nowy post z {username}:", text)
                adopt_post = {
                    "original_text": text,
                    "source": username,
                    "messages": msgs,
                    "has_media": has_media,
                    "cached_files": [],
                }
                sent = await send_preview(bot, userbot, adopt_post, preview, make_adopt_buttons(has_media=has_media), download_media=has_media, formatting_entities=preview_ents)
                pending_adoption[sent.id] = track_post(pending_adoption, adopt_post, sent_id=sent.id)

            for msg in singles:
                text = msg.text or "(brak tekstu)"
                has_media = bool(msg.photo or msg.video)

                print(f"[NEW] Post z {username} (media: {has_media})")
                preview, preview_ents = make_preview(f"Nowy post z {username}:", text)
                adopt_post = {
                    "original_text": text,
                    "source": username,
                    "messages": [msg],
                    "has_media": has_media,
                    "cached_files": [],
                }
                sent = await send_preview(bot, userbot, adopt_post, preview, make_adopt_buttons(has_media=has_media), download_media=has_media, formatting_entities=preview_ents)
                pending_adoption[sent.id] = track_post(pending_adoption, adopt_post, sent_id=sent.id)

    async def poll_loop():
        while True:
            try:
                await poll_channels()
            except Exception as e:
                print(f"[POLL] Błąd: {e}")
            await asyncio.sleep(POLL_INTERVAL)

    async def cleanup_loop():
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL)
            now = time.time()
            expired_adopt = [k for k, v in pending_adoption.items() if now - v.get("created_at", now) > ADOPTION_TTL]
            for k in expired_adopt:
                cleanup_cached_files(pending_adoption[k])
                del pending_adoption[k]
            expired_posts = [k for k, v in pending_posts.items() if now - v.get("created_at", now) > POST_TTL]
            for k in expired_posts:
                cleanup_cached_files(pending_posts[k])
                del pending_posts[k]
            if expired_adopt or expired_posts:
                print(f"[CLEANUP] Usunięto {len(expired_adopt)} adoption + {len(expired_posts)} posts")

            expired_reels = get_expired_reels()
            if expired_reels:
                from telethon import Button
                n = len(expired_reels)
                print(f"[CLEANUP] Znaleziono {n} reels starszych niż 30 dni")
                await bot.send_message(
                    config.OWNER_ID,
                    f"🗑 Znaleziono <b>{n}</b> mediów do rolek starszych niż 30 dni.\nUsunąć?",
                    buttons=[
                        [Button.inline("🗑 Usuń stare", b"reels_delete_expired"),
                         Button.inline("📌 Zachowaj", b"reels_keep")],
                    ],
                    parse_mode="html",
                )

    # ─── Bot: /check command ─────────────────────────────────

    @bot.on(events.NewMessage(pattern="/check"))
    async def on_check(event):
        if event.sender_id != config.OWNER_ID:
            return
        sender = await event.get_sender()
        print(f"[CMD] /check — {sender.username or sender.first_name} ({sender.id})")
        await event.reply("Sprawdzam kanały...")
        before = len(pending_adoption)
        await poll_channels()
        after = len(pending_adoption)
        new_count = after - before
        await event.reply(f"Znaleziono {new_count} nowych postów.")

    # ─── Bot: /ip command ────────────────────────────────────

    @bot.on(events.NewMessage(pattern="/ip"))
    async def on_ip(event):
        if event.sender_id != config.OWNER_ID:
            return
        sender = await event.get_sender()
        print(f"[CMD] /ip — {sender.username or sender.first_name} ({sender.id})")
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception as e:
            local_ip = f"Błąd: {e}"
        await event.reply(f"Local IP: `{local_ip}`")

    # ─── Bot: /osdetails command ─────────────────────────────

    @bot.on(events.NewMessage(pattern="/osdetails"))
    async def on_osdetails(event):
        if event.sender_id != config.OWNER_ID:
            return
        sender = await event.get_sender()
        print(f"[CMD] /osdetails — {sender.username or sender.first_name} ({sender.id})")
        import socket, struct

        def read_file(path):
            try:
                with open(path) as f:
                    return f.read().strip()
            except Exception:
                return "n/a"

        def parse_route():
            iface, gateway = "n/a", "n/a"
            try:
                with open("/proc/net/route") as f:
                    for line in f.readlines()[1:]:
                        fields = line.strip().split()
                        if fields[1] == "00000000" and fields[7] == "00000000":
                            iface = fields[0]
                            gw_int = int(fields[2], 16)
                            gateway = socket.inet_ntoa(struct.pack("<I", gw_int))
                            break
            except Exception:
                pass
            return iface, gateway

        def get_cidr(iface, local_ip):
            try:
                with open("/proc/net/fib_trie") as f:
                    content = f.read()
                mask_path = f"/sys/class/net/{iface}/operstate"
                open(mask_path)
                import fcntl, struct as st
                SIOCGIFNETMASK = 0x891b
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                netmask = socket.inet_ntoa(fcntl.ioctl(
                    s.fileno(), SIOCGIFNETMASK,
                    st.pack("256s", iface[:15].encode())
                )[20:24])
                s.close()
                bits = sum(bin(int(x)).count("1") for x in netmask.split("."))
                return f"{local_ip}/{bits}"
            except Exception:
                return "n/a"

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            local_ip = "n/a"

        iface, gateway = parse_route()
        mac      = read_file(f"/sys/class/net/{iface}/address")
        cidr     = get_cidr(iface, local_ip)
        hostname = read_file("/etc/hostname")
        dns      = " ".join(
            line.split()[1] for line in read_file("/etc/resolv.conf").splitlines()
            if line.startswith("nameserver")
        )

        msg = (
            f"<b>Network details for static IP setup</b>\n\n"
            f"<b>Hostname:</b> <code>{hostname}</code>\n"
            f"<b>Interface:</b> <code>{iface}</code>\n"
            f"<b>MAC:</b> <code>{mac}</code>\n"
            f"<b>IP:</b> <code>{local_ip}</code>\n"
            f"<b>CIDR:</b> <code>{cidr}</code>\n"
            f"<b>Gateway:</b> <code>{gateway}</code>\n"
            f"<b>DNS:</b> <code>{dns}</code>"
        )
        await event.reply(msg, parse_mode="html")

    # ─── Bot: direct photo → AI reads & generates post ─────

    @bot.on(events.NewMessage(func=lambda e: e.is_private and not e.forward and (e.photo or e.video) and not e.text.startswith("/")))
    async def on_direct_photo(event):
        if event.sender_id != config.OWNER_ID:
            return

        sender = await event.get_sender()
        print(f"[CMD] direct photo — {sender.username or sender.first_name} ({sender.id})")
        await event.reply("Czytam obraz...")

        path = await bot.download_media(event.message, file=MEDIA_DIR)
        if not path:
            await event.reply("Nie udało się pobrać obrazu.")
            return

        extracted = await ask_claude_vision(path, context=event.text or "")
        print(f"[PHOTO] Odczytano: {extracted[:100]}...")

        caption = event.text or ""

        word_count = len(extracted.split())
        if word_count <= 10:
            await event.reply(f"📷 {extracted}")
            os.remove(path)
            return

        await event.reply(f"Odczytano tekst, generuję post...")
        source = "screenshot"
        if caption:
            extracted = f"{caption}\n\n{extracted}"

        rewritten = await ask_claude(extracted, source, INITIAL_INSTRUCTION)
        print(f"[PHOTO] Post wygenerowany.")

        sent = await bot.send_message(
            config.OWNER_ID, rewritten,
            buttons=make_edit_buttons(has_media=True),
            parse_mode='html',
        )

        pending_posts[sent.id] = track_post(pending_posts, {
            "text": rewritten,
            "original_text": extracted,
            "source": source,
            "messages": [event.message],
            "has_media": True,
            "cached_files": [path],
            "platform": "telegram",
            "forwarded": True,
        }, sent_id=sent.id)

    # ─── Bot: forwarded messages ────────────────────────────

    FORWARD_ALBUM_DELAY = 2.0

    def _get_forward_source(fwd):
        if fwd.chat and getattr(fwd.chat, "username", None):
            return f"@{fwd.chat.username}"
        if fwd.chat and getattr(fwd.chat, "title", None):
            return fwd.chat.title
        if fwd.sender and getattr(fwd.sender, "username", None):
            return f"@{fwd.sender.username}"
        return "forwarded"

    async def _flush_forward_album(grouped_id):
        buf = forward_buffer.pop(grouped_id, None)
        if not buf:
            return
        msgs = sorted(buf["messages"], key=lambda m: m.id)
        source = buf["source"]
        text = next((m.text for m in msgs if m.text), "(brak tekstu)")
        has_media = any(m.photo or m.video for m in msgs)

        media_note = f" ({len(msgs)} zdjęć/wideo)" if has_media and len(msgs) > 1 else ""
        preview, preview_ents = make_preview(f"Przekazany post z {source}:{media_note}", text)
        adopt_post = {
            "original_text": text,
            "source": source,
            "messages": msgs,
            "has_media": has_media,
            "cached_files": [],
            "forwarded": True,
        }
        sent = await send_preview(bot, userbot, adopt_post, preview, make_adopt_buttons(has_media=has_media), download_media=has_media, formatting_entities=preview_ents)
        pending_adoption[sent.id] = track_post(pending_adoption, adopt_post, sent_id=sent.id)
        print(f"[FORWARD] Album z {source} ({len(msgs)} wiadomości, media: {has_media})")

    @bot.on(events.NewMessage(func=lambda e: e.is_private and e.forward))
    async def on_forward(event):
        if event.sender_id != config.OWNER_ID:
            return

        fwd = event.forward
        source = _get_forward_source(fwd)
        grouped_id = event.message.grouped_id

        if grouped_id:
            if grouped_id in forward_buffer:
                forward_buffer[grouped_id]["messages"].append(event.message)
                forward_buffer[grouped_id]["timer"].cancel()
            else:
                forward_buffer[grouped_id] = {
                    "messages": [event.message],
                    "source": source,
                }
            forward_buffer[grouped_id]["timer"] = asyncio.get_event_loop().call_later(
                FORWARD_ALBUM_DELAY,
                lambda gid=grouped_id: asyncio.ensure_future(_flush_forward_album(gid)),
            )
            print(f"[FORWARD] Buforuję część albumu {grouped_id} z {source}")
            return

        text = event.text or "(brak tekstu)"
        has_media = bool(event.photo or event.video)

        preview, preview_ents = make_preview(f"Przekazany post z {source}:", text)
        adopt_post = {
            "original_text": text,
            "source": source,
            "messages": [event.message],
            "has_media": has_media,
            "cached_files": [],
            "forwarded": True,
        }
        sent = await send_preview(bot, userbot, adopt_post, preview, make_adopt_buttons(has_media=has_media), download_media=has_media, formatting_entities=preview_ents)
        pending_adoption[sent.id] = track_post(pending_adoption, adopt_post, sent_id=sent.id)
        print(f"[FORWARD] Post z {source} (media: {has_media})")

    # ─── Bot: /lastone command ───────────────────────────────

    @bot.on(events.NewMessage(pattern="/lastone"))
    async def on_lastone(event):
        if event.sender_id != config.OWNER_ID:
            return
        sender = await event.get_sender()
        print(f"[CMD] /lastone — {sender.username or sender.first_name} ({sender.id})")
        if not source_entities:
            await event.reply("Brak kanałów do monitorowania.")
            return

        entity = list(source_entities.values())[0]
        username = f"@{entity.username}" if getattr(entity, "username", None) else str(entity.id)
        await event.reply(f"Pobieram ostatni post z {username}...")

        recent = []
        async for msg in userbot.iter_messages(entity, limit=5):
            recent.append(msg)

        if not recent:
            await event.reply("Brak postów na kanale.")
            return

        last_msg = recent[0]
        if last_msg.grouped_id:
            album_msgs = [m for m in recent if m.grouped_id == last_msg.grouped_id]
            album_msgs.sort(key=lambda m: m.id)
            messages = album_msgs
        else:
            messages = [last_msg]

        text = next((m.text for m in messages if m.text), "(brak tekstu)")
        has_media = any(m.photo or m.video for m in messages)

        preview, preview_ents = make_preview(f"Ostatni post z {username}:", text)
        adopt_post = {
            "original_text": text,
            "source": username,
            "messages": messages,
            "has_media": has_media,
            "cached_files": [],
        }
        sent = await send_preview(bot, userbot, adopt_post, preview, make_adopt_buttons(has_media=has_media), download_media=has_media, formatting_entities=preview_ents)
        pending_adoption[sent.id] = track_post(pending_adoption, adopt_post, sent_id=sent.id)
        print(f"[LASTONE] Wysłano ostatni post z {username} ({len(messages)} wiadomości, media: {has_media})")

    # ─── Bot: /rolka command ────────────────────────────────

    @bot.on(events.NewMessage(pattern="/rolka"))
    async def on_rolka(event):
        if event.sender_id != config.OWNER_ID:
            return
        sender = await event.get_sender()
        print(f"[CMD] /rolka — {sender.username or sender.first_name} ({sender.id})")

        unused = get_unused_reels()
        if not unused:
            await event.reply("Brak mediów do rolek. Użyj 🍣 aby zapisać media z postów.")
            return

        from telethon import Button
        from datetime import datetime
        session = {"items": unused, "index": 0, "selected": set()}
        reel_sessions[config.OWNER_ID] = session

        item = unused[0]
        ts = datetime.fromtimestamp(item["timestamp"]).strftime("%d.%m %H:%M")
        caption = f"🎬 Rolka 1/{len(unused)}\n📍 {item['source']}\n🕐 {ts}"

        sent = await bot.send_file(
            config.OWNER_ID, item["file_path"], caption=caption,
            buttons=[
                [Button.inline("✅ Dodaj", b"reel_add"), Button.inline("⏭ Pomiń", b"reel_skip")],
                [Button.inline("📤 Wyślij", b"reel_send"), Button.inline("❌ Odrzuć", b"reel_cancel")],
            ],
        )
        session["msg_id"] = sent.id
        print(f"[ROLKA] Start: {len(unused)} mediów dostępnych")

    # ─── Bot: handle Phase 1 buttons (shared) ─────────────────

    @bot.on(events.CallbackQuery)
    async def on_button(event):
        sender = await event.get_sender()
        if sender.id != config.OWNER_ID:
            await event.answer("Brak dostępu")
            return

        msg_id = event.message_id
        data = event.data.decode()
        print(f"[BTN] {data} — {sender.username or sender.first_name} ({sender.id})")

        # ── Reel Tinder-flow handlers ──

        if data in ("reel_add", "reel_skip", "reel_cancel", "reel_send", "reel_confirm", "reel_back"):
            from telethon import Button
            from datetime import datetime
            session = reel_sessions.get(config.OWNER_ID)

            if data == "reel_cancel":
                reel_sessions.pop(config.OWNER_ID, None)
                await event.answer("Anulowano")
                try:
                    await event.delete()
                except Exception:
                    pass
                print("[ROLKA] Anulowano proces")
                return

            if not session:
                await event.answer("Brak aktywnej sesji /rolka")
                return

            if data == "reel_add":
                item = session["items"][session["index"]]
                session["selected"].add(item["id"])
                await event.answer(f"Dodano ✓ ({len(session['selected'])} wybranych)")
                session["index"] += 1
                print(f"[ROLKA] Dodano {item['id']} z {item['source']}")

            elif data == "reel_skip":
                await event.answer("Pominięto")
                session["index"] += 1

            elif data == "reel_send":
                selected = [r for r in session["items"] if r["id"] in session["selected"]]
                if not selected:
                    await event.answer("Nie wybrano żadnych mediów!", alert=True)
                    return

                lines = ["📋 <b>Wybrane media do rolki:</b>\n"]
                for i, r in enumerate(selected, 1):
                    ts = datetime.fromtimestamp(r["timestamp"]).strftime("%d.%m %H:%M")
                    lines.append(f"{i}. {r['source']} — {ts}")
                lines.append(f"\n<b>Łącznie: {len(selected)}</b>")

                try:
                    msg = await event.get_message()
                    await msg.edit(
                        "\n".join(lines),
                        buttons=[
                            [Button.inline("✅ Akceptuj", b"reel_confirm"), Button.inline("← Wróć", b"reel_back")],
                            [Button.inline("❌ Anuluj", b"reel_cancel")],
                        ],
                        parse_mode="html",
                    )
                except Exception:
                    pass
                await event.answer(f"{len(selected)} mediów do wysłania")
                return

            elif data == "reel_back":
                if session["index"] > 0:
                    session["index"] = max(0, session["index"] - 1)
                # Fall through to show current item

            elif data == "reel_confirm":
                selected_ids = session["selected"]
                selected = [r for r in session["items"] if r["id"] in selected_ids]
                if not selected:
                    await event.answer("Brak wybranych mediów")
                    return

                files = [r["file_path"] for r in selected if os.path.exists(r["file_path"])]
                if not files:
                    await event.answer("Brak plików do wysłania")
                    return

                await event.answer("Publikuję relacje na FB...")
                from facebook_handlers import publish_story_to_facebook

                published = 0
                errors = []
                for fp in files:
                    ok, result = await publish_story_to_facebook(fp)
                    if ok:
                        published += 1
                        print(f"[ROLKA] Relacja opublikowana: {fp}")
                    else:
                        errors.append(result)
                        print(f"[ROLKA] Błąd relacji: {result}")

                mark_reels_used(selected_ids)
                print(f"[ROLKA] Opublikowano {published}/{len(files)} relacji na FB, oznaczono jako used")

                status = f"✅ Opublikowano {published}/{len(files)} relacji na FB"
                if errors:
                    status += f"\n⚠️ Błędy: {'; '.join(errors[:3])}"
                await bot.send_message(config.OWNER_ID, status)

                reel_sessions.pop(config.OWNER_ID, None)
                try:
                    await event.delete()
                except Exception:
                    pass
                return

            if data in ("reel_add", "reel_skip", "reel_back"):
                items = session["items"]
                idx = session["index"]

                if idx >= len(items):
                    selected = [r for r in items if r["id"] in session["selected"]]
                    if not selected:
                        reel_sessions.pop(config.OWNER_ID, None)
                        await event.answer("Koniec mediów, nic nie wybrano")
                        try:
                            await event.delete()
                        except Exception:
                            pass
                        return
                    lines = ["📋 <b>Koniec mediów. Wybrane:</b>\n"]
                    for i, r in enumerate(selected, 1):
                        ts = datetime.fromtimestamp(r["timestamp"]).strftime("%d.%m %H:%M")
                        lines.append(f"{i}. {r['source']} — {ts}")
                    lines.append(f"\n<b>Łącznie: {len(selected)}</b>")
                    try:
                        msg = await event.get_message()
                        await msg.edit(
                            "\n".join(lines),
                            buttons=[
                                [Button.inline("✅ Akceptuj", b"reel_confirm"), Button.inline("← Wróć", b"reel_back")],
                                [Button.inline("❌ Anuluj", b"reel_cancel")],
                            ],
                            parse_mode="html",
                        )
                    except Exception:
                        pass
                    return

                item = items[idx]
                ts = datetime.fromtimestamp(item["timestamp"]).strftime("%d.%m %H:%M")
                caption = f"🎬 Rolka {idx + 1}/{len(items)} ({len(session['selected'])} wybranych)\n📍 {item['source']}\n🕐 {ts}"

                reel_buttons = [
                    [Button.inline("✅ Dodaj", b"reel_add"), Button.inline("⏭ Pomiń", b"reel_skip")],
                    [Button.inline("📤 Wyślij", b"reel_send"), Button.inline("❌ Odrzuć", b"reel_cancel")],
                ]
                try:
                    await event.delete()
                except Exception:
                    pass
                sent = await bot.send_file(
                    config.OWNER_ID, item["file_path"], caption=caption,
                    buttons=reel_buttons,
                )
                session["msg_id"] = sent.id
            return

        if data == "reels_delete_expired":
            expired = get_expired_reels()
            reel_ids = {r["id"] for r in expired}
            delete_reels(reel_ids)
            await event.answer(f"Usunięto {len(reel_ids)} starych mediów ✓")
            print(f"[CLEANUP] Usunięto {len(reel_ids)} expired reels")
            try:
                await event.delete()
            except Exception:
                pass
            return

        if data == "reels_keep":
            await event.answer("Zachowano")
            try:
                await event.delete()
            except Exception:
                pass
            return

        if data == "_noop":
            await event.answer()
            return

        if data == "choose_platform":
            post = pending_adoption.get(msg_id)
            if not post:
                post = await recover_adoption(bot, msg_id)
            if not post:
                await event.answer("Post wygasł")
                return
            await event.answer("Wybieram platformę...")
            print(f"[CHOOSE_PLATFORM] msg_id={msg_id} → post z {post['source']}")
            try:
                original_msg = await event.get_message()
                await original_msg.edit(original_msg.text, buttons=make_platform_buttons(has_media=post.get("has_media", False)))
            except Exception:
                pass
            return

        if data == "back_adopt":
            post = pending_adoption.get(msg_id)
            if not post:
                post = await recover_adoption(bot, msg_id)
            if not post:
                await event.answer("Post wygasł")
                return
            await event.answer("Wracam...")
            print(f"[BACK_ADOPT] msg_id={msg_id} → post z {post['source']}")
            try:
                original_msg = await event.get_message()
                await original_msg.edit(original_msg.text, buttons=make_adopt_buttons(has_media=post.get("has_media", False)))
            except Exception:
                pass
            return

        if data == "photo_read":
            post = pending_adoption.get(msg_id)
            if not post:
                post = await recover_adoption(bot, msg_id)
            if not post:
                await event.answer("Post wygasł")
                return
            if not post.get("has_media"):
                await event.answer("Brak zdjęcia w tym poście")
                return
            await event.answer("Czytam zdjęcie...")
            await show_loading(event, "Czytam zdjęcie...")
            print(f"[PHOTO_READ] Interpretuję zdjęcie z {post['source']}...")

            download_client = bot if post.get("forwarded") else userbot
            photo_msg = next((m for m in post["messages"] if m.photo), None)
            if not photo_msg:
                await event.answer("Nie znaleziono zdjęcia")
                return

            path = await download_client.download_media(photo_msg, file=MEDIA_DIR)
            if not path:
                await event.answer("Nie udało się pobrać zdjęcia")
                return

            try:
                description = await ask_claude_vision(path, context=post.get("original_text", ""))
                print(f"[PHOTO_READ] Gotowe.")

                preview, preview_ents = make_preview(f"📷 Zdjęcie z {post['source']}:", description)
                await bot.send_message(
                    config.OWNER_ID, preview, formatting_entities=preview_ents,
                )
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
            return

        if data == "dl_media":
            post = pending_adoption.get(msg_id) or pending_posts.get(msg_id)
            if not post:
                post = await recover_adoption(bot, msg_id)
            if not post or not post.get("has_media"):
                await event.answer("Brak mediów")
                return

            download_client = bot if post.get("forwarded") else userbot
            files = await ensure_cached_files(download_client, post)
            if not files:
                await event.answer("Nie udało się pobrać mediów", alert=True)
                return

            await event.answer("Wysyłam media...")
            for f in files:
                await bot.send_file(config.OWNER_ID, f)
            print(f"[DL_MEDIA] Wysłano {len(files)} plików z {post.get('source', '?')}")
            return

        if data == "reject":
            if msg_id in pending_adoption:
                print(f"[REJECT] msg_id={msg_id} → post z {pending_adoption[msg_id].get('source', '?')}")
                cleanup_cached_files(pending_adoption[msg_id])
                del pending_adoption[msg_id]
            await event.answer("Odrzucono")
            try:
                await event.delete()
            except Exception:
                pass
            return

        if data == "save_reel":
            post = pending_adoption.get(msg_id) or pending_posts.get(msg_id)
            if not post:
                post = await recover_adoption(bot, msg_id)
            if not post or not post.get("has_media"):
                await event.answer("Brak mediów do zapisania")
                return

            download_client = bot if post.get("forwarded") else userbot
            files = await ensure_cached_files(download_client, post)
            if not files:
                await event.answer("Nie udało się pobrać mediów", alert=True)
                return

            source = post.get("source", "unknown")
            saved = 0
            dupes = 0
            for f in files:
                entry = add_reel_media(f, source)
                if entry:
                    saved += 1
                else:
                    dupes += 1
            if saved == 0 and dupes > 0:
                await event.answer("Już zapisano te media do rolek", alert=True)
                print(f"[SAVE_REEL] Duplikat z {source} — pominięto")
                return
            print(f"[SAVE_REEL] Zapisano {saved} mediów z {source} do rolek" + (f" ({dupes} duplikatów)" if dupes else ""))

            from telethon import Button
            try:
                msg = await event.get_message()
                new_buttons = []
                for row in msg.buttons or []:
                    new_row = []
                    for btn in row:
                        if btn.data == b"save_reel":
                            new_row.append(Button.inline("🍣 ✓", b"_noop"))
                        else:
                            new_row.append(Button.inline(btn.text, btn.data))
                    new_buttons.append(new_row)
                await msg.edit(buttons=new_buttons)
            except Exception:
                pass
            await event.answer(f"Zapisano {saved} mediów do rolek ✓")
            return

        if data == "pub_no":
            post = pending_posts.pop(msg_id, None)
            if post:
                print(f"[PUB_NO] msg_id={msg_id} → odrzucam post z {post.get('source', '?')} (platforma: {post.get('platform', '?')})")
                cleanup_cached_files(post)
            else:
                print(f"[PUB_NO] msg_id={msg_id} → post nie znaleziony, usuwam wiadomość")
            await event.answer("Odrzucono")
            try:
                await event.delete()
            except Exception:
                pass
            return

    # ─── Register platform handlers ──────────────────────────

    from telegram_handlers import register_telegram_handlers
    from x_handlers import register_x_handlers
    from facebook_handlers import register_facebook_handlers

    register_telegram_handlers(bot, userbot)
    register_x_handlers(bot, userbot)
    register_facebook_handlers(bot, userbot)

    # ─── Deploy helpers ──────────────────────────────────────

    DEPLOY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".last_deploy")

    def get_git_info():
        try:
            import subprocess
            def git(*args):
                return subprocess.check_output(["git"] + list(args), cwd=os.path.dirname(os.path.abspath(__file__))).decode().strip()
            return {
                "hash": git("rev-parse", "--short", "HEAD"),
                "full_hash": git("rev-parse", "HEAD"),
                "message": git("log", "-1", "--pretty=%s"),
                "author": git("log", "-1", "--pretty=%an"),
                "date": git("log", "-1", "--pretty=%ci"),
                "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            }
        except Exception:
            return {}

    def check_new_deploy(info):
        current = info.get("hash")
        try:
            with open(DEPLOY_FILE) as f:
                last = f.read().strip()
        except FileNotFoundError:
            last = None
        if current and current != last:
            try:
                with open(DEPLOY_FILE, "w") as f:
                    f.write(current)
            except Exception:
                pass
            return True
        return False

    START_TIME = time.time()

    # ─── Bot: /status command ────────────────────────────────

    @bot.on(events.NewMessage(pattern="/status"))
    async def on_status(event):
        if event.sender_id != config.OWNER_ID:
            return
        info = get_git_info()
        uptime_s = int(time.time() - START_TIME)
        h, rem = divmod(uptime_s, 3600)
        m, s = divmod(rem, 60)
        uptime_str = f"{h}h {m}m {s}s"

        lines = ["<b>Status aplikacji</b>\n"]
        lines.append(f"⏱ <b>Uptime:</b> {uptime_str}")
        lines.append(f"📋 <b>Kanały:</b> {len(source_entities)}")
        lines.append(f"📥 <b>Pending adoption:</b> {len(pending_adoption)}")
        lines.append(f"📝 <b>Pending posts:</b> {len(pending_posts)}")
        if info:
            lines.append("")
            lines.append(f"🔖 <b>Branch:</b> <code>{info.get('branch', 'n/a')}</code>")
            lines.append(f"🔗 <b>Commit:</b> <code>{info.get('hash', 'n/a')}</code>")
            lines.append(f"💬 <b>Message:</b> {info.get('message', 'n/a')}")
            lines.append(f"👤 <b>Author:</b> {info.get('author', 'n/a')}")
            lines.append(f"📅 <b>Date:</b> {info.get('date', 'n/a')}")
        await event.reply("\n".join(lines), parse_mode="html")

    # ─── Start ───────────────────────────────────────────────

    print("Uruchamiam userbot + bot...")
    await userbot.start()
    await bot.start(bot_token=config.BOT_TOKEN)

    # Web panel (same process, separate thread)
    try:
        from web_api import app as web_app
        from web_api import set_bot_context
        import threading
        import uvicorn
        set_bot_context(asyncio.get_event_loop(), bot, userbot)
        def run_web():
            uvicorn.run(
                web_app,
                host=config.WEB_HOST,
                port=config.WEB_PORT,
                log_level="warning",
            )
        t = threading.Thread(target=run_web, daemon=True)
        t.start()
        print(f"Web API: http://{config.WEB_HOST}:{config.WEB_PORT}  |  Web UI: http://social:5173")
    except Exception as e:
        print(f"[WEB] Nie uruchomiono panelu: {e}")

    git_info = get_git_info()
    await bot.send_message(config.OWNER_ID, "🚀 <b>Deployment started</b> — inicjalizuję...", parse_mode="html")

    if check_new_deploy(git_info):
        commit = git_info.get("hash", "?")
        msg = git_info.get("message", "")
        await bot.send_message(
            config.OWNER_ID,
            f"🆕 <b>New code deployed</b>\n<code>{commit}</code> — {msg}",
            parse_mode="html",
        )

    for ch in config.SOURCE_CHANNELS:
        try:
            entity = await userbot.get_entity(ch)
            source_entities[entity.id] = entity
            async for msg in userbot.iter_messages(entity, limit=1):
                last_seen_ids[entity.id] = msg.id
                print(f"  Monitoring: {ch} (id: {entity.id}, last_msg: {msg.id})")
                break
        except Exception as e:
            print(f"  Could not resolve {ch}: {e}")

    asyncio.create_task(poll_loop())
    asyncio.create_task(cleanup_loop())

    # Start scheduler loop for scheduled publications
    from scheduler import run_scheduler_loop
    asyncio.create_task(run_scheduler_loop(bot, userbot))

    # Start RSS feed poll loop
    from rss_feeds import run_rss_poll_loop
    asyncio.create_task(run_rss_poll_loop())

    print(f"Polling co {POLL_INTERVAL}s. Cleanup co {CLEANUP_INTERVAL}s (TTL: {POST_TTL}s).")
    print("Czekam na posty...")

    commit = git_info.get("hash", "")
    commit_str = f" | <code>{commit}</code>" if commit else ""
    await bot.send_message(
        config.OWNER_ID,
        f"✅ <b>App running</b> — monitoring {len(source_entities)} kanałów{commit_str}",
        parse_mode="html",
    )
    try:
        await asyncio.Event().wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        print("Zatrzymano.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
