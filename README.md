# newsautomation

Telegram bot do automatycznego monitorowania kanałów informacyjnych, przerabiania postów przez Claude AI i publikowania na własnym kanale.

## Wymagania

- Python 3.11+
- Konto Telegram (API_ID, API_HASH) + Bot Token
- Klucz API Claude (Anthropic)

## Konfiguracja

Utwórz plik `.env`:

```env
API_ID=12345678
API_HASH=abc123...
BOT_TOKEN=123456:ABC-DEF...
OWNER_ID=123456789
CHANNEL_ID=-1001234567890
CLAUDE_API_KEY=sk-ant-...
SOURCE_CHANNELS=@channel1,@channel2
```

## Uruchomienie

```bash
# Lokalnie
pip install -r requirements.txt
python main.py

# Kontener
podman-compose up -d --build
```

## Jak działa

1. Bot monitoruje kanały z `SOURCE_CHANNELS` co 5 minut
2. Nowe posty wysyłane są jako preview do OWNER_ID z przyciskami
3. Owner decyduje: zaadoptować, przetłumaczyć, odczytać zdjęcie lub odrzucić
4. Po przeróbce przez Claude — edycja stylu, publikacja lub odrzucenie

## Przyciski

### Faza 1 — Adopcja (nowy/przekazany post)

| Przycisk | Co robi |
|----------|---------|
| **Zaadoptuj** | Wysyła tekst do Claude z poleceniem przeróbki na post informacyjny po polsku. Przechodzi do fazy 2. |
| **🔄 Tłumacz** | Tłumaczy tekst na polski bez przeróbki (zachowuje strukturę oryginału). Przechodzi do fazy 2. |
| **📷 Zdjęcie** | *(tylko gdy post ma zdjęcie)* Pobiera zdjęcie, wysyła do Claude Vision — analiza geopolityczna: co widać, kontekst, ocena (eskalacja/deeskalacja/neutralne). Nie adoptuje — tylko informuje. |
| **Odrzuć** | Usuwa wiadomość z czatu. Post znika. |

### Faza 2 — Edycja i publikacja (po adopcji/tłumaczeniu)

#### Górny rząd — publikacja

| Przycisk | Co robi |
|----------|---------|
| **📷 Publikuj ze zdjęciem** | *(tylko gdy post ma media)* Publikuje tekst + zdjęcia/wideo na kanale. |
| **📝 Publikuj bez zdjęcia** | *(tylko gdy post ma media)* Publikuje tylko tekst, bez mediów. |
| **Publikuj** | *(gdy post nie ma mediów)* Publikuje tekst na kanale. |
| **Odrzuć** | Usuwa wiadomość. Post nie zostaje opublikowany. |

#### Styl i długość

| Przycisk | Co robi |
|----------|---------|
| **Wydłuż** | Rozbudowuje tekst — dodaje kontekst, tło, konsekwencje. Min. 3-4 nowe zdania. |
| **Skróć** | Skraca tekst o min. 50%. Zostają tylko kluczowe fakty. |
| **Grok 😈** | Przepisuje w stylu Groka z X/Twittera — sarkastyczny, ironiczny, czarny humor, cynizm. Fakty zostają, opakowanie zmienia się. |

#### Przeróbka

| Przycisk | Co robi |
|----------|---------|
| **Retry** | Przepisuje tekst od nowa — inny styl, struktura, otwarcie. Podobna długość. |
| **Soft** | Łagodniejszy ton — dyplomatyczny, wyważony, bez emocji. |
| **Harder** | Ostrzejszy ton — mocne słowa, dramatyzm, napięcie. |

#### Formatowanie i inne

| Przycisk | Co robi |
|----------|---------|
| **✨** (Beautify) | Dodaje emoji, pogrubienia, listy, rozdziela na krótkie akapity. Wizualna przeróbka. |
| **🕊️** (PC) | Neutralny, informacyjny ton jak agencja prasowa (Reuters/AP). Bez opinii, bez clickbaitu. |
| **🔄** (Translate) | Tłumaczy na polski z zachowaniem struktury. Dodaje nagłówek i stopkę. |
| **Edytuj** | Bot prosi o nowy tekst — odpowiadasz wiadomością i tekst zostaje podmieniony. Lub wpisujesz instrukcję (np. "dodaj cytat z Bidena") i Claude przerabia. |
| **🌍** (Countries) | Wybór kraju — tekst zostaje przerobiony z perspektywą korzystną dla wybranego państwa. |

### Kontekst edycji (edit chain)

Każda edycja jest zapamiętywana. Jeśli klikniesz **Grok** a potem **Skróć** — tekst zostanie skrócony ale **sarkazm zostaje**. Claude dostaje informację o dotychczasowych stylach i zachowuje ich charakter.

## Komendy

| Komenda | Co robi |
|---------|---------|
| `/check` | Ręcznie sprawdza kanały źródłowe (zamiast czekać na polling). |
| `/lastone` | Pobiera ostatni post z pierwszego kanału źródłowego. |
| Przekazanie wiadomości | Forward z dowolnego kanału — bot traktuje jak nowy post do adopcji. |
| Wysłanie zdjęcia | Bezpośrednie zdjęcie — Claude odczytuje treść/opisuje i generuje post. |

## Architektura

```
SOURCE_CHANNELS ──polling co 5min──▶ Bot (preview + przyciski)
                                        │
                                        ▼
                                    OWNER_ID
                                    (Zaadoptuj / Tłumacz / 📷 / Odrzuć)
                                        │
                                        ▼
                                    Claude AI (Haiku 4.5)
                                        │
                                        ▼
                                    OWNER_ID
                                    (Publikuj / Edytuj / Grok / Skróć / ...)
                                        │
                                        ▼
                                    CHANNEL_ID (publikacja)
```
