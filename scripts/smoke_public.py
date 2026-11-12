"""Verify the HTTPS deployment without logging passwords, cookies, or download tickets."""

import argparse
import json
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

# Support both `python scripts/smoke_public.py` and `python -m scripts.smoke_public`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.config import Settings


class SmokeFailure(Exception):
    """A deliberately sanitized check failure safe to print."""


def check(condition, message):
    if not condition:
        raise SmokeFailure(message)


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.urls.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet" and attrs.get("href"):
            self.urls.append(attrs["href"])


def request(client, method, path, expected, label, **kwargs):
    response = client.request(method, path, **kwargs)
    check(response.status_code == expected, f"{label}: expected HTTP {expected}, got {response.status_code}")
    return response


def login(client, password):
    response = request(client, "POST", "/api/v1/login", 303, "login", data={"password": password})
    check(response.headers.get("location") == "/", "login did not succeed")
    auth = next((cookie for cookie in response.cookies.jar if cookie.name == "liuying_auth"), None)
    check(auth is not None, "login did not set the authentication cookie")
    check(auth.secure and auth.has_nonstandard_attr("HttpOnly"), "auth cookie lacks Secure or HttpOnly")


def wait_job(client, job):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        state = request(client, "GET", "/api/v1/jobs/" + job["id"], 200, "job status").json()
        check(state["status"] not in ("failed", "cancelled"), "sample job failed or was cancelled")
        if state["status"] == "ready":
            return state
        time.sleep(0.5)
    raise SmokeFailure("sample job timed out after 180 seconds")


def download_sample(client, info, password):
    client.headers["X-CSRF-Token"] = info["csrf_token"]
    queued = request(
        client, "POST", "/api/v1/resolutions", 202, "sample resolution", json={"text": info["sample_url"]}
    ).json()
    resolved = wait_job(client, queued)
    media_path = "/api/v1/media/" + resolved["result"]["media_id"]
    media = request(client, "GET", media_path, 200, "sample metadata").json()
    queued = request(
        client,
        "POST",
        "/api/v1/downloads",
        202,
        "sample download",
        json={"media_id": media["id"], "format_id": media["formats"][0]["id"]},
    ).json()
    downloaded = wait_job(client, queued)
    ticket = request(
        client,
        "POST",
        "/api/v1/artifacts/" + downloaded["result"]["artifact_id"] + "/download-ticket",
        200,
        "download ticket",
    ).json()["url"]
    check(ticket.startswith("/api/v1/files/"), "download ticket is not a local file URL")
    response = request(client, "GET", ticket, 200, "sample file")
    check(len(response.content) == downloaded["result"]["size_bytes"], "sample file size mismatch")
    check(response.content[4:8] == b"ftyp", "sample file is not an MP4")
    partial = request(client, "GET", ticket, 206, "byte range", headers={"Range": "bytes=0-31"})
    check(partial.content == response.content[:32], "byte range content mismatch")
    with httpx.Client(base_url=str(client.base_url), timeout=30, trust_env=False) as other:
        if password:
            request(other, "GET", ticket, 401, "anonymous file protection")
            login(other, password)
        request(other, "GET", "/api/v1/session", 200, "second session")
        request(other, "GET", media_path, 404, "cross-session metadata protection")
        request(other, "GET", ticket, 404, "cross-session file protection")
    return {"sample_bytes": len(response.content), "range": "passed", "cross_session": "blocked"}


def verify(args):
    # Settings() reads .env without creating directories, databases, or signing keys.
    cfg = Settings()
    target = urlsplit(args.base_url)
    check(
        target.scheme == "https"
        and bool(target.hostname)
        and target.username is None
        and target.password is None
        and target.path in ("", "/")
        and not target.query
        and not target.fragment,
        "base URL must be an HTTPS origin without credentials, path, query, or fragment",
    )
    check(target.hostname in cfg.allowed_hosts, "target hostname is not explicitly in LIUYING_ALLOWED_HOSTS")
    password = None if args.anonymous else cfg.access_password
    check(args.anonymous or bool(password), "LIUYING_ACCESS_PASSWORD is empty. Use --anonymous for a public instance.")
    origin = args.base_url.rstrip("/")
    # TLS verification stays enabled; redirects cannot forward credentials to another origin.
    with httpx.Client(base_url=origin, timeout=30, trust_env=False, follow_redirects=False) as client:
        page = request(client, "GET", "/", 200, "anonymous home")
        if password:
            check('name="password"' in page.text and '/api/v1/login' in page.text, "login form is missing")
            request(client, "GET", "/api/v1/session", 401, "anonymous session protection")
            request(client, "GET", "/api/v1/platforms", 401, "anonymous platform protection")
            login(client, password)
            page = request(client, "GET", "/", 200, "authenticated home")
        check('name="password"' not in page.text, "frontend still displays login form")
        health = request(client, "GET", "/api/v1/health", 200, "health").json()
        check(health.get("status") == "ok", "health status is not ok")
        info = request(client, "GET", "/api/v1/session", 200, "session").json()
        check(bool(info.get("csrf_token")), "session has no CSRF token")
        session_cookie = next((cookie for cookie in client.cookies.jar if cookie.name == "liuying_session"), None)
        check(session_cookie is not None, "site did not set the session cookie")
        check(session_cookie.has_nonstandard_attr("HttpOnly"), "session cookie lacks HttpOnly")
        request(client, "GET", "/api/v1/platforms", 200, "platforms")
        assets = Assets()
        assets.feed(page.text)
        asset_urls = [urljoin(origin + "/", url) for url in assets.urls]
        asset = next(
            (
                url for url in asset_urls
                if urlsplit(url).scheme == target.scheme
                and urlsplit(url).netloc == target.netloc
                and urlsplit(url).path.endswith((".js", ".css"))
            ),
            None,
        )
        check(asset is not None, "frontend has no same-origin JavaScript or CSS asset")
        response = request(client, "GET", asset, 200, "frontend asset")
        check(
            bool(response.content)
            and any(kind in response.headers.get("content-type", "") for kind in ("javascript", "text/css")),
            "frontend asset is empty or has the wrong content type",
        )
        result = {
            "https": "passed",
            "access_gate": "anonymous" if args.anonymous else "passed",
            "session_cookie_secure": session_cookie.secure,
            "frontend": "passed",
        }
        if args.download:
            result.update(download_sample(client, info, password))
        print("PASS", json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://wanxingchen666.xyz", help="HTTPS origin in allowed_hosts")
    parser.add_argument("--anonymous", action="store_true", help="verify an instance without a site password")
    parser.add_argument("--download", action="store_true", help="also create sample jobs and verify file download")
    args = parser.parse_args()
    try:
        verify(args)
    except SmokeFailure as error:
        print("FAIL:", error, file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001
        # HTTP exception text can contain signed URLs; validation errors can contain .env values.
        print(f"FAIL: {type(error).__name__}; sensitive diagnostic details omitted", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
