import json

import httpx
import pytest

from api import engine_child as engine
from api.errors import AppError


@pytest.mark.parametrize(
    ("link", "landing"),
    [
        (
            "https://www.kuaishou.com/short-video/abc?authorId=author123",
            "https://www.kuaishou.com/short-video/abc?authorId=author123",
        ),
        (
            "https://v.kuaishou.com/example",
            "https://www.kuaishou.com/short-video/abc?photoId=abc&userId=author123",
        ),
    ],
)
def test_guest_play_url_with_share_author(monkeypatch, link, landing):
    media_url = "https://cdn.example/video.mp4?token=keep"
    poster_url = "https://cdn.example/cover.jpg"

    def respond(request):
        assert "did=web_" in request.headers.get("cookie", "")
        if request.url.host == "v.kuaishou.com":
            return httpx.Response(302, headers={"Location": landing})
        if request.url.host == "www.kuaishou.com":
            assert str(request.url) == landing
            return httpx.Response(200, text="public video")
        assert request.url.host == "live.kuaishou.com"
        assert request.url.params["photoId"] == "abc"
        assert request.url.params["principalId"] == "author123"
        return httpx.Response(
            200,
            json={
                "data": {
                    "currentWork": {
                        "playUrl": media_url,
                        "photoUrl": poster_url,
                        "poster": poster_url,
                        "width": 720,
                        "height": 1280,
                        "author": {"name": "公开作者"},
                    }
                }
            },
        )

    monkeypatch.setattr(engine, "client", lambda: httpx.Client(transport=httpx.MockTransport(respond)))
    result = engine.resolve_ks(link)
    (fmt,) = result["public"]["formats"]
    assert result["public"]["author"] == "公开作者"
    assert result["private"]["thumbnail"] == poster_url
    assert fmt["id"] == engine.KUAISHOU_GUEST_FORMAT_ID
    assert (fmt["width"], fmt["height"], fmt["quality"]) == (720, 1280, "720p")
    assert fmt["watermark"] == "unknown"
    assert result["private"]["formats"][fmt["id"]][0]["url"] == media_url


@pytest.mark.parametrize("has_requested_photo", [True, False])
def test_mobile_fallback_when_guest_has_no_work(monkeypatch, has_requested_photo):
    link = "https://www.kuaishou.com/short-video/abc?authorId=author123"
    landing = "https://m.gifshow.com/fw/photo/abc?authorId=author123"
    source = "https://txmov2.a.kwimgs.com/video.mp4?clientCacheKey=abc_b.mp4&signature=keep"
    media = [
        {"url": "https://txmov2.a.kwimgs.com/other.mp4?clientCacheKey=other_b.mp4"},
        {"url": "https://other.example/video.mp4?clientCacheKey=abc_b.mp4"},
    ]
    if has_requested_photo:
        media.append({"url": source})
    state = {
        "share-cache-key": {
            "photo": {
                "photoId": "123456",
                "caption": "移动端作品",
                "duration": 9999,
                "width": 720,
                "height": 1280,
                "mainMvUrls": media,
            }
        }
    }
    requested = []

    def respond(request):
        requested.append(str(request.url))
        if str(request.url) == link:
            if request.headers.get("User-Agent") == engine.KUAISHOU_MOBILE_UA:
                return httpx.Response(302, headers={"Location": landing})
            return httpx.Response(200, text="desktop video")
        if str(request.url) == landing:
            assert request.headers["User-Agent"] == engine.KUAISHOU_MOBILE_UA
            return httpx.Response(200, text=f"<script>window.INIT_STATE = {json.dumps(state)}</script>")
        assert request.url.host == "live.kuaishou.com"
        assert request.url.params["principalId"] == "author123"
        return httpx.Response(200, json={"data": {"result": 3}})

    monkeypatch.setattr(engine, "client", lambda: httpx.Client(transport=httpx.MockTransport(respond)))
    if not has_requested_photo:
        with pytest.raises(AppError) as error:
            engine.resolve_ks(link)
        assert error.value.code == "ACCESS_DENIED"
        return

    result = engine.resolve_ks(link)
    assert result["public"]["title"] == "移动端作品"
    assert result["public"]["duration"] == 9.999
    (fmt,) = result["public"]["formats"]
    assert fmt["quality"] == "移动网页 · 720p"
    assert fmt["id"] != engine.KUAISHOU_GUEST_FORMAT_ID
    assert fmt["watermark"] == "unknown"
    assert result["private"]["formats"][fmt["id"]] == [
        {"url": source, "headers": {"Referer": "https://m.gifshow.com/", "User-Agent": engine.KUAISHOU_MOBILE_UA}}
    ]

    requested.clear()
    refreshed = engine.resolve(link, "kuaishou", format_id=fmt["id"])
    assert refreshed["public"]["formats"][0]["id"] == fmt["id"]
    assert requested == [link, landing]

    requested.clear()
    with pytest.raises(AppError) as error:
        engine.resolve(link, "kuaishou", format_id=engine.KUAISHOU_GUEST_FORMAT_ID)
    assert error.value.code == "SOURCE_CHANGED"
    assert landing not in requested
