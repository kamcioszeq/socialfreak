from telethon import events
import config
from shared import (
    pending_adoption, pending_posts,
    ask_claude, INITIAL_INSTRUCTION,
    make_edit_buttons, make_x_buttons, make_after_publish_buttons,
    make_platform_buttons, make_preview, show_loading, restore_buttons, recover_adoption,
    cleanup_cached_files, track_post,
    send_preview, publish_to_channel,
    COUNTRIES_PAGE_1, COUNTRIES_PAGE_2, COUNTRY_NAMES,
)


REPHRASE_LABELS = {
    "longer": "WYDŁUŻ", "shorter": "SKRÓĆ", "retry": "RETRY",
    "soft": "SOFT", "harder": "HARDER", "beautify": "BEAUTIFY ✨", "pc": "PC 🕊️",
    "translate": "TŁUMACZ 🔄", "grok": "GROK 😈",
}

REPHRASE_INSTRUCTIONS = {
    "longer": (
        "Rozbuduj ten tekst ZNACZĄCO — dodaj co najmniej 3-4 nowe zdania. "
        "Dodaj kontekst historyczny, tło wydarzeń, możliwe konsekwencje. "
        "Użyj list punktowanych (• lub ➡️) jeśli pasuje. "
        "Dodaj akapit z analizą lub perspektywą. "
        "Tekst musi być WYRAŹNIE dłuższy niż oryginał. "
        "Oto tekst do rozbudowania:\n\n"
    ),
    "shorter": (
        "Skróć ten tekst MINIMUM o 50% (zostaw co najwyżej połowę słów). "
        "Zostaw TYLKO najważniejsze fakty. Usuń powtórzenia, kontekst, tło. "
        "Zachowaj nagłówek i stopkę. Oto tekst do przerobienia:\n\n"
    ),
    "retry": (
        "Napisz ten tekst ZUPEŁNIE OD NOWA — kompletnie inny styl, inna struktura, "
        "inne otwarcie, inne zakończenie. Użyj synonimów, zmień kolejność informacji. "
        "Tekst nie może przypominać poprzedniej wersji. Zachowaj podobną długość. "
        "Oto tekst do przerobienia:\n\n"
    ),
    "soft": (
        "Przeformułuj ten tekst ZNACZNIE łagodniej — ton dyplomatyczny, wyważony, "
        "bez emocji i dramatyzmu. Zamiast 'atak' użyj 'działania', zamiast 'zniszczenie' "
        "użyj 'uszkodzenie'. Neutralny język dziennikarski. "
        "Zachowaj fakty. Oto tekst do przerobienia:\n\n"
    ),
    "harder": (
        "Przeformułuj ten tekst ZNACZNIE ostrzej — mocny, uderzający ton. "
        "Użyj mocnych słów (eskalacja, uderzenie, kryzys, alarm). "
        "Dodaj dramatyzmu i napięcia. Zacznij od najsilniejszego faktu. "
        "Zachowaj fakty. Oto tekst do przerobienia:\n\n"
    ),
    "beautify": (
        "Przebuduj wizualnie ten tekst:\n"
        "• Dodaj dużo emoji (🔥⚡💥🚨📌➡️⚠️🔴🟢💣🎯🛡️) przy kluczowych punktach\n"
        "• Użyj **pogrubień** na najważniejszych frazach i nazwach\n"
        "• Rozdziel tekst na krótkie akapity (max 2 zdania każdy)\n"
        "• Użyj list z emoji jako bullet points (➡️, 📌, 🔹)\n"
        "• Tekst ma wyglądać jak profesjonalny post na kanale informacyjnym\n"
        "• Zachowaj treść i sens, zmień TYLKO wizualną prezentację\n"
        "Oto tekst do przerobienia:\n\n"
    ),
    "pc": (
        "Przepisz ten tekst w sposób WYŁĄCZNIE informacyjny i neutralny. "
        "Bez emocji, bez opinii, bez dramatyzmu, bez clickbaitu. "
        "Tylko suche fakty: kto, co, kiedy, gdzie, w jakim kontekście. "
        "Jeśli ktoś coś powiedział — zacytuj dosłownie. "
        "Nie oceniaj, nie interpretuj, nie sugeruj. "
        "Ton: agencja prasowa (Reuters/AP). "
        "Zachowaj nagłówek (ale też neutralny) i stopkę. "
        "Oto tekst do przerobienia:\n\n"
    ),
    "translate": (
        "Przetłumacz ten tekst na polski. Tylko tłumaczenie, nie przerabiaj. "
        "Zachowaj oryginalną strukturę, akapity i formatowanie. "
        "Dodaj nagłówek i stopkę jak w innych postach. "
        "Oto tekst do przetłumaczenia:\n\n"
    ),
    "grok": (
        "Przepisz ten tekst w stylu Groka z X/Twittera — sarkastyczny, ironiczny, "
        "z czarnym humorem i szczyptą cynizmu. Bez cenzury, bez PC. "
        "Dodaj uszczypliwe komentarze w nawiasach lub między akapitami. "
        "Możesz żartować z polityków, sytuacji, absurdów. "
        "Zachowaj fakty ale opakuj je w bezlitosny sarkazm. "
        "Używaj emoji sarkastycznie (🤡🫠💀😏🤷). "
        "Nagłówek też ma być sarkastyczny. Zachowaj stopkę. "
        "WAŻNE: Tekst musi być TEJ SAMEJ DŁUGOŚCI co oryginał lub KRÓTSZY. NIE rozbudowuj. "
        "Oto tekst do przerobienia:\n\n"
    ),
}

