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


def form_post(path: str, form: dict, access_token: str | None = None) -> tuple[int, dict, str]:
    data = urllib.parse.urlencode(form).encode()
    url = API + path
    if access_token:
        join = "&" if "?" in url else "?"
        url = f"{url}{join}access_token={urllib.parse.quote(access_token)}"
    st, raw, _ = http(
        url,
        method="POST",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    text = raw.decode("utf-8", "replace")
    try:
        doc = json.loads(text)
    except Exception:
        doc = {"raw": text[:300]}
    return st, doc, text[:300]


def discover_homes(token: str, weblink: str, name: str) -> list[str]:
    homes: list[str] = []

    def add(path: str) -> None:
        path = str(path or "").strip()
        if not path:
            return
        if not path.startswith("/"):
            path = "/" + path
        if path not in homes:
            homes.append(path)

    # Public weblink metadata (often includes real home for the owner).
    st, raw, _ = http(
        f"{API}/folder?weblink={urllib.parse.quote('/' + weblink)}&access_token={urllib.parse.quote(token)}"
    )
    print(f"folder(weblink) status={st}")
    if st == 200:
        try:
            body = json.loads(raw.decode("utf-8", "replace")).get("body") or {}
            print("folder(weblink) keys", sorted(body.keys()))
            if body.get("home"):
                add(str(body["home"]).rstrip("/") + "/" + name)
            if body.get("name"):
                add("/" + str(body["name"]) + "/" + name)
        except Exception as e:
            print("folder(weblink) parse err", e)

    # Scan account root for folder named Синхронизация / matching weblink.
    st, raw, _ = http(
        f"{API}/folder?home={urllib.parse.quote('/')}&access_token={urllib.parse.quote(token)}&limit=500"
    )
    print(f"folder(home=/) status={st}")
    if st == 200:
        try:
            body = json.loads(raw.decode("utf-8", "replace")).get("body") or {}
            for item in body.get("list") or []:
                if not isinstance(item, dict):
                    continue
                item_home = str(item.get("home") or "")
                item_name = str(item.get("name") or "")
                item_wl = str(item.get("weblink") or "")
                if item_wl.replace("/", "") == weblink.replace("/", "") or item_name == "Синхронизация":
                    print("matched folder", item_name, item_home, item_wl)
                    if item_home:
                        add(item_home.rstrip("/") + "/" + name)
                    if item_name:
                        add("/" + item_name + "/" + name)
        except Exception as e:
            print("folder(home=/) parse err", e)

    add(f"/Синхронизация/{name}")
    add(f"/{weblink}/{name}")
    return homes


def register(token: str, file_hash: str, size: int, weblink: str, name: str) -> None:
    homes = discover_homes(token, weblink, name)
    print("home candidates", homes)

    attempts: list[tuple[str, dict]] = []
    # Shared-folder API variants (token in query string).
    for weblink_val in (
        f"/{weblink}/{name}",
        f"{weblink}/{name}",
        f"/{weblink}/",
        weblink,
        f"/{weblink}",
    ):
        form = {
            "weblink": weblink_val,
            "hash": file_hash,
            "size": str(size),
            "conflict": "rewrite",
            "upload_type": "manual",
            "api": "2",
            "platform": "desktop_web",
        }
        if weblink_val.endswith("/"):
            form["name"] = name
        attempts.append(("/weblinks/file/add", form))

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
                },
            )
        )
        # Some clients also send token in form as `token`.
        attempts.append(
            (
                "/file/add",
                {
                    "home": home,
                    "hash": file_hash,
                    "size": str(size),
                    "conflict": "rewrite",
                    "api": "2",
                    "token": token,
                },
            )
        )

    last = None
    for path, form in attempts:
        # Primary: access_token as query param (OAuth / cloud-win).
        st, doc, raw = form_post(path, {k: v for k, v in form.items() if k != "token"}, access_token=token)
        print(f"try {path} q-token -> {st} {doc if isinstance(doc, dict) else raw}")
        last = (st, doc)
        if st == 200 or (isinstance(doc, dict) and doc.get("status") == 200):
            return
        # Secondary: form field token= (web CSRF style) without query auth.
        if "token" in form:
            st2, doc2, raw2 = form_post(path, form, access_token=None)
            print(f"try {path} form-token -> {st2} {doc2 if isinstance(doc2, dict) else raw2}")
            last = (st2, doc2)
            if st2 == 200 or (isinstance(doc2, dict) and doc2.get("status") == 200):
                return
    raise SystemExit(f"register_failed:{last}")


def verify_public(weblink: str, name: str, token: str = "") -> bool:
    # Content is served via /weblink/view/, not /public/ (that path 404s for this folder).
    urls = [
        f"https://cloclo52.cloud.mail.ru/weblink/view/{weblink}/{urllib.parse.quote(name)}",
        f"https://cloclo53.cloud.mail.ru/weblink/view/{weblink}/{urllib.parse.quote(name)}",
        f"https://cloclo61.cloud.mail.ru/weblink/view/{weblink}/{urllib.parse.quote(name)}",
        f"https://cloclo64.cloud.mail.ru/weblink/view/{weblink}/{urllib.parse.quote(name)}",
        f"https://cloclo21.cloud.mail.ru/weblink/view/{weblink}/{urllib.parse.quote(name)}",
    ]
    for url in urls:
        for _ in range(3):
            st, raw, _ = http(url + "?_=" + str(int(time.time() * 1000)))
            print(f"verify view {url} -> {st}")
            if st == 200:
                try:
                    doc = json.loads(raw.decode("utf-8", "replace"))
                    if isinstance(doc, dict) and isinstance(doc.get("m"), dict):
                        return True
                except Exception:
                    pass
            time.sleep(0.5)
    # Fallback: folder listing already shows the file (auth optional).
    folder_urls = [
        f"{API}/folder?weblink={urllib.parse.quote('/' + weblink)}",
        f"{API}/folder?weblink={urllib.parse.quote(weblink)}",
    ]
    if token:
        folder_urls = [
            u + f"&access_token={urllib.parse.quote(token)}" for u in folder_urls
        ] + folder_urls
    for folder_url in folder_urls:
        st, raw, _ = http(folder_url)
        print(f"verify folder -> {st}")
        if st != 200:
            continue
        try:
            body = json.loads(raw.decode("utf-8", "replace")).get("body") or {}
            for item in body.get("list") or []:
                if isinstance(item, dict) and item.get("name") == name:
                    print("verify folder: found", name)
                    return True
        except Exception as e:
            print("verify folder parse err", e)
    return False


def _env_first(*names: str) -> str:
    for name in names:
        val = os.environ.get(name)
        if val is None:
            continue
        val = str(val).strip()
        if val:
            return val
    return ""


def main() -> int:
    email = _env_first("MAILRU_LOGIN", "MAILRU_EMAIL", "MAIL_LOGIN")
    password = _env_first("MAILRU_PASSWORD", "MAILRU_PASS", "MAILRU_APP_PASSWORD", "MAIL_PASSWORD")
    if not email or not password:
        print(
            "ERROR: secrets empty. Add Repository secrets MAILRU_LOGIN and MAILRU_PASSWORD at "
            "https://github.com/Ludecani/tz-map-bothost/settings/secrets/actions",
            file=sys.stderr,
        )
        return 2

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
    if not verify_public(weblink, name, token):
        raise SystemExit("verify_failed: file not visible via weblink/view or folder list")
    print("OK visible in Mail.ru folder", f"https://cloud.mail.ru/public/{weblink}/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# retrigger sync after secrets added
