# Plan techniczny: SocialFreak (rozszerzenie newsautomation)

**Konwencja:** Wszystkie ścieżki i zmiany dotyczą wyłącznie repozytorium **`/Users/kamils/Downloads/git/socialfreak`**. Projekt **newsautomation** pozostaje bez zmian (aktualna, działająca wersja). SocialFreak = kopia newsautomation + poniższe feature’y.

**Baza kodu:** Skopiować całość z `newsautomation` do `socialfreak` (np. `cp -r newsautomation socialfreak`), potem pracować tylko w `socialfreak`.

---

## Źródła planu

Plan integruje dwa zestawy wymagań:

- **A (Post Planner):** Dostosowanie posta do platformy (A.1), Kategoryzacja/buckety (A.2), Harmonogram publikacji (A.3), Recykling treści (A.4), Approval workflow (A.5), Podgląd przed publikacją (A.6), Bulk actions (A.7), Szablony/saved replies (A.8), Widok kalendarza (A.9), Raport/analityki (A.10).
- **B (Sugestie Claude’a):** Scheduling/kolejka (B.1), Best Time to Post (B.2), Evergreen Recycling (B.3), Analytics Dashboard (B.4), Sentiment/Tone Detection (B.5), RSS/Web Source Monitoring (B.6), Content Categorization & Auto-tagging (B.7), Bulk/Draft Queue (B.8), Approval Workflow (B.9), Unified Published History + Search (B.10).

