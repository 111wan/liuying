import json
from types import SimpleNamespace

import httpx
import pytest

from api import engine_child as engine
from api.errors import AppError


def mock_http(monkeypatch, handler):
    monkeypatch.setattr(engine, "client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))


def test_xhs_original_stream_and_undefined(monkeypatch):
    note = {
        "title": "undefined 是标题文字",
        "user": {"nickname": "作者"},
        "video": {
            "consumer": {"originVideoKey": "original.mp4"},
            "media": {
                "stream": {
                    "h264": [{"masterUrl": "https://cdn.example/video.mp4", "width": 1920, "height": 1080}]
                }
            },
        },
    }
    raw = json.dumps({"note": {"noteDetailMap": {"123": {"note": note}}}}, ensure_ascii=False)
    html = "<script>window.__INITIAL_STATE__=" + raw[:-1] + ',"optional":undefined}</script>'
    mock_http(monkeypatch, lambda _: httpx.Response(200, text=html))
    value = engine.resolve_xhs("https://www.xiaohongshu.com/explore/123?xsec_token=keep-me")
    assert value["public"]["title"] == note["title"]
    assert [f["watermark"] for f in value["public"]["formats"]] == ["absent", "unknown"]
    assert "xsec_token=keep-me" in value["private"]["url"]
    assert value["public"]["formats"][1]["quality"] == "1080p"


def test_xhs_requires_valid_ssr(monkeypatch):
    mock_http(monkeypatch, lambda _: httpx.Response(200, text="login required"))
    with pytest.raises(AppError) as error:
        engine.resolve_xhs("https://www.xiaohongshu.com/explore/123")
    assert error.value.code == "AUTH_REQUIRED"


def test_ks_guest_cookie_and_unknown_watermark(monkeypatch):
    def respond(request):
        assert "did=web_" in request.headers.get("cookie", "")
        if "feedbyid" in request.url.path:
            assert request.url.params["photoId"] == "abc"
            return httpx.Response(
                200,
                json={"data": {"currentWork": {"caption": "样本", "mp4Url": "https://cdn.example/a.mp4"}}},
            )
        return httpx.Response(200, text='{"userId":"user123"}')

    mock_http(monkeypatch, respond)
    value = engine.resolve_ks("https://www.kuaishou.com/short-video/abc")
    assert value["public"]["formats"][0]["watermark"] == "unknown"


def test_dtk_watermark_and_media_url_validation():
    content = {
        "title": "样本",
        "media": {
            "video": {"url": "https://cdn.example/video.mp4", "watermark": False},
            "streams": [
                {"url": "https://cdn.example/wm.mp4", "watermark": True},
                {"url": "https://cdn.example/unknown.mp4"},
            ],
        },
    }
    value = engine.resolve_dtk("https://www.douyin.com/video/1", "douyin", content)
    assert [f["watermark"] for f in value["public"]["formats"]] == ["absent", "present", "unknown"]
    content["media"]["video"]["url"] = "http://127.0.0.1/private.mp4"
    with pytest.raises(AppError):
        engine.resolve_dtk("https://www.douyin.com/video/1", "douyin", content)


def test_redirect_removes_credentials(monkeypatch):
    def respond(request):
        if request.url.host == "first.example":
            return httpx.Response(302, headers={"Location": "https://second.example/a.mp4"})
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        return httpx.Response(200, content=b"video")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = engine.response(
            client, "https://first.example/a.mp4", headers={"Cookie": "secret=yes", "Authorization": "secret"}
        )
        assert result.status_code == 200
        result.close()


def test_http_client_loads_session_cookies_and_ignores_expired_entries(monkeypatch, tmp_path):
    cookiefile = tmp_path / "cookies.txt"
    cookiefile.write_text(
        "# Netscape HTTP Cookie File\n"
        ".rednote.com\tTRUE\t/\tTRUE\t0\tsession\tcurrent\n"
        ".rednote.com\tTRUE\t/\tTRUE\t1\texpired\tstale\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(engine, "settings", lambda: SimpleNamespace(cookie_file=str(cookiefile)))
    with engine.client() as client:
        assert client.build_request("GET", "https://www.rednote.com/").headers["cookie"] == "session=current"
        assert "cookie" not in client.build_request("GET", "https://www.xiaohongshu.com/").headers


def test_tiktok_cover_and_media_follow_platform_proxy(monkeypatch, tmp_path):
    proxy = "http://proxy.example:7890"
    monkeypatch.setattr(engine, "settings", lambda: SimpleNamespace(proxy=proxy))
    requests = []

    def make_client(proxy=None):
        def respond(request):
            requests.append((proxy, request.url.host))
            if request.url.path == "/cover.jpg":
                return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=b"cover")
            return httpx.Response(403)

        return httpx.Client(transport=httpx.MockTransport(respond))

    monkeypatch.setattr(engine, "client", make_client)
    data = engine.descriptor(
        "https://www.tiktok.com/@sample/video/123", "tiktok", "样本",
        thumbnail="https://images.example/cover.jpg",
    )
    engine.add_format(data, "test", [{"url": "https://new-cdn.example/video.mp4"}])
    engine.cover(data, tmp_path)
    assert data["public"]["cover"] is True
    with pytest.raises(AppError) as error:
        engine.download(data, data["public"]["formats"][0]["id"], tmp_path)
    assert error.value.code == "SOURCE_EXPIRED"
    assert requests == [(proxy, "images.example"), (proxy, "new-cdn.example")]


def test_direct_head_fallback(monkeypatch):
    def respond(request):
        if request.method == "HEAD":
            return httpx.Response(405)
        return httpx.Response(200, headers={"Content-Type": "video/mp4", "Content-Length": "100"})

    mock_http(monkeypatch, respond)
    value = engine.resolve_direct("https://example.com/a.mp4")
    assert value["public"]["formats"][0]["size_bytes"] == 100
    assert value["public"]["formats"][0]["watermark"] == "unknown"
