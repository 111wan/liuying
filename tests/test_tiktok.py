import io
import json
from types import SimpleNamespace

import httpx
import pytest
from yt_dlp.utils import DownloadError

from api import engine_child as engine

POST = "https://www.tiktok.com/@creator/video/6718335390845095173"
CDN = "https://v16-webapp-prime.us.tiktok.com/video.mp4"


def test_tiktok_download_uses_originating_cookies_without_serializing_them(tmp_path, monkeypatch, capsys):
    cookiefile = tmp_path / "cookies.txt"
    original = "# Netscape HTTP Cookie File\n"
    cookiefile.write_text(original, encoding="utf-8")
    config = SimpleNamespace(cookie_file=str(cookiefile), dtk_url="", max_bytes=10_000, max_duration=100)
    monkeypatch.setattr(engine, "settings", lambda: config)
    monkeypatch.setattr(engine, "proxy_url", lambda: "")
    monkeypatch.setattr(engine, "install_network_guard", lambda endpoint: None)
    monkeypatch.setattr(engine.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stderr="Duration: 00:00:03"))
    requests = []
    sessions = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            assert opts["http_headers"]["User-Agent"] == engine.UA
            self._request_director = SimpleNamespace(handlers={})
            self.cookiefile = opts["cookiefile"]
            self.cookies = httpx.Cookies()

        @property
        def cookiejar(self):
            return self.cookies.jar

        def __enter__(self):
            assert self.cookiefile.read() == original
            return self

        def __exit__(self, *_):
            self.cookiefile.write("# job-local update\n")
            for cookie in self.cookiejar:
                cookie.expires = 0

        def extract_info(self, url, download):
            assert url == POST and not download
            sessions.append(f"visitor-{len(sessions) + 1}")
            self.cookies.set("ttwid", sessions[-1], domain=".tiktok.com")
            self.cookies.set("account", "private", domain=".example.com")
            return {
                "title": "TikTok sample",
                "duration": 3,
                "formats": [{
                    "url": CDN, "format_id": "play", "height": 1280, "width": 720, "ext": "mp4",
                    "vcodec": "h264", "acodec": "aac",
                    "http_headers": {"Cookie": "ttwid=stale", "Authorization": "private-header"},
                }],
            }

    def upstream(request):
        requests.append(request)
        if request.url.host == "v16-webapp-prime.us.tiktok.com":
            assert request.headers.get("cookie") == f"ttwid={sessions[-1]}"
            return httpx.Response(302, headers={"Location": "https://media.example.com/video.mp4"})
        assert "cookie" not in request.headers
        return httpx.Response(200, content=b"\x00\x00\x00\x18ftypisom")

    monkeypatch.setattr(engine, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(engine, "client", lambda **_: httpx.Client(transport=httpx.MockTransport(upstream)))

    def run(mode, **kwargs):
        command = {"mode": mode, "directory": str(tmp_path / mode), "platform": "tiktok", "url": POST, **kwargs}
        monkeypatch.setattr(engine.sys, "stdin", io.StringIO(json.dumps(command)))
        engine.main()
        output = capsys.readouterr().out
        assert "visitor-" not in output
        assert "ttwid" not in output
        assert "private-header" not in output
        return json.loads(output.splitlines()[-1])["data"]

    resolved = run("resolve")
    fmt = resolved["public"]["formats"][0]
    finished = run("download", format_id=fmt["id"])
    assert finished["size"] == 12
    assert len(requests) == 2
    assert len(sessions) == 2
    assert cookiefile.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(("detail", "proxied", "code", "guidance"), [
    ("Unexpected response from webpage request", False, "ACCESS_DENIED", "当前服务出口"),
    ("Unable to extract universal data for rehydration", True, "ACCESS_DENIED", "当前服务出口"),
    ("Connection refused", True, "NETWORK_TIMEOUT", "出口代理"),
    ("Log into an account that has access", False, "AUTH_REQUIRED", "要求登录"),
])
def test_tiktok_reports_actionable_extraction_errors(detail, proxied, code, guidance):
    error = engine.tiktok_extraction_error(DownloadError(detail), proxied)
    assert error.code == code
    assert guidance in error.message