Mapowanie źródeł do priorytetów: patrz nagłówki poszczególnych sekcji (np. „Źródło: B.4, A.10").

---

## Co już istnieje w systemie (nie wymaga implementacji od zera)

| Feature | Status | Lokalizacja |
|---------|--------|-------------|
| Preview (media + text) | ✅ Działa | Web panel (PostDetail), `send_preview()` w shared.py |
| Adopt per platform (T/X/FB) | ✅ Działa | telegram/x/facebook_handlers.py, web_api.py |
| Rephrase / Generate (Claude) | ✅ Działa | `ask_claude()` w shared.py, 9 stylów w telegram_handlers |
| Reels_cache | ✅ Działa | shared.py (`load_reels`, `add_reel_media`, dedup MD5) |
| Web panel: lista, szczegóły, przyciski | ✅ Działa | App.jsx (PostList, PostDetail, Sidebar) |
| Facebook Graph API publishing | ✅ Działa | facebook_handlers.py (`publish_to_facebook`) |
| Telegram channel publishing | ✅ Działa | shared.py (`publish_to_channel`) |
| Claude Vision (analiza zdjęć) | ✅ Działa | shared.py (`ask_claude_vision`) |
| Country bias (perspektywa kraju) | ✅ Działa | telegram_handlers.py (16 krajów) |
| Edit chain tracking | ✅ Działa | `post["edit_chain"]` w handlers |

**Czego brakuje (= scope tego planu):**
- Brak trwałego zapisu opublikowanych postów (ginią po restarcie)
- Brak tagów/kategorii
- Brak bulk actions w web panelu
- Brak schedulingu (wszystko na żywo)
- Brak analizy tonu/sentymentu
- Brak approval workflow (tylko 1 owner)
- Brak preview per platform (X 280, FB styl)
- Brak wyszukiwania w historii
- Brak recyklingu/evergreen
- Brak RSS, Best Time, kalendarza, szablonów

---

## 0. Struktura katalogów (socialfreak)

```
socialfreak/
├── config.py
├── main.py
├── shared.py
├── web_api.py
├── telegram_handlers.py
├── x_handlers.py
├── facebook_handlers.py
├── published_store.py      # NOWY: zapis historii publikacji
├── scheduler.py            # NOWY: kolejka zaplanowanych publikacji
├── rss_feeds.py            # NOWY: źródła RSS (opcjonalnie później)
├── requirements.txt
├── .env
├── data/                   # NOWY katalog: trwałe dane
│   ├── published.json     # lub published.db (SQLite)
│   ├── scheduled.json
│   └── templates.json
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── index.css
│   │   ├── main.jsx
│   │   ├── components/     # NOWY: wydzielone komponenty
│   │   │   ├── Sidebar.jsx
│   │   │   ├── PostList.jsx
│   │   │   ├── PostDetail.jsx
│   │   │   ├── PlatformPreviews.jsx
│   │   │   ├── HistoryView.jsx
│   │   │   ├── CalendarView.jsx
│   │   │   └── BulkActionBar.jsx
│   │   └── ...
│   └── ...
├── Containerfile
├── podman-compose.yml
└── deploy.sh
```

---

## 1. Analytics / Historia opublikowanych (priorytet 1) — Źródło: B.4, A.10

**Cel:** Każda publikacja (Telegram/FB/X) zapisywana do trwałego store’u; w panelu ekran „Historia” z tabelą i wyszukiwaniem.

### 1.1 Backend – storage

**Nowy plik:** `socialfreak/published_store.py`

- **Format:** JSON w `data/published.json` (alternatywa: SQLite `data/published.db`).
- **Struktura rekordu:**
```python
{
  "id": "pub_uuid",
  "published_at": "ISO8601",
  "platform": "telegram" | "facebook" | "x",
  "source": str,
  "text": str,
  "original_text": str,
  "post_id": str,        # id z pending_posts / web_*
  "link": str | None    # opcjonalnie URL do posta (FB/X)
}
```
- **Funkcje:** `append_published(record)`, `list_published(limit, offset, platform=None, q=None, from_date=None, to_date=None)` (search po `text`/`original_text`), `get_stats()` (count per platform, ostatnie 7 dni).

### 1.2 Backend – integracja przy publish

**Modyfikacje:**

- `socialfreak/shared.py`: w `publish_to_channel()` na końcu (po udanym `send_message`/`send_file`) wywołać `published_store.append_published({...})`.
- `socialfreak/facebook_handlers.py`: w `publish_to_facebook()` po udanym postie wywołać `published_store.append_published({...})`.
- `socialfreak/web_api.py`: endpointy `publish_telegram` / `publish_facebook` po `_run(_pub())` wywołać append z danymi posta (post_id, platform, source, text, original_text, link jeśli API zwraca).

**Nowe endpointy w** `socialfreak/web_api.py`:

- `GET /api/published?limit=50&offset=0&platform=telegram&q=Iran&from=2025-03-01&to=2025-03-31`  
  Response: `{ "items": [...], "total": N }`.
- `GET /api/analytics/summary`  
  Response: `{ "by_platform": {...}, "last_7_days": [...] }` (na podstawie `get_stats()`).

### 1.3 Frontend – UI

- **Sidebar:** Dodać ikonę „Historia” (np. 📋) obok Home / T / X / F; `view === 'history'` → render `HistoryView`.
- **Nowy komponent:** `frontend/src/components/HistoryView.jsx`:
  - Stan: `items`, `total`, `loading`, `q`, `platformFilter`, `from`, `to`.
  - Pola: input wyszukiwania (`q`), select platformy, daty od–do, przycisk „Szukaj”.
  - Tabela: kolumny Data, Platforma, Źródło, Fragment tekstu (np. 80 znaków), link (jeśli jest).
  - Paginacja: `limit=50`, przyciski Następna/Poprzednia z `offset`.
  - Fetch: `GET /api/published?...` przy mount i przy zmianie filtrów.
- **App.jsx:** Import `HistoryView`, w `main` render warunkowy: `view === 'history' ? <HistoryView /> : ...` (zamiast PostList/PostDetail).

### 1.4 Pliki do utworzenia/edycji

| Akcja | Ścieżka |
|-------|--------|
| NOWY | `socialfreak/published_store.py` |
| NOWY | `socialfreak/data/` (katalog), `socialfreak/data/published.json` (pusty `[]` lub init przy pierwszym zapisie) |
| EDYCJA | `socialfreak/shared.py` – po udanym publish wywołanie `published_store.append_published` |
| EDYCJA | `socialfreak/facebook_handlers.py` – to samo |
| EDYCJA | `socialfreak/web_api.py` – append po publish_telegram/publish_facebook + `GET /api/published`, `GET /api/analytics/summary` |
| NOWY | `socialfreak/frontend/src/components/HistoryView.jsx` |
| EDYCJA | `socialfreak/frontend/src/App.jsx` – view `history`, Sidebar + ikona Historia |
| EDYCJA | `socialfreak/frontend/src/index.css` – style dla tabeli historii, filtrów, paginacji |

---

## 2. Auto-tagging / Kategorie (priorytet 2) — Źródło: B.7, A.2

**Cel:** Przy adopcji Claude zwraca 1–3 tagi; zapis w `post["tags"]`; w panelu filtr po tagu i wyświetlanie tagów na kartach.

### 2.1 Backend – model i prompt

- **shared.py:** Rozszerzyć strukturę posta (w `pending_adoption` i `pending_posts`) o pole `tags: list[str]`.
- **shared.py:** Nowa funkcja `async def ask_claude_tags(text: str, source: str) -> list[str]`. Prompt: „Na podstawie tekstu i źródła zwróć 1–3 tagi tematyczne po polsku lub angielsku, np. Ukraina, NATO, BliskiWschód. Tylko lista tagów, po jednym w linii.” Parsowanie odpowiedzi (linie, bez #).
- **web_api.py – adopt:** Po `ask_claude(...)` (przeróbka) wywołać `ask_claude_tags(original, source)` i zapisać `new_post["tags"] = tags`.
- **web_api.py – _serialize_post:** Dodać w zwracanym obiekcie pole `"tags": post.get("tags") or []`.
- **web_api.py – list_posts:** Parametr opcjonalny `tag: str`. Filtr: `new` i `in_progress` przefiltrowane po `tag in (post.get("tags") or [])`.

**Endpoint:** `GET /api/posts?tag=Ukraina` (query param).

### 2.2 Frontend – UI

- **PostList (karty):** Pod `source` wyświetlić `post.tags` jako chipy/badże (np. `<span class="tag">Ukraina</span>`).
- **PostDetail:** Sekcja „Tagi” – wyświetlenie `post.tags`, opcjonalnie edycja (np. input + zapis przez `PUT /api/posts/{id}/tags`).
- **Sidebar lub nad listą:** Dropdown „Filtruj tag” z listą tagów (np. z ostatnich postów lub stała lista). Wybór ustawia `selectedTag` → fetch `GET /api/posts?tag=...`.
- **App.jsx / PostList:** Przekazać `selectedTag` do `usePostList` lub osobny fetch z query; wyświetlać tylko posty z danym tagiem.

### 2.3 Pliki

| Akcja | Ścieżka |
|-------|--------|
| EDYCJA | `socialfreak/shared.py` – `ask_claude_tags`, rozszerzenie słownika posta o `tags` |
| EDYCJA | `socialfreak/web_api.py` – adopt (wywołanie tags), _serialize_post (tags), list_posts (query `tag`) |
| EDYCJA | `socialfreak/frontend/src/App.jsx` – stan `selectedTag`, dropdown, przekazanie do listy |
| EDYCJA | `socialfreak/frontend/src/App.jsx` lub `PostList.jsx` – render tagów na kartach, w PostDetail |
| EDYCJA | `socialfreak/frontend/src/index.css` – `.tag`, `.tagFilter` |

---

## 3. Bulk adopt / Bulk actions (priorytet 3) — Źródło: B.8, A.7

**Cel:** W liście „Nowe” checkbox przy każdym poście; pasek akcji „Adoptuj zaznaczone → T/X/F”, „Odrzuć zaznaczone”.

### 3.1 Backend

- **web_api.py:**  
  - `POST /api/posts/bulk-adopt`  
    Body: `{ "ids": ["123", "456"], "platform": "telegram" }`.  
    Pętla: dla każdego `id` wywołać tę samą logikę co w `POST /api/posts/{id}/adopt` (bez zwracania przekierowania na nowy post). Zwrócić `{ "adopted": ["web_xxx", ...], "errors": [{ "id": "123", "error": "..." }] }`.  
  - `POST /api/posts/bulk-reject`  
    Body: `{ "ids": ["123", "456"] }`.  
    Dla każdego id: wywołać logikę reject (usunięcie z pending_adoption, cleanup). Zwrócić `{ "rejected": 2 }`.

### 3.2 Frontend

- **PostList:** Stan `selectedIds: Set<string>`. Checkbox przy każdej karcie „Nowe” (i ewent. „W trakcie”) – toggle w `selectedIds`. Checkbox „Zaznacz wszystkie” dla sekcji Nowe.
- **BulkActionBar (nowy komponent):** Renderowany gdy `selectedIds.size > 0`. Przyciski: „Adoptuj zaznaczone → Telegram”, „→ X”, „→ Facebook”, „Odrzuć zaznaczone”. Na klik: `POST bulk-adopt` lub `bulk-reject` z `Array.from(selectedIds)`, potem `refreshList()`, wyczyszczenie `selectedIds`.
- **App.jsx:** Przekazać `selectedIds`, `setSelectedIds` do PostList; render BulkActionBar nad lub pod listą (sticky pasek).

### 3.3 Pliki

| Akcja | Ścieżka |
|-------|--------|
| EDYCJA | `socialfreak/web_api.py` – `POST /api/posts/bulk-adopt`, `POST /api/posts/bulk-reject` |
| NOWY | `socialfreak/frontend/src/components/BulkActionBar.jsx` |
| EDYCJA | `socialfreak/frontend/src/App.jsx` – stan selectedIds, BulkActionBar |
| EDYCJA | `socialfreak/frontend/src/App.jsx` (PostList) – checkboxi, integracja z BulkActionBar |
| EDYCJA | `socialfreak/frontend/src/index.css` – .bulkBar, .checkbox |

---

## 4. Scheduling / Kolejka publikacji (priorytet 4) — Źródło: B.1, A.3

**Cel:** Przycisk „Zaplanuj” w szczegółach posta (i opcjonalnie w bocie `/schedule HH:MM`); post trafia do kolejki z `publish_at`; worker co minutę wysyła due posty.

### 4.1 Backend – scheduler storage i worker

- **Nowy plik:** `socialfreak/scheduler.py`
  - Storage: `data/scheduled.json` (lista zadań). Rekord: `{ "id": "sched_uuid", "post_id": "web_xxx", "platform": "telegram", "publish_at": "ISO8601", "created_at": "ISO8601" }`.
  - Funkcje: `add_scheduled(post_id, platform, publish_at)`, `get_due()`, `remove_scheduled(sched_id)`, `list_scheduled(limit)`.
  - **Worker:** `async def run_scheduler_loop(bot, userbot, loop_interval=60)` – co 60 s wywołuje `get_due()`, dla każdego due: pobiera post z `pending_posts[post_id]`, wywołuje `publish_to_channel` lub `publish_to_facebook`, zapisuje do `published_store`, usuwa z `scheduled`.

- **web_api.py:**  
  - `POST /api/posts/{post_id}/schedule`  
    Body: `{ "platform": "telegram"|"facebook"|"x", "publish_at": "2025-03-20T14:00:00" }`.  
    Walidacja: post istnieje, `publish_at` w przyszłości. `scheduler.add_scheduled(post_id, platform, publish_at)`.  
  - `GET /api/scheduled`  
    Zwraca listę zaplanowanych (do widoku kalendarza i listy).
  - `DELETE /api/scheduled/{sched_id}`  
    Usuwa z kolejki.

- **main.py:** Po starcie bota uruchomić w tle `asyncio.create_task(run_scheduler_loop(bot, userbot))` (ten sam event loop).

### 4.2 Frontend – UI

- **PostDetail:** Przy „Publikuj Telegram” dodać przycisk „Zaplanuj”. Klik otwiera modal/dialog: wybór platformy, pole datetime-local (lub date + time), „Zapisz”. Submit → `POST /api/posts/{id}/schedule`. Komunikat „Dodano do kolejki”.
- **Sidebar lub widok:** Ikona „Kalendarz” / „Zaplanowane” → widok listy zaplanowanych (`GET /api/scheduled`). Tabela: data, platforma, źródło/fragment; przycisk „Anuluj” → `DELETE /api/scheduled/{id}`.
- **HistoryView / osobny widok:** Opcjonalnie w „Historia” pokazać też zaplanowane (z `GET /api/scheduled`) w jednym widoku „Nadchodzące”.

### 4.3 Pliki

| Akcja | Ścieżka |
|-------|--------|
| NOWY | `socialfreak/scheduler.py` |
| NOWY | `socialfreak/data/scheduled.json` |
| EDYCJA | `socialfreak/web_api.py` – POST schedule, GET scheduled, DELETE scheduled |
| EDYCJA | `socialfreak/main.py` – start scheduler loop |
| EDYCJA | `socialfreak/frontend/src/App.jsx` (PostDetail) – przycisk Zaplanuj, modal datetime |
| NOWY/EDYCJA | `socialfreak/frontend/src/components/ScheduledView.jsx` – lista zaplanowanych |
| EDYCJA | `socialfreak/frontend/src/index.css` – modal, datetime input |

---

## 5. Sentiment / Tone detection (priorytet 5) — Źródło: B.5

**Cel:** Na karcie posta (nowy i w trakcie) badge: Eskalacja / Napięcie / Dyplomacja (np. kolory czerwony/żółty/zielony). Claude analizuje tekst przed adopcją lub on-demand.

### 5.1 Backend

- **shared.py:** `async def ask_claude_tone(text: str) -> str` → "escalation" | "tension" | "diplomacy" (lub etykiety PL). Prompt: „Określ ton: eskalujący, napięty, dyplomatyczny. Odpowiedz jednym słowem.”
- **Struktura posta:** Pole `tone: str | None`. Ustawiane: (a) przy pierwszym wejściu posta do systemu (np. w poll/forward handler), lub (b) on-demand w panelu.
- **web_api.py:**  
  - W `_serialize_post` dodać `"tone": post.get("tone")`.  
  - `POST /api/posts/{post_id}/detect-tone` – wywołuje `ask_claude_tone(original_text)`, zapisuje w `post["tone"]`, zwraca `{ "tone": "..." }`. (Post może być w pending_adoption lub pending_posts – w obu przypadkach zapis w odpowiednim słowniku.)

- **Miejsce zapisu tone przy wejściu:** W `main.py` (poll) / `telegram_handlers.py` (forward) po dodaniu do `pending_adoption` można w tle wywołać `ask_claude_tone` i zapisać `post["tone"]` (opcjonalnie, żeby nie blokować).

### 5.2 Frontend

- **PostList (karta):** Jeśli `post.tone` istnieje, wyświetlić badge: np. `tone === 'escalation'` → czerwony, „Eskalacja”; `tension` → żółty; `diplomacy` → zielony.
- **PostDetail:** W nagłówku lub nad podglądem badge tonu; przycisk „Wykryj ton” jeśli brak → `POST /api/posts/{id}/detect-tone`, odświeżenie posta.

### 5.3 Pliki

| Akcja | Ścieżka |
|-------|--------|
| EDYCJA | `socialfreak/shared.py` – `ask_claude_tone` |
| EDYCJA | `socialfreak/web_api.py` – _serialize_post (tone), POST detect-tone |
| EDYCJA | `socialfreak/frontend/src/App.jsx` – badge tone na kartach i w PostDetail, przycisk „Wykryj ton” |
| EDYCJA | `socialfreak/frontend/src/index.css` – .badgeToneEscalation, .badgeToneTension, .badgeToneDiplomacy |

---

## 6. Approval workflow (priorytet 6) — Źródło: A.5, B.9

**Cel:** Status posta: draft | ready_for_review | approved. Tylko approved można opublikować (lub zaplanować). Opcjonalnie drugi operator (Telegram user_id) może ustawiać „Do przeglądu”.

### 6.1 Backend

- **shared.py / struktura posta:** Pole `status: "draft" | "ready_for_review" | "approved"` (domyślnie `draft`). Opcjonalnie `submitted_by: int | None` (Telegram user_id).
- **config.py:** `REVIEWER_IDS: list[int]` (opcjonalnie) – user_id, którzy mogą wysyłać do review; domyślnie tylko OWNER_ID może approve/publish.
- **web_api.py:**  
  - `PUT /api/posts/{post_id}/status` Body: `{ "status": "ready_for_review" | "approved" }`.  
  - W `list_posts` i `_serialize_post` zwracać `status`, `submitted_by`.  
  - W `publish_telegram` / `publish_facebook`: jeśli wymagane, sprawdzenie `post.get("status") == "approved"` (albo pominięcie jeśli brak workflow).
- **Telegram (main/telegram_handlers):** Dla wiadomości od user_id z REVIEWER_IDS przycisk „Wyślij do review” → ustawia status `ready_for_review`, `submitted_by=user_id`. Owner widzi w panelu listę „Do zatwierdzenia” (filtr `status === 'ready_for_review'`).

### 6.2 Frontend

- **PostDetail:** Wyświetlenie `post.status`; przyciski „Oznacz do przeglądu”, „Zatwierdź” (tylko dla owner). Wywołanie `PUT /api/posts/{id}/status`.
- **PostList / filtr:** W Sidebar lub nad listą filtr „Do zatwierdzenia” (view `review`) → fetch z filtrem `status=ready_for_review` (wymaga rozszerzenia API o query `status`).
- **Przycisk Publikuj:** Disabled jeśli `status !== 'approved'` (gdy workflow włączony).

### 6.3 Pliki

| Akcja | Ścieżka |
|-------|--------|
| EDYCJA | `socialfreak/shared.py` – domyślny status w track_post / new_post |
| EDYCJA | `socialfreak/config.py` – REVIEWER_IDS |
| EDYCJA | `socialfreak/web_api.py` – PUT status, serialization status/submitted_by, opcjonalnie GET /api/posts?status= |
| EDYCJA | `socialfreak/telegram_handlers.py` – przycisk „Do review” dla reviewerów |
| EDYCJA | `socialfreak/frontend/src/App.jsx` – status, przyciski, filtr review, disable Publikuj |

---

## 7. Preview per platform (priorytet 7) — Źródło: A.1, A.6

**Cel:** W PostDetail trzy minipodglądy: jak post będzie wyglądał na Telegramie, X (z licznikiem 280), Facebooku.

### 7.1 Backend

- Nie wymaga nowych endpointów. Tekst per platform już jest w `text_telegram`, `text_x`, `text_facebook`. Opcjonalnie endpoint `GET /api/posts/{id}/preview?platform=telegram` zwracający fragment do iframe (niekonieczny – można wszystko w frontend).

### 7.2 Frontend

- **PlatformPreviews.jsx:** Komponent przyjmuje `textTelegram`, `textX`, `textFacebook`, `mediaUrl`. Trzy karty/sekcje:
  - Telegram: bubble (zaokrąglony blok), miniaturka media, tekst.
  - X: jeden blok tekstu + licznik znaków `textX.length / 280`.
  - Facebook: krótki blok tekstu (styl „post na stronie”).
- **PostDetail:** Nad lub pod obecnym „Podgląd” wstawić `<PlatformPreviews ... />` z tekstami z aktualnego taba lub wszystkich trzech (w zależności od UX).

### 7.3 Pliki

| Akcja | Ścieżka |
|-------|--------|
| NOWY | `socialfreak/frontend/src/components/PlatformPreviews.jsx` |
| EDYCJA | `socialfreak/frontend/src/App.jsx` (PostDetail) – import i render PlatformPreviews |
| EDYCJA | `socialfreak/frontend/src/index.css` – .previewTelegram, .previewX, .previewFacebook, .charCount |

---

## 8. Published history search (priorytet 8) — Źródło: B.10

**Cel:** Rozszerzenie ekranu „Historia” o wyszukiwanie pełnotekstowe i filtry (już ujęte w pkt 1). Ewentualnie zaawansowane: FTS w SQLite, highlight fragmentu.

### 8.1 Backend

- **published_store.py:** W `list_published` parametr `q` – filtrowanie po `q in text or q in original_text` (case-insensitive). Przy SQLite: FTS5 lub LIKE '%q%'.

### 8.2 Frontend

- Już w HistoryView (pkt 1): pole `q`, przycisk Szukaj, przekazanie do API. Brak dodatkowych komponentów.

---

## 9. Recykling / Evergreen (priorytet 9) — Źródło: A.4, B.3

**Cel:** Lista „Opublikowane” z przyciskiem „Wznów” / „Zaplanuj ponownie”; opcjonalnie flaga `evergreen` i auto-recycle po X dniach.

### 9.1 Backend

- **published_store:** Pole w rekordzie `evergreen: bool`, `recycle_after_days: int | None`. Funkcja `list_published(..., evergreen_only=False)`, `mark_evergreen(pub_id)`, `get_evergreen_due()` – rekordy gdzie `published_at + recycle_after_days <= now`.
- **web_api.py:**  
  - `POST /api/published/{pub_id}/recycle` – czyta rekord z published_store, tworzy „syntetyczny” post w `pending_posts` (lub kolejce do adopcji) z `original_text`, `source`, `text_telegram` itd. z zapisanego rekordu, żeby użytkownik mógł edytować i ponownie opublikować.  
  - Opcjonalnie worker w scheduler: co dzień `get_evergreen_due()`, dla każdego wywołanie logiki recycle (wstawienie do kolejki).

### 9.2 Frontend

- **HistoryView:** W każdej linii tabeli przycisk „Wznów”. Klik → `POST /api/published/{id}/recycle` → przekierowanie do nowego posta w „W trakcie” lub komunikat „Dodano do listy”.
- **HistoryView:** Checkbox „Evergreen” + pole „Recykluj po (dni)” i przycisk „Zapisz” → `PUT /api/published/{id}` (oznaczenie evergreen + recycle_after_days).

### 9.3 Pliki

| Akcja | Ścieżka |
|-------|--------|
| EDYCJA | `socialfreak/published_store.py` – evergreen, recycle_after_days, get_evergreen_due, mark_evergreen |
| EDYCJA | `socialfreak/web_api.py` – POST published/{id}/recycle, PUT published/{id} |
| EDYCJA | `socialfreak/frontend/src/components/HistoryView.jsx` – przycisk Wznów, checkbox Evergreen |

---

## 10. Best Time, RSS, Kalendarz, Szablony (priorytet 10 – zbiorczo) — Źródło: B.2, B.6, A.9, A.8

Cztery niezależne pod-feature'y. Każdy może być wdrożony osobno po ugruntowaniu historii (#1) i schedulingu (#4).

### 10.1 Best Time to Post — Źródło: B.2

**Cel:** Na podstawie historii publikacji sugerować optymalną godzinę dla danej platformy. Heurystyka lub Claude.

#### Backend

- **published_store.py:** Nowa funkcja `get_publish_time_distribution(platform: str) -> dict[int, int]` — agregacja rekordów po godzinie (0–23), zwraca `{ hour: count }`.
- **web_api.py:**
  - `GET /api/analytics/best-times?platform=telegram`
    Response: `{ “platform”: “telegram”, “distribution”: { “9”: 12, “14”: 8, ... }, “suggested_hour”: 9 }`.
  - Logika `suggested_hour`: godzina z największą liczbą publikacji (prosta heurystyka) lub wywołanie Claude z promptem „Na podstawie rozkładu godzin publikacji dla platformy X, zasugeruj najlepszą godzinę”.

#### Frontend

- **Modal „Zaplanuj” (z pkt 4):** Dodać przycisk „Sugerowana godzina” obok pola datetime. Klik → `GET /api/analytics/best-times?platform=...` → auto-fill godziny w polu datetime.
- **Analytics view (opcjonalnie):** Wykres słupkowy rozkładu godzin publikacji per platforma.

#### Pliki

| Akcja | Ścieżka |
|-------|--------|
| EDYCJA | `socialfreak/published_store.py` – `get_publish_time_distribution` |
| EDYCJA | `socialfreak/web_api.py` – `GET /api/analytics/best-times` |
| EDYCJA | `socialfreak/frontend/src/App.jsx` – przycisk „Sugerowana godzina” w modalu Zaplanuj |

---

### 10.2 RSS / Web Source Monitoring — Źródło: B.6

**Cel:** Dodać RSS (BBC, Reuters, PAP itp.) jako źródła obok kanałów Telegram. Nowe posty z RSS trafiają do `pending_adoption` z etykietą `source: “RSS: nazwa”`.

#### Backend

- **Nowy plik:** `socialfreak/rss_feeds.py`
  - Zależność: `feedparser` (dodać do `requirements.txt`).
  - Konfiguracja: `RSS_FEEDS` w `.env` lub `config.py` — lista URL-i z nazwami:
    ```python
    RSS_FEEDS = [
        {“name”: “BBC News”, “url”: “https://feeds.bbci.co.uk/news/world/rss.xml”},
        {“name”: “PAP”, “url”: “https://...”},
    ]
    ```
  - Persistence: `data/rss_last_seen.json` — `{ “feed_url”: “last_entry_id” }` (żeby nie duplikować).
  - Funkcje:
    - `load_last_seen()`, `save_last_seen()`
    - `async fetch_new_entries(feed: dict) -> list[dict]` — parsuje feed, zwraca nowe wpisy (tytuł + link + opis).
    - `async poll_all_feeds()` — iteruje po `RSS_FEEDS`, dla każdego nowego wpisu tworzy syntetyczny post:
      ```python
      {
          “original_text”: f”{entry.title}\n\n{entry.summary}\n\n{entry.link}”,
          “source”: f”RSS: {feed['name']}”,
          “has_media”: False,
          “messages”: [],
          “cached_files”: [],
      }
      ```
      Wstawia do `pending_adoption` z kluczem `f”rss_{hash(entry.id)}”`.

- **main.py:** `asyncio.create_task(rss_poll_loop())` — pętla co `RSS_POLL_INTERVAL` (np. 300 s = 5 min). Wywołuje `poll_all_feeds()`, dla każdego nowego wpisu `send_preview()` do ownera.

- **web_api.py (opcjonalnie):**
  - `GET /api/rss/feeds` — lista skonfigurowanych feedów.
  - `POST /api/rss/feeds` — dodanie nowego feedu (dynamicznie).
  - `DELETE /api/rss/feeds/{index}` — usunięcie feedu.

#### Frontend (opcjonalnie)

- **Sidebar:** Ikona „RSS” → widok zarządzania feedami (lista, dodaj URL, usuń).
- Posty RSS pojawiają się w normalnej liście „Nowe” z oznaczeniem źródła `RSS: ...`.

#### Pliki

| Akcja | Ścieżka |
|-------|--------|
| NOWY | `socialfreak/rss_feeds.py` |
| NOWY | `socialfreak/data/rss_last_seen.json` |
| EDYCJA | `socialfreak/config.py` – `RSS_FEEDS`, `RSS_POLL_INTERVAL` |
| EDYCJA | `socialfreak/requirements.txt` – `feedparser` |
| EDYCJA | `socialfreak/main.py` – task `rss_poll_loop` |
| OPCJA | `socialfreak/web_api.py` – endpointy zarządzania feedami |
| OPCJA | `socialfreak/frontend/src/App.jsx` – widok RSS |

---

### 10.3 Widok kalendarza — Źródło: A.9

**Cel:** Zaplanowane + opublikowane na osi czasu (widok miesięczny/tygodniowy). Wymaga danych z schedulera (#4) i historii (#1).

#### Backend

- Brak nowych endpointów — dane z istniejących:
  - `GET /api/scheduled` → zaplanowane (z datą `publish_at`).
  - `GET /api/published?from=2025-03-01&to=2025-03-31` → opublikowane (z datą `published_at`).
- Opcjonalnie endpoint łączony: `GET /api/calendar?from=...&to=...`
  Response: `{ “scheduled”: [...], “published”: [...] }` (merge obu źródeł).

#### Frontend

- **Nowy komponent:** `frontend/src/components/CalendarView.jsx`
  - Widok: siatka miesięczna (7 kolumn × 4–5 wierszy) lub tygodniowa (7 kolumn × godziny).
  - Każdy dzień: lista eventów (zaplanowanych = niebieskie, opublikowanych = zielone).
  - Klik na event → nawigacja do szczegółów posta lub do zaplanowanego.
  - Nawigacja: przyciski ◀ / ▶ do przełączania miesiąca/tygodnia.
  - Fetch: przy mount i przy zmianie zakresu dat.
- **Sidebar:** Ikona „Kalendarz” (📅) → `view === 'calendar'`.
- **App.jsx:** Import `CalendarView`, render warunkowy.

#### Pliki

| Akcja | Ścieżka |
|-------|--------|
| NOWY | `socialfreak/frontend/src/components/CalendarView.jsx` |
| EDYCJA | `socialfreak/frontend/src/App.jsx` – view `calendar`, Sidebar ikona |
| EDYCJA | `socialfreak/frontend/src/index.css` – `.calendar`, `.calendarDay`, `.calendarEvent` |
| OPCJA | `socialfreak/web_api.py` – `GET /api/calendar` (łączony endpoint) |

---

### 10.4 Szablony / Saved Replies — Źródło: A.8

**Cel:** Zapisane szablony tekstu (np. nagłówki, stopki, hasztagi). W edytorze posta dropdown „Wstaw szablon” wstawiający treść do textarea.

#### Backend

- **Storage:** `data/templates.json`
  ```json
  [
    {
      “id”: “tpl_uuid”,
      “name”: “Stopka Telegram”,
      “content”: “\n\n@geopolitykapl”,
      “platform”: “telegram”,
      “created_at”: “ISO8601”
    }
  ]
  ```
- **web_api.py:**
  - `GET /api/templates` — lista szablonów (opcjonalnie `?platform=telegram`).
  - `POST /api/templates` Body: `{ “name”: “...”, “content”: “...”, “platform”: “...” }` — tworzy szablon.
  - `PUT /api/templates/{id}` — edycja.
  - `DELETE /api/templates/{id}` — usunięcie.

#### Frontend

- **PostDetail:** Nad textarea dropdown/select „Wstaw szablon” z listą szablonów (filtrowanych po aktywnej platformie). Klik na szablon → wstawienie `template.content` na pozycji kursora (lub na końcu).
- **Osobny widok (opcjonalnie):** „Szablony” w Sidebar → lista szablonów z CRUD (dodaj, edytuj, usuń).

#### Pliki

| Akcja | Ścieżka |
|-------|--------|
| NOWY | `socialfreak/data/templates.json` (pusty `[]`) |
| EDYCJA | `socialfreak/web_api.py` – CRUD templates |
| EDYCJA | `socialfreak/frontend/src/App.jsx` – dropdown „Wstaw szablon” w PostDetail |
| OPCJA | `socialfreak/frontend/src/components/TemplatesView.jsx` – zarządzanie szablonami |
| EDYCJA | `socialfreak/frontend/src/index.css` – `.templateDropdown`, `.templateItem` |

---

## Kolejność wdrożenia (techniczna)

| Krok | Feature | Źródło | Opis |
|------|---------|--------|------|
| 0 | Setup | — | Katalog `socialfreak` + kopia z newsautomation |
| 1 | **Analytics / Historia** | B.4, A.10 | published_store, zapis przy publish, endpointy, HistoryView + Sidebar. Bez refaktoru architektury. |
| 2 | **Auto-tagging** | B.7, A.2 | ask_claude_tags, tags w postach, filtr API, tagi w UI. Wpięcie w istniejący flow. |
| 3 | **Bulk actions** | B.8, A.7 | bulk-adopt, bulk-reject, checkboxi, BulkActionBar. |
| 4 | **Scheduling** | B.1, A.3 | scheduler.py, endpointy schedule/scheduled, worker w main, modal Zaplanuj, ScheduledView. |
| 5 | **Sentiment badge** | B.5 | ask_claude_tone, detect-tone endpoint, badge 🔴🟡🟢 w UI. |
| 6 | **Approval workflow** | A.5, B.9 | status draft/review/approved, PUT status, filtr review, opcjonalnie drugi operator. |
| 7 | **Preview per platform** | A.1, A.6 | PlatformPreviews.jsx (X 280 znaków, FB styl, T bubble). |
| 8 | **Published search** | B.10 | Rozszerzenie list_published (q) i HistoryView. Wymaga #1. |
| 9 | **Recykling/Evergreen** | A.4, B.3 | evergreen w store, recycle endpoint, przyciski Wznów; opcjonalnie auto-recycle po X dniach. |
| 10a | **Best Time** | B.2 | Agregacja godzin publikacji, sugerowana godzina w modalu Zaplanuj. Wymaga #1 + #4. |
| 10b | **RSS** | B.6 | rss_feeds.py, poll loop, posty RSS w pending_adoption. Niezależne. |
| 10c | **Kalendarz** | A.9 | CalendarView.jsx, dane z scheduled + published. Wymaga #1 + #4. |
| 10d | **Szablony** | A.8 | templates.json, CRUD API, dropdown w PostDetail. Niezależne. |

**Zasada:** #1 i #2 są najłatwiejsze do wdrożenia teraz — oba wpinają się w istniejący flow (publish i adopt) bez zmiany architektury.

---

## Zależności między modułami

```
published_store ◄── shared.publish_to_channel()
                ◄── facebook_handlers.publish_to_facebook()
                ◄── web_api (publish_*, GET /api/published)
                ◄── scheduler (po wysłaniu due)

scheduler       ──► published_store (zapis po publish)
                ──► shared.publish_to_channel()
                ──► facebook_handlers.publish_to_facebook()
                ──► pending_posts (odczyt posta do wysłania)

rss_feeds       ──► pending_adoption (wstawianie nowych postów)
                ──► shared.send_preview() (powiadomienie ownera)

ask_claude_tags ◄── web_api.adopt() (przy adopcji)
ask_claude_tone ◄── web_api.detect_tone() (on-demand lub auto)

Frontend        ──► osobne komponenty/widoki w App.jsx:
                    HistoryView, ScheduledView, CalendarView,
                    BulkActionBar, PlatformPreviews, TemplatesView
                    — wspólny stan `view` w App
```

---

## Nowe zależności Python (requirements.txt)

| Paczka | Dla feature'a |
|--------|--------------|
| `feedparser` | #10b RSS |

Pozostałe feature'y korzystają z istniejących zależności (`httpx`, `fastapi`, `uvicorn`, `telethon`).