STYLE_NAMES = {
    "adopt": "przerobiony redakcyjnie",
    "translate_raw": "przetłumaczony",
    "grok": "sarkastyczny/Grok",
    "longer": "rozbudowany",
    "shorter": "skrócony",
    "retry": "przepisany od nowa",
    "soft": "złagodzony",
    "harder": "zaostrzony",
    "beautify": "upiększony",
    "pc": "neutralny/informacyjny",
    "translate": "przetłumaczony",
}


def register_telegram_handlers(bot, userbot):
    """Register all Telegram-platform handlers on the bot."""

    @bot.on(events.CallbackQuery)
    async def on_telegram_button(event):
        sender = await event.get_sender()
        if sender.id != config.OWNER_ID:
            return

        msg_id = event.message_id
        data = event.data.decode()

        # ── Adopt for Telegram ──

        if data == "adopt":
            post = pending_adoption.get(msg_id)
            if not post:
                post = await recover_adoption(bot, msg_id)
            if not post:
                return
            await event.answer("Przerabiam przez Claude...")
            await show_loading(event, "Przerabiam na Telegram...")
            print(f"[ADOPT] msg_id={msg_id} → post z {post['source']}: {post['original_text'][:60]}...")

            rewritten = await ask_claude(post["original_text"], post["source"], INITIAL_INSTRUCTION)
            print(f"[ADOPT] Gotowe.")

            sent = await send_preview(bot, userbot, post, rewritten, make_edit_buttons(has_media=post.get("has_media")), download_media=True, reply_to=msg_id)

            pending_posts[sent.id] = track_post(pending_posts, {
                "text": rewritten,
                "original_text": post["original_text"],
                "source": post["source"],
                "messages": post["messages"],
                "has_media": post["has_media"],
                "cached_files": post.get("cached_files", []),
                "forwarded": post.get("forwarded", False),
                "edit_chain": ["adopt"],
                "platform": "telegram",
                "phase1_msg_id": msg_id,
            }, sent_id=sent.id)
            await restore_buttons(bot, msg_id, post)
            return

        if data == "translate_raw":
            post = pending_adoption.get(msg_id)
            if not post:
                post = await recover_adoption(bot, msg_id)
            if not post:
                return
            await event.answer("Tłumaczę...")
            await show_loading(event, "Tłumaczę...")
            print(f"[TRANSLATE] Tłumaczę post z {post['source']}...")

            instruction = "Przetłumacz poniższy tekst na polski. Oto tekst:\n\n"
            translated = await ask_claude(
                post["original_text"], post["source"], instruction,
                system_prompt="Jesteś tłumaczem. Tłumacz tekst na polski. Tylko tłumaczenie — nie przerabiaj, nie dodawaj niczego od siebie, nie zmieniaj struktury. Zachowaj oryginalne formatowanie i akapity. Formatuj HTML: <b>bold</b> do pogrubień, <blockquote>cytat</blockquote> do cytatów. NIGDY nie używaj Markdown (**bold**, _italic_)."
            )
            print(f"[TRANSLATE] Gotowe.")

            preview, preview_ents = make_preview(f"🔄 Tłumaczenie z {post['source']}:", translated)
            sent = await send_preview(bot, userbot, post, preview, make_platform_buttons(has_media=post.get("has_media", False)), formatting_entities=preview_ents, reply_to=msg_id)

            pending_adoption[sent.id] = track_post(pending_adoption, {
                "original_text": translated,
                "source": post["source"],
                "messages": post["messages"],
                "has_media": post["has_media"],
                "cached_files": post.get("cached_files", []),
                "forwarded": post.get("forwarded", False),
            }, sent_id=sent.id)
            await restore_buttons(bot, msg_id, post)
            return

        # ── Country pages ──

        if data == "countries":
            post = pending_posts.get(msg_id)
            if not post or post.get("platform") in ("x", "facebook"):
                return
            await event.answer("Wybieram kraj...")
            print(f"[COUNTRIES] msg_id={msg_id} → post z {post['source']}")
            await bot.send_message(
                config.OWNER_ID,
                "Wybierz kraj — tekst zostanie przerobiony z jego perspektywą:",
                buttons=COUNTRIES_PAGE_1,
                reply_to=msg_id,
            )
            return

        if data == "countries_p2":
            await event.answer("Strona 2...")
            await (await event.get_message()).edit(
                "Wybierz kraj — tekst zostanie przerobiony z jego perspektywą:",
                buttons=COUNTRIES_PAGE_2,
            )
            return

        if data == "countries_p1":
            await event.answer("Strona 1...")
            await (await event.get_message()).edit(
                "Wybierz kraj — tekst zostanie przerobiony z jego perspektywą:",
                buttons=COUNTRIES_PAGE_1,
            )
            return

        # ── Country bias ──

        if data.startswith("bias_"):
            code = data[5:]
            country = COUNTRY_NAMES.get(code, code)

            this_msg = await event.get_message()
            parent_id = this_msg.reply_to_msg_id if this_msg.reply_to_msg_id else msg_id
            post = pending_posts.get(parent_id)
            if not post:
                return

            await event.answer(f"Przerabiam ({country})...")
            await show_loading(event, f"Perspektywa: {country}...")
            print(f"[BIAS {code}] Przerabiam post z {post['source']} z perspektywą {country}...")

            instruction = (
                f"Przeformułuj ten tekst z perspektywą korzystną dla {country}. "
                f"Pokaż {country} w pozytywnym świetle, podkreśl ich racje, argumenty i osiągnięcia. "
                f"Zachowaj fakty ale dobierz słowa i narrację tak żeby {country} wypadał dobrze. "
                f"Oto tekst do przerobienia:\n\n{post['text']}"
            )
            rewritten = await ask_claude(post["original_text"], post["source"], instruction)
            print(f"[BIAS {code}] Gotowe.")

            anchor = post.get("phase1_msg_id")
            sent = await send_preview(bot, userbot, post, rewritten, make_edit_buttons(has_media=post.get("has_media")), download_media=post.get("has_media", False), reply_to=anchor)

            post["text"] = rewritten
            del pending_posts[parent_id]
            pending_posts[sent.id] = track_post(pending_posts, post, sent_id=sent.id)

            try:
                await this_msg.delete()
            except Exception:
                pass
            return

        # ── Continue to X after Telegram publish ──

        if data == "continue_x":
            post = pending_posts.get(msg_id)
            if not post:
                await event.answer("Post wygasł")
                return
            await event.answer("Przerabiam na X...")
            await show_loading(event, "Przerabiam na X...")
            print(f"[CONTINUE_X] Przerabiam post z {post['source']} na X...")

            from x_handlers import X_INSTRUCTION, X_SYSTEM_PROMPT
            rewritten = await ask_claude(
                post["original_text"], post["source"], X_INSTRUCTION,
                system_prompt=X_SYSTEM_PROMPT,
            )
            print(f"[CONTINUE_X] Gotowe.")

            anchor = post.get("phase1_msg_id")

            new_post = {
                "text": rewritten,
                "original_text": post["original_text"],
                "source": post["source"],
                "messages": post["messages"],
                "has_media": post["has_media"],
                "cached_files": post.get("cached_files", []),
                "forwarded": post.get("forwarded", False),
                "edit_chain": ["adopt_x"],
                "platform": "x",
                "phase1_msg_id": anchor,
            }
            sent = await send_preview(bot, userbot, new_post, rewritten, make_x_buttons(has_media=post.get("has_media", False)), download_media=post.get("has_media", False), reply_to=anchor)

            del pending_posts[msg_id]
            pending_posts[sent.id] = track_post(pending_posts, new_post, sent_id=sent.id)

            try:
                await (await event.get_message()).delete()
            except Exception:
                pass
            return

        # ── Edit buttons (Telegram post) ──

        post = pending_posts.get(msg_id)
        if not post or post.get("platform") in ("x", "x_done", "facebook", "fb_done"):
            return

        if data == "pub_yes":
            await event.answer("Publikuję ze zdjęciem..." if post.get("has_media") else "Publikuję...")
            await show_loading(event, "Publikuję...")
            print(f"[PUBLISH] Publikuję na kanale (ze zdjęciem: {post.get('has_media')})...")
            await publish_to_channel(userbot, bot, post, post["text"])
            original_msg = await event.get_message()
            await original_msg.edit(original_msg.text + "\n\n✅ OPUBLIKOWANO", buttons=make_after_publish_buttons("telegram"))
            post["platform"] = "t_done"
            return

        if data == "pub_text_only":
            await event.answer("Publikuję bez zdjęcia...")
            await show_loading(event, "Publikuję...")
            print(f"[PUBLISH] Publikuję na kanale (tylko tekst)...")
            await userbot.send_message(config.CHANNEL_ID, post["text"], parse_mode='html')
            original_msg = await event.get_message()
            await original_msg.edit(original_msg.text + "\n\n✅ OPUBLIKOWANO (tekst)", buttons=make_after_publish_buttons("telegram"))
            post["platform"] = "t_done"
            return

        if data == "pub_edit":
            await event.answer("Edycja...")
            print(f"[PUB_EDIT] msg_id={msg_id} → post z {post['source']}")
            await bot.send_message(
                config.OWNER_ID,
                "Wyślij nowy tekst dla tego posta (odpowiedz na tę wiadomość):",
                reply_to=msg_id,
            )
            return

        if data in REPHRASE_INSTRUCTIONS:
            label = REPHRASE_LABELS[data]
            await event.answer(f"Przerabiam ({label})...")
            await show_loading(event, f"{label}...")
            print(f"[{label}] Przerabiam post z {post['source']}...")

            chain = post.get("edit_chain", [])
            style_context = ""
            if chain:
                applied = [STYLE_NAMES.get(s, s) for s in chain]
                style_context = (
                    f"WAŻNE: Dotychczas zastosowane style: {', '.join(applied)}. "
                    "ZACHOWAJ charakter i ton poprzednich edycji, tylko zastosuj nowe polecenie. "
                    "Np. jeśli tekst jest sarkastyczny — zostaw sarkazm. Jeśli formalny — zostaw formalny ton.\n\n"
                )

            instruction = style_context + REPHRASE_INSTRUCTIONS[data] + post["text"]
            rewritten = await ask_claude(post["original_text"], post["source"], instruction)
            print(f"[{label}] Gotowe.")

            anchor = post.get("phase1_msg_id")
            sent = await send_preview(bot, userbot, post, rewritten, make_edit_buttons(has_media=post.get("has_media")), download_media=post.get("has_media", False), reply_to=anchor)

            post["text"] = rewritten
            post.setdefault("edit_chain", []).append(data)
            del pending_posts[msg_id]
            pending_posts[sent.id] = track_post(pending_posts, post, sent_id=sent.id)

            try:
                await (await event.get_message()).delete()
            except Exception:
                pass
            return

    # ── Text edit replies ──

    @bot.on(events.NewMessage(func=lambda e: e.is_private and e.is_reply))
    async def on_edit_reply(event):
        if event.sender_id != config.OWNER_ID:
            return

        reply_msg = await event.get_reply_message()
        original_msg_id = reply_msg.reply_to_msg_id if reply_msg.reply_to_msg_id else reply_msg.id

        post = pending_posts.get(original_msg_id)
        if not post or post.get("platform") == "x":
            return

        text = event.text.strip()
        sender = await event.get_sender()
        print(f"[CMD] reply: {text[:80]} — {sender.username or sender.first_name} ({sender.id})")

        if text.startswith("!"):
            new_text = text[1:].strip()
            post["text"] = new_text
            await event.reply("Tekst zaktualizowany.")
        else:
            await event.reply("Przerabiam...")
            new_text = await ask_claude(post["original_text"], post["source"],
                f"{text}\n\nOto tekst do przerobienia:\n\n{post['text']}")
            post["text"] = new_text

        anchor = post.get("phase1_msg_id")
        sent = await send_preview(bot, userbot, post, post["text"], make_edit_buttons(has_media=post.get("has_media")), download_media=post.get("has_media", False), reply_to=anchor)

        del pending_posts[original_msg_id]
        pending_posts[sent.id] = track_post(pending_posts, post, sent_id=sent.id)
