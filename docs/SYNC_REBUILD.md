# Пересборка синхронизации карты ТЗ

## Зачем

Сейчас у карты **несколько независимых «истин»**: jsonblob, bothost `/api/sync/state`, Mail.ru `sync-state.json`, Mantle, статический `sync-mirror.json` на GitHub Pages. Клиент пишет во все сразу и читает «кто первым ответил». Отсюда:

- метки одного ПК не доходят до другого;
- пустой/устаревший снимок **стирает** чужие отметки (prune);
- Action Mail.ru копирует jsonblob → Mail.ru и затирает то, что писали только в Mail.ru;
- кэш Pages / localStorage держит старый билд или старый snap;
- монолитный `index.html` (~580 KB) ломается при правках маркеров (уже теряли `OBSERVATIONS`).

Патчи (#32–#50) лечат симптомы. Нужна **одна модель данных** и поэтапный переход без простоя.

---

## Целевая модель: один лидер + зеркала

```
┌─────────────┐     PATCH /api/sync/ops      ┌──────────────────┐
│  Браузер A  │ ───────────────────────────► │  Bothost server  │  ← SOURCE OF TRUTH
│  Браузер B  │ ◄──── GET ?since=seq ─────── │  data/sync-*.json │
└─────────────┘                              └────────┬─────────┘
                                                      │ периодический mirror
                           ┌──────────────────────────┼──────────────────┐
                           ▼                          ▼                  ▼
                     jsonblob                   Mail.ru folder      sync-mirror.json
                   (backup / RU)               (опц. read)         (Pages, только fill-in)
```

Правила:

1. **Писать можно только в лидер** (bothost). Успех сохранения = HTTP 200 от лидера.
2. **jsonblob** — горячий backup, пишет **сервер** (или клиент только если bothost недоступен).
3. **Mail.ru / Mantle / Pages** — только зеркала. Клиент **никогда** не считает их успехом записи и **никогда** не prune по ним.
4. Конфликт по метке: **last-write-wins по `at`** (уже есть в `_merge_compact`).
5. Снятие отметки — явная операция `status: none` с новым `at`, а не «метки нет в снимке».

---

## Формат данных

Оставляем компактный снимок (совместим с текущим):

```json
{ "v": 1, "r": "tz-map-novgorod", "t": 1784717046568, "seq": 42,
  "m": { "12": [2, "Вова", 1784716234332] } }
```

Коды: `1` = в работе, `2` = готово, `3` = база / спецстатус (как сейчас).

Новый канал операций (поверх снимка):

```http
POST /api/sync/ops
{ "ops": [ { "i": "12", "c": 2, "by": "Вова", "at": 1784716234332 } ], "client": "pc-a" }

→ { "ok": true, "seq": 43, "doc": { ...полный снимок... } }
```

```http
GET /api/sync/ops?since=42
→ { "seq": 43, "changed": true, "doc": { ... } }
```

Пока `ops` лог короткий: сервер сразу мержит в `m` и хранит `seq`. Полный event-log можно добавить позже; для ~200 меток достаточно LWW-снимка + seq.

---

## Клиент: упрощённый цикл

```
клик статуса
  → localStorage + dirty/outbox (мгновенно на UI)
  → POST /api/sync/ops  (или PUT /api/sync/state fallback)
  → только после 200: clear dirty, toast «сохранено»
  → иначе: retry из outbox, toast «нет сети · повтор»

poll каждые 3–4 с
  → GET /api/sync/ops?since=lastSeq  (или GET /api/sync/state)
  → merge LWW в completedMeta
  → prune ТОЛЬКО если ответ от лидера и complete=true
```

Discovery API (как сейчас): `sync-api.json` / `_api` в jsonblob → `apiOrigin`. Без bothost клиент пишет напрямую в jsonblob (единственный fallback-лидер).

---

## План внедрения (без простоя)

### Фаза 0 — уже в этом PR

- Документ архитектуры.
- Сервер: `POST/GET /api/sync/ops` + поле `seq` в состоянии.
- Клиент: запись **сначала bothost, потом jsonblob**; Mail.ru/Mantle только mirror после успеха; prune только после jsonblob/bothost.

### Фаза 1 — стабилизация (следующий шаг)

- Bothost при старте и каждые N минут: sync-state → jsonblob + (опц.) триггер Mail.ru Action.
- Убрать клиентскую запись в Mail.ru/Mantle из hot path (оставить кнопку «зеркалировать» для отладки).
- Явный `status: none` в compact `m` (tombstone), prune по tombstone, не по отсутствию ключа.

### Фаза 2 — разборка монолита

```
index.html          → оболочка + Leaflet UI
js/sync.js          → движок sync (ops/outbox/poll)
data/markers.json   → MARKERS
data/observations.json
data/tz-docs.json
```

Сборка в `build/` + `docs/` для Pages. Правки маркеров больше не рискуют стереть sync/OBSERVATIONS.

### Фаза 3 — UX «ничего не ломается»

- Build stamp + `Cache-Control: no-store` для `index.html` / `sync-*.json`.
- При смене `SYNC_BUILD_STAMP` — сброс только snap-кэша, не outbox.
- Индикатор: `онлайн · bothost · seq N` / `деград · jsonblob` / `офлайн · outbox K`.
- Один канонический URL (без `/m/` плясок): Pages + bothost отдают один и тот же билд.

---

## Что сознательно НЕ делаем

- Не переезжаем на Firebase/Supabase «с нуля» — в RU часто режутся; bothost уже доступен команде.
- Не делаем CRDT — для статусов меток достаточно LWW по `at`.
- Не требуем логин Mail.ru для обычной работы — это было узким местом.

---

## Критерии готовности

| Сценарий | Ожидание |
|----------|----------|
| A ставит «готово», B открыт | B видит за ≤ 1 интервал poll (~4 с) |
| A офлайн, ставит статус | UI сразу; после сети — push из outbox, B видит |
| jsonblob недоступен, bothost есть | Работает через bothost |
| bothost лежит, jsonblob есть | Деград-режим через jsonblob |
| Mail.ru пустой/старый | Не стирает метки ни у кого |
| Новый билд на Pages | Оба ПК после Ctrl+F5 видят один stamp и одни счётчики |

---

## Миграция данных

Текущий `sync-mirror.json` / jsonblob / bothost `m` совместимы 1:1. При первом `POST /api/sync/ops` сервер сидирует из существующих файлов (как `load_sync_state` сейчас) и выставляет `seq=1`.
