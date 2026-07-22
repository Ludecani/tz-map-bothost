#!/usr/bin/env python3
"""Push current jsonblob sync doc into Mail.ru shared folder «Синхронизация».

Requires env:
  MAILRU_LOGIN          full email
  MAILRU_PASSWORD       app password (пароль для внешних приложений)
Optional:
  SYNC_JSONBLOB_URL     default: project blob
  MAILRU_WEBLINK        default: fztm/mjzaGLfJv
  MAILRU_SYNC_NAME      default: sync-state.json
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "tz-map-mailru-sync/1.0"
CLIENT_ID = "cloud-win"
OAUTH_URL = "https://o2.mail.ru/token"
API = "https://cloud.mail.ru/api/v2"
DEFAULT_BLOB = "https://jsonblob.com/api/jsonBlob/019f86c2-5e38-7c3a-be39-75b48e1492d1"
DEFAULT_WEBLINK = "fztm/mjzaGLfJv"
DEFAULT_NAME = "sync-state.json"


def http(url: str, method: str = "GET", data: bytes | None = None, headers: dict | None = None, timeout: int = 60):
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"User-Agent": UA, "Accept": "*/*", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers.items())
    except urllib.error.HTTPError as e:
        return e.code, (e.read() if hasattr(e, "read") else b""), dict(getattr(e, "headers", {}) or {})


def login(email: str, password: str) -> str:
    body = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "username": email,
            "password": password,
        }
    ).encode()
    status, raw, _ = http(
        OAUTH_URL,
        method="POST",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        doc = json.loads(raw.decode("utf-8", "replace"))
    except Exception as e:
        raise SystemExit(f"oauth_bad_json:{status}:{raw[:200]!r}:{e}")
    token = doc.get("access_token")
    if status != 200 or not token:
        err = doc.get("error_description") or doc.get("error") or raw[:200]
        raise SystemExit(f"oauth_failed:{err}")
    return str(token)


def fetch_blob(url: str) -> dict:
    status, raw, _ = http(url + ("&" if "?" in url else "?") + "_=" + str(int(time.time() * 1000)))
    if status != 200:
        raise SystemExit(f"blob_http_{status}:{raw[:200]!r}")
    doc = json.loads(raw.decode("utf-8", "replace"))
    if not isinstance(doc, dict) or not isinstance(doc.get("m"), dict):
        raise SystemExit("blob_bad_doc")
    return {"v": 1, "r": doc.get("r") or "tz-map-novgorod", "t": int(doc.get("t") or time.time() * 1000), "m": doc["m"]}


def upload_hash(token: str, content: bytes) -> str:
    q = urllib.parse.urlencode({"client_id": CLIENT_ID, "token": token})
    shards = []
    st, raw, _ = http(f"{API}/dispatcher?access_token={urllib.parse.quote(token)}")
    if st == 200:
        try:
            body = json.loads(raw.decode("utf-8", "replace")).get("body") or {}
            for key in ("public_upload", "upload"):
                rows = body.get(key) or []
                if isinstance(rows, list) and rows and rows[0].get("url"):
                    shards.append(rows[0]["url"])
                elif isinstance(rows, dict) and rows.get("url"):
                    shards.append(rows["url"])
        except Exception:
            pass
    st, raw, _ = http("https://dispatcher.cloud.mail.ru/u")
    if st == 200:
        word = raw.decode("utf-8", "replace").strip().split()[0]
        if word.startswith("http"):
            shards.append(word)
    shards.extend(
        [
            "https://pu.cloud.mail.ru/upload/?cloud_domain=2",
            "https://uploader.cloud.mail.ru/upload-web/",
            "https://uploader.cloud.mail.ru/upload/",
        ]
    )
    seen = set()
    for shard in shards:
        if not shard or shard in seen:
            continue
        seen.add(shard)
        url = shard if "?" in shard else (shard.rstrip("/") + "/")
        url = url + ("&" if "?" in url else "?") + q
        st, raw, _ = http(
            url,
            method="PUT",
            data=content,
            headers={"Content-Type": "application/octet-stream", "Content-Length": str(len(content))},
            timeout=90,
        )
        text = raw.decode("utf-8", "replace")
        import re

        m = re.search(r"[A-Fa-f0-9]{40}", text)
        if st in (200, 201) and m:
            return m.group(0).upper()
    raise SystemExit("upload_failed")


def form_post(path: str, form: dict) -> tuple[int, dict]:
    data = urllib.parse.urlencode(form).encode()
    st, raw, _ = http(
        API + path,
        method="POST",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        doc = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        doc = {"raw": raw[:300].decode("utf-8", "replace")}
    return st, doc


def register(token: str, file_hash: str, size: int, weblink: str, name: str) -> None:
    homes = []
    st, raw, _ = http(
        f"{API}/folder?weblink={urllib.parse.quote('/' + weblink)}&access_token={urllib.parse.quote(token)}"
    )
    if st == 200:
        try:
            body = json.loads(raw.decode("utf-8", "replace")).get("body") or {}
            if body.get("home"):
                homes.append(str(body["home"]).rstrip("/") + "/" + name)
            if body.get("name"):
                homes.append("/" + str(body["name"]) + "/" + name)
        except Exception:
            pass
    homes.extend(
        [
            f"/{weblink}/{name}",
            f"/Синхронизация/{name}",
        ]
    )

    attempts = [
        ("/weblinks/file/add", {
            "weblink": f"/{weblink}/{name}",
            "hash": file_hash,
            "size": str(size),
            "conflict": "rewrite",
            "upload_type": "manual",
            "api": "2",
            "access_token": token,
            "platform": "desktop_web",
        }),
        ("/weblinks/file/add", {
            "weblink": f"{weblink}/{name}",
            "hash": file_hash,
            "size": str(size),
            "conflict": "rewrite",
            "upload_type": "manual",
            "api": "2",
            "access_token": token,
        }),
        ("/weblinks/file/add", {
            "weblink": f"/{weblink}/",
            "name": name,
            "hash": file_hash,
            "size": str(size),
            "conflict": "rewrite",
            "api": "2",
            "access_token": token,
        }),
    ]
    for home in homes:
        attempts.append(
            (
                "/file/add",
                {
                    "home": home,
                    "hash": file_hash,
                    "size": str(size),
                    "conflict": "rewrite",
                    "api": "2",
                    "access_token": token,
                },
            )
        )

    last = None
    for path, form in attempts:
        st, doc = form_post(path, form)
        last = (st, doc)
        if st == 200 or (isinstance(doc, dict) and doc.get("status") == 200):
            return
    raise SystemExit(f"register_failed:{last}")


def verify_public(weblink: str, name: str) -> bool:
    urls = [
        f"https://cloclo53.cloud.mail.ru/public/{weblink}/{urllib.parse.quote(name)}",
        f"https://cloclo51.cloud.mail.ru/public/{weblink}/{urllib.parse.quote(name)}",
        f"https://cloud.mail.ru/public/{weblink}/{urllib.parse.quote(name)}",
    ]
    for url in urls:
        for _ in range(3):
            st, raw, _ = http(url + "?_=" + str(int(time.time() * 1000)))
            if st == 200:
                try:
                    doc = json.loads(raw.decode("utf-8", "replace"))
                    if isinstance(doc, dict) and isinstance(doc.get("m"), dict):
                        return True
                except Exception:
                    pass
            time.sleep(1.0)
    return False


def main() -> int:
    email = (os.environ.get("MAILRU_LOGIN") or "").strip()
    password = os.environ.get("MAILRU_PASSWORD") or ""
    if not email or not password:
        print("SKIP: set MAILRU_LOGIN and MAILRU_PASSWORD (app password) repository secrets", file=sys.stderr)
        return 0

    blob_url = (os.environ.get("SYNC_JSONBLOB_URL") or DEFAULT_BLOB).strip()
    weblink = (os.environ.get("MAILRU_WEBLINK") or DEFAULT_WEBLINK).strip()
    name = (os.environ.get("MAILRU_SYNC_NAME") or DEFAULT_NAME).strip()

    doc = fetch_blob(blob_url)
    payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    print(f"blob marks={len(doc['m'])} bytes={len(payload)}")

    token = login(email, password)
    print("oauth ok")
    file_hash = upload_hash(token, payload)
    print("upload hash", file_hash)
    register(token, file_hash, len(payload), weblink, name)
    print("registered")
    if not verify_public(weblink, name):
        raise SystemExit("verify_failed: file not visible in public folder")
    print("OK visible in Mail.ru folder", f"https://cloud.mail.ru/public/{weblink}/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# retrigger sync after secrets added
