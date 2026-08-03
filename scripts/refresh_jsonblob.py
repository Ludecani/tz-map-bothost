#!/usr/bin/env python3
"""Keep Pages sync channel alive: jsonblob + Mantle + sync-mirror.

Free jsonblob IDs expire ~24h. This job:
1) prefers the live blob as the seed (not a stale local mirror),
2) merges Mantle `_compact` and the Pages mirror (LWW by `at`),
3) refreshes/recreates the blob,
4) writes sync-api.json + sync-mirror.json for GitHub Pages,
5) publishes `_jsonblob` + `_compact` to Mantle so peers discover the channel
   without waiting for a manual redeploy.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UA = "tz-map-refresh-jsonblob/1.1"
BLOB_RE = re.compile(r"https://jsonblob\.com/api/jsonBlob/[0-9a-f-]+", re.I)
MANTLE_ROOM = "https://mantledb.sh/v2/tzmap-public/rooms/tz-map-novgorod"
PAGES_MIRROR = "https://ludecani.github.io/tz-map-bothost/sync-mirror.json"


def http_json(url: str, method: str = "GET", body: bytes | None = None, timeout: int = 30):
    headers = {"Accept": "application/json", "User-Agent": UA}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                parsed = json.loads(raw.decode("utf-8") or "null")
            except Exception:
                parsed = None
            return resp.status, parsed, dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read() if hasattr(e, "read") else b""
        try:
            parsed = json.loads(raw.decode("utf-8") or "null")
        except Exception:
            parsed = None
        return e.code, parsed, dict(e.headers or {})


def empty_doc() -> dict:
    return {"v": 1, "r": "tz-map-novgorod", "t": 0, "seq": 0, "m": {}}


def as_compact(doc) -> dict | None:
    if not isinstance(doc, dict):
        return None
    if isinstance(doc.get("m"), dict):
        return doc
    compact = doc.get("_compact")
    if isinstance(compact, dict) and isinstance(compact.get("m"), dict):
        return compact
    return None


def merge_compact(a: dict, b: dict) -> dict:
    """LWW merge by row `at` (index 2)."""
    out_m: dict = {}
    for src in (a, b):
        for idx, row in (src.get("m") or {}).items():
            if not isinstance(row, list) or not row:
                continue
            key = str(idx)
            prev = out_m.get(key)
            at = int(row[2]) if len(row) > 2 else 0
            prev_at = int(prev[2]) if prev and len(prev) > 2 else 0
            if not prev or at >= prev_at:
                out_m[key] = list(row)
    return {
        "v": 1,
        "r": (b.get("r") or a.get("r") or "tz-map-novgorod"),
        "t": max(int(a.get("t") or 0), int(b.get("t") or 0), int(time.time() * 1000)),
        "seq": max(int(a.get("seq") or 0), int(b.get("seq") or 0)),
        "m": out_m,
    }


def fetch_live_blob(url: str) -> dict | None:
    if not url:
        return None
    try:
        st, remote, _ = http_json(url + f"?_={int(time.time())}")
    except Exception:
        return None
    if st == 200:
        return as_compact(remote)
    return None


def fetch_mantle_compact() -> tuple[dict | None, dict | None]:
    """Return (compact, full_room_or_None)."""
    try:
        st, room, _ = http_json(MANTLE_ROOM + f"?_={int(time.time())}")
    except Exception:
        return None, None
    if st != 200 or not isinstance(room, dict):
        return None, None
    return as_compact(room), room


def fetch_pages_mirror() -> dict | None:
    try:
        st, live, _ = http_json(PAGES_MIRROR + f"?_={int(time.time())}")
    except Exception:
        return None
    if st == 200:
        return as_compact(live)
    return None


def load_local_seed() -> dict:
    for path in (
        ROOT / "sync-mirror.json",
        ROOT / "docs" / "sync-mirror.json",
        ROOT / "build" / "sync-mirror.json",
    ):
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        compact = as_compact(doc)
        if compact:
            return compact
    return empty_doc()


def load_seed(blob_url: str) -> dict:
    """Prefer live blob, then Mantle, then Pages mirror, then local files."""
    seed = empty_doc()
    sources: list[tuple[str, dict | None]] = [
        ("blob", fetch_live_blob(blob_url)),
        ("mantle", fetch_mantle_compact()[0]),
        ("pages", fetch_pages_mirror()),
        ("local", load_local_seed()),
    ]
    for name, doc in sources:
        if not doc:
            print(f"seed:{name}=miss")
            continue
        print(f"seed:{name}=marks:{len(doc.get('m') or {})} seq={doc.get('seq')} t={doc.get('t')}")
        seed = merge_compact(seed, doc) if seed.get("m") else merge_compact(empty_doc(), doc)
    seed["t"] = max(int(seed.get("t") or 0), int(time.time() * 1000))
    seed["seq"] = max(int(seed.get("seq") or 0), 1)
    return seed


def current_url() -> str:
    for path in (ROOT / "sync-api.json", ROOT / "docs" / "sync-api.json"):
        if not path.exists():
            continue
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        u = str((cfg or {}).get("jsonblobUrl") or "").strip()
        if BLOB_RE.fullmatch(u):
            return u
    html = (ROOT / "index.html").read_text(encoding="utf-8", errors="ignore")
    m = BLOB_RE.search(html)
    return m.group(0) if m else ""


def create_blob(doc: dict) -> str:
    body = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    st, parsed, headers = http_json("https://jsonblob.com/api/jsonBlob", method="POST", body=body)
    if st not in (200, 201):
        raise RuntimeError(f"create failed status={st} body={parsed}")
    blob_id = headers.get("X-jsonblob-id") or headers.get("x-jsonblob-id") or ""
    loc = headers.get("Location") or headers.get("location") or ""
    if blob_id:
        return f"https://jsonblob.com/api/jsonBlob/{blob_id}"
    if loc.startswith("/"):
        return "https://jsonblob.com" + loc
    if loc.startswith("http"):
        return loc
    raise RuntimeError("create returned no location")


def put_blob(url: str, doc: dict) -> bool:
    body = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    st, _, _ = http_json(url, method="PUT", body=body)
    return st in (200, 201)


def replace_urls(old: str, new: str) -> None:
    files = [
        ROOT / "index.html",
        ROOT / "docs" / "index.html",
        ROOT / "build" / "index.html",
        ROOT / "server.py",
        ROOT / "build" / "server.py",
        ROOT / "scripts" / "push_mailru_sync.py",
    ]
    for path in files:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        updated = text
        if old:
            updated = updated.replace(old, new)
        updated = BLOB_RE.sub(new, updated)
        if "SYNC_JSONBLOB_URL_DEFAULT" in updated:
            updated = re.sub(
                r"(const SYNC_JSONBLOB_URL_DEFAULT\s*=\s*')[^']+(')",
                r"\1" + new + r"\2",
                updated,
            )
        if "DEFAULT_BLOB" in updated:
            updated = re.sub(
                r'(DEFAULT_BLOB\s*=\s*")[^"]+(")',
                r"\1" + new + r"\2",
                updated,
            )
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            print(f"updated {path.relative_to(ROOT)}")


def write_sync_api(url: str) -> None:
    cfg = {
        "apiOrigin": "",
        "jsonblobUrl": url,
        "updatedAt": int(time.time() * 1000),
        "v": 1,
    }
    text = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"
    for path in (
        ROOT / "sync-api.json",
        ROOT / "docs" / "sync-api.json",
        ROOT / "build" / "sync-api.json",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")


def write_mirrors(doc: dict) -> None:
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    for path in (
        ROOT / "sync-mirror.json",
        ROOT / "docs" / "sync-mirror.json",
        ROOT / "build" / "sync-mirror.json",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def publish_mantle(url: str, compact: dict) -> bool:
    """Publish live blob URL + compact snapshot into Mantle room (read-merge-write)."""
    try:
        st, room, _ = http_json(MANTLE_ROOM + f"?_={int(time.time())}")
    except Exception as exc:
        print(f"mantle read failed: {exc}")
        return False
    doc = room if (st == 200 and isinstance(room, dict)) else {}
    if not isinstance(doc, dict):
        doc = {}
    prev = as_compact(doc) or empty_doc()
    merged = merge_compact(prev, compact)
    out = dict(doc)
    out["v"] = out.get("v") or 3
    out["updatedAt"] = int(time.time() * 1000)
    out["_jsonblob"] = url
    out["_jsonblobAt"] = int(time.time() * 1000)
    out["_compact"] = merged
    body = json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    try:
        st2, _, _ = http_json(MANTLE_ROOM, method="POST", body=body, timeout=40)
    except Exception as exc:
        print(f"mantle write failed: {exc}")
        return False
    ok = st2 in (200, 201)
    print(f"mantle publish status={st2} marks={len(merged.get('m') or {})}")
    return ok


def main() -> int:
    old = current_url()
    seed = load_seed(old)
    print(f"current={old or '(none)'} seed_keys={len(seed.get('m') or {})}")
    url = old
    alive = False
    if old:
        st, remote, _ = http_json(old + f"?_={int(time.time())}")
        if st == 200 and isinstance(remote, dict) and isinstance(remote.get("m"), dict):
            alive = True
            merged = merge_compact(remote, seed)
            if put_blob(old, merged):
                seed = merged
                print(f"refreshed existing blob marks={len(seed.get('m') or {})}")
            else:
                print("warn: put failed; will recreate")
                alive = False
        else:
            print(f"blob dead status={st}")
    if not alive:
        url = create_blob(seed)
        print(f"created {url}")
    write_sync_api(url)
    write_mirrors(seed)
    replace_urls(old, url)
    publish_mantle(url, seed)
    print(f"done url={url} marks={len(seed.get('m') or {})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
