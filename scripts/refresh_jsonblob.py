#!/usr/bin/env python3
"""Ensure Pages has a writable jsonblob URL (free IDs expire ~24h)."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UA = "tz-map-refresh-jsonblob/1.0"
BLOB_RE = re.compile(r"https://jsonblob\.com/api/jsonBlob/[0-9a-f-]+", re.I)


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


def load_seed() -> dict:
    candidates = [
        ROOT / "sync-mirror.json",
        ROOT / "docs" / "sync-mirror.json",
        ROOT / "build" / "sync-mirror.json",
    ]
    seed = {"v": 1, "r": "tz-map-novgorod", "t": 0, "seq": 0, "m": {}}
    for path in candidates:
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(doc, dict) and isinstance(doc.get("m"), dict):
            seed = doc
            break
    # Prefer live Pages mirror when richer/newer.
    try:
        st, live, _ = http_json(
            f"https://ludecani.github.io/tz-map-bothost/sync-mirror.json?_={int(time.time())}"
        )
        if st == 200 and isinstance(live, dict) and isinstance(live.get("m"), dict):
            if len(live["m"]) >= len(seed.get("m") or {}) or int(live.get("t") or 0) >= int(
                seed.get("t") or 0
            ):
                seed = live
    except Exception:
        pass
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
        # Keep DEFAULT assignment coherent if present as bare const.
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


def main() -> int:
    seed = load_seed()
    old = current_url()
    print(f"current={old or '(none)'} seed_keys={len(seed.get('m') or {})}")
    url = old
    alive = False
    if old:
        st, remote, _ = http_json(old + f"?_={int(time.time())}")
        if st == 200 and isinstance(remote, dict) and isinstance(remote.get("m"), dict):
            alive = True
            # Keep blob warm and merge latest mirror seed (inline LWW by `at`).
            out_m = dict(remote.get("m") or {})
            for idx, row in (seed.get("m") or {}).items():
                if not isinstance(row, list) or not row:
                    continue
                prev = out_m.get(str(idx))
                at = int(row[2]) if len(row) > 2 else 0
                prev_at = int(prev[2]) if prev and len(prev) > 2 else 0
                if not prev or at >= prev_at:
                    out_m[str(idx)] = list(row)
            merged = {
                "v": 1,
                "r": seed.get("r") or remote.get("r") or "tz-map-novgorod",
                "t": max(int(seed.get("t") or 0), int(remote.get("t") or 0), int(time.time() * 1000)),
                "seq": max(int(seed.get("seq") or 0), int(remote.get("seq") or 0)),
                "m": out_m,
            }
            if put_blob(old, merged):
                seed = merged
                print(f"refreshed existing blob marks={len(out_m)}")
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
    print(f"done url={url} marks={len(seed.get('m') or {})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
