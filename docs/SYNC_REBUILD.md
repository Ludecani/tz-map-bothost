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

### Фаза 0 — сделано

- Документ архитектуры.
- Сервер: `POST/GET /api/sync/ops` + поле `seq` в состоянии.
- Клиент: запись **сначала bothost, потом jsonblob**.

### Фаза 1 — сделано

- Bothost при старте и каждые ~2 мин: state → jsonblob + локальный `sync-mirror.json`.
- Клиентская запись в Mail.ru/Mantle убрана из hot path (save/pull).
- Снятие статуса — tombstone `c:0`; **prune по отсутствию ключа отключён**.
- Runtime state хранится в `var/sync-state.json` (не в `data/`).

### Фаза 2 — в процессе

```
index.html              → оболочка + Leaflet UI
js/sync-core.js         → LWW merge helpers
data/markers.js         → MARKERS
data/observations.js
data/tz-docs.js
scripts/publish_static.py → копирует в docs/ + build/
```

Полный вынос UI-связанного sync-движка в `js/sync.js` — следующий шаг.

### Фаза 3 — частично сделано

- Build stamp `v22.07.27:10` + `Cache-Control: no-store` на html/js/json.
- При смене stamp — сброс только snap, outbox сохраняется.
- Индикатор: `онлайн · bothost · N · seq …` / `офлайн · очередь K`.

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
