import json

import httpx
import pytest

from api import engine_child as engine
from api.errors import AppError


def mock_http(monkeypatch, handler):
    monkeypatch.setattr(engine, "client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))


def note_page(notes):
    state = json.dumps({"note": {"noteDetailMap": {key: {"note": note} for key, note in notes.items()}}})
    return f'<script>window.__INITIAL_STATE__={{"empty":new Set([]),{state[1:]};</script>'


def test_xhs_rednote_redirect_extracts_only_requested_note(monkeypatch):
    title = "undefined and new Set([])"
    signed_path = "/discovery/item/123?xsec_token=a%2Bb&xsec_source=app_share"
    share_url = "https://xhslink.cn/o/example"

    def respond(request):
        if request.url.host == "xhslink.cn":
            return httpx.Response(302, headers={"Location": "https://www.xiaohongshu.com" + signed_path})
        assert request.url.params["xsec_token"] == "a+b"
        if request.url.host == "www.xiaohongshu.com":
            return httpx.Response(302, headers={"Location": "https://www.rednote.com" + signed_path})
        assert request.url.host == "www.rednote.com"
        return httpx.Response(
            200,
            text=note_page(
                {
                    "456": {"title": "推荐视频", "video": {"consumer": {"originVideoKey": "wrong.mp4"}}},
                    "123": {
                        "title": title,
                        "type": "video",
                        "video": {
                            "media": {
                                "stream": {
                                    "h264": [
                                        {
                                            "masterUrl": "http://127.0.0.1/private.mp4",
                                            "backupUrls": ["https://cdn.example/right.mp4"],
                                            "width": 720,
                                            "height": 1280,
                                        }
                                    ]
                                }
                            }
                        },
                    },
                }
            ),
        )

    mock_http(monkeypatch, respond)
    result = engine.resolve_xhs(share_url)
    assert result["public"]["title"] == title
    assert result["private"]["url"] == share_url
    assert [item["quality"] for item in result["public"]["formats"]] == ["720p"]
    assert next(iter(result["private"]["formats"].values()))[0]["url"] == "https://cdn.example/right.mp4"


@pytest.mark.parametrize(
    ("status", "path", "code", "retryable"),
    [
        (200, "/login?redirectPath=%2Fdiscovery%2Fitem%2F123", "AUTH_REQUIRED", False),
        (200, "/404/sec_example", "NOT_FOUND", False),
        (200, "/", "INVALID_INPUT", False),
        (401, "/discovery/item/123", "AUTH_REQUIRED", False),
        (403, "/discovery/item/123", "ACCESS_DENIED", False),
        (429, "/discovery/item/123", "RATE_LIMITED", True),
    ],
)
def test_xhs_landing_reports_upstream_state(monkeypatch, status, path, code, retryable):
    def respond(request):
        if request.url.host == "xhslink.com":
            return httpx.Response(302, headers={"Location": "https://www.rednote.com" + path})
        return httpx.Response(status, text="<html>没有视频</html>")

    mock_http(monkeypatch, respond)
    with pytest.raises(AppError) as error:
        engine.resolve_xhs("https://xhslink.com/o/example")
    assert error.value.code == code
    assert error.value.retryable is retryable


def test_xhs_photo_note_does_not_download_recommended_video(monkeypatch):
    mock_http(
        monkeypatch,
        lambda _: httpx.Response(
            200,
            text=note_page(
                {
                    "123": {"title": "图文", "type": "normal"},
                    "456": {"title": "推荐视频", "video": {"consumer": {"originVideoKey": "wrong.mp4"}}},
                }
            ),
        ),
    )
    with pytest.raises(AppError) as error:
        engine.resolve_xhs("https://www.rednote.com/discovery/item/123")
    assert error.value.code == "UNSUPPORTED"


def test_xhs_missing_note_does_not_download_another_video(monkeypatch):
    mock_http(
        monkeypatch,
        lambda _: httpx.Response(
            200,
            text=note_page(
                {
                    "456": {"title": "推荐视频", "video": {"consumer": {"originVideoKey": "wrong.mp4"}}},
                }
            ),
        ),
    )
    with pytest.raises(AppError) as error:
        engine.resolve_xhs("https://www.xiaohongshu.com/explore/123")
    assert error.value.code == "UPSTREAM_CHANGED"


@pytest.mark.parametrize("entrypoint", ["signed", "short"])
def test_xhs_mobile_fallback_preserves_signed_url(monkeypatch, entrypoint):
    signed_url = "https://www.rednote.com/discovery/item/123?xsec_token=a%2Bb&xsec_source=pc_feed"
    share_url = "https://xhslink.cn/o/example" if entrypoint == "short" else signed_url
    seen = []
    note = {
        "noteId": "123",
        "type": "video",
        "title": "手机网页的视频",
        "user": {"nickName": "作者"},
        "video": {
            "consumer": {"originVideoKey": "blocked.mp4"},
            "media": {
                "stream": {
                    "h265": [{"masterUrl": "https://cdn.example/hevc.mp4"}],
                    "h264": [{"masterUrl": "https://cdn.example/right.mp4"}],
                }
            },
        },
    }
    state = {"noteData": {"data": {"noteData": note}}}

    def respond(request):
        if request.url.host == "xhslink.cn":
            return httpx.Response(302, headers={"Location": signed_url})
        if request.url.path == "/login":
            return httpx.Response(200, text="<html>登录</html>")
        assert str(request.url) == signed_url
        is_mobile = "iPhone" in request.headers["User-Agent"]
        seen.append(is_mobile)
        if not is_mobile:
            return httpx.Response(302, headers={"Location": "/login"})
        return httpx.Response(200, text=f"<script>window.__INITIAL_STATE__={json.dumps(state)}</script>")

    mock_http(monkeypatch, respond)
    result = engine.resolve_xhs(share_url)
    assert seen == [False, True]
    assert result["public"]["title"] == note["title"]
    assert result["public"]["author"] == "作者"
    assert result["private"]["url"] == share_url
    assert [format["codec"] for format in result["public"]["formats"]] == ["h264", "h265"]
    stream = next(iter(result["private"]["formats"].values()))[0]
    assert stream["url"] == "https://cdn.example/right.mp4"
    assert "iPhone" in stream["headers"]["User-Agent"]


def test_xhs_mobile_fallback_rejects_different_note(monkeypatch):
    state = {"noteData": {"data": {"noteData": {"noteId": "456", "type": "video"}}}}

    def respond(request):
        if "iPhone" in request.headers["User-Agent"]:
            return httpx.Response(200, text=f"<script>window.__INITIAL_STATE__={json.dumps(state)}</script>")
        return httpx.Response(401)

    mock_http(monkeypatch, respond)
    with pytest.raises(AppError) as error:
        engine.resolve_xhs("https://www.rednote.com/discovery/item/123?xsec_token=keep")
    assert error.value.code == "UPSTREAM_CHANGED"
