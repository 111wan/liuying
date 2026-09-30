from copy import deepcopy
from types import SimpleNamespace

import pytest
from yt_dlp import YoutubeDL
from yt_dlp.extractor.bilibili import BiliBiliIE

from api import engine_child as engine
from api.bilibili import BiliBiliCDNIE
from api.errors import AppError

VIDEO_URL = "https://www.bilibili.com/video/BV1uzhX6LEVa/"
VIDEO_CDN = "https://upos.example/video.m4s?signature=keep%2Bencoded&expires=123"
AUDIO_CDN = "https://upos.example/audio.m4s?signature=audio%2Bencoded&expires=123"


def play_info(base_key="baseUrl", backup_key="backupUrl"):
    return {
        "dash": {
            "video": [{
                "id": 80,
                "width": 1920,
                "height": 1080,
                "mimeType": "video/mp4",
                "codecs": "avc1.640028",
                base_key: "https://edge.example:4483/video.m4s",
                backup_key: [VIDEO_CDN],
            }],
            "audio": [{
                "id": 30280,
                "mimeType": "audio/mp4",
                "codecs": "mp4a.40.2",
                base_key: "https://edge.example:8082/audio.m4s",
                backup_key: [AUDIO_CDN],
            }],
        },
    }


def formats_for(payload):
    with YoutubeDL({"quiet": True, "cachedir": False}, auto_init=False) as ydl:
        return BiliBiliCDNIE(ydl).extract_formats(payload)


@pytest.mark.parametrize("base_key,backup_key", [
    ("baseUrl", "backupUrl"),
    ("base_url", "backup_url"),
    ("url", "backupUrl"),
])
def test_dash_video_and_audio_use_supplied_safe_backups_without_mutating_input(base_key, backup_key):
    payload = play_info(base_key, backup_key)
    original = deepcopy(payload)

    formats = formats_for(payload)

    assert payload == original
    assert {f["url"] for f in formats} == {VIDEO_CDN, AUDIO_CDN}
    assert next(f for f in formats if f["vcodec"] != "none")["height"] == 1080
    assert next(f for f in formats if f["vcodec"] == "none")["acodec"] == "mp4a.40.2"


def test_safe_primary_is_preserved():
    payload = play_info()
    payload["dash"]["video"][0]["baseUrl"] = "https://primary.example/video.m4s"
    payload["dash"]["audio"][0]["baseUrl"] = "https://primary.example/audio.m4s"

    assert {f["url"] for f in formats_for(payload)} == {
        "https://primary.example/video.m4s", "https://primary.example/audio.m4s",
    }


def test_missing_upstream_formats_preserve_platform_access_handling():
    assert formats_for({}) == []


@pytest.mark.parametrize("bad_backup", [
    "http://localhost/private",
    "http://127.0.0.1/private",
    "http://10.0.0.1/private",
    "http://169.254.169.254/latest",
    "http://[::1]/private",
    "https://cdn.example:8082/video.m4s",
    "https://user:password@cdn.example/video.m4s",
])
def test_unsafe_backup_is_skipped_for_a_later_safe_candidate(bad_backup):
    payload = play_info()
    payload["dash"]["video"][0]["backupUrl"].insert(0, bad_backup)
    payload["dash"]["audio"][0]["backupUrl"].insert(0, bad_backup)

    assert {f["url"] for f in formats_for(payload)} == {VIDEO_CDN, AUDIO_CDN}


def test_adapter_rejects_tracks_without_any_safe_candidate():
    payload = play_info()
    for track in payload["dash"]["video"] + payload["dash"]["audio"]:
        track["backupUrl"] = ["http://127.0.0.1/private", "https://edge.example:8082/file"]

    with pytest.raises(AppError) as error:
        formats_for(payload)
    assert error.value.code == "UNSUPPORTED_FORMAT"


def test_application_registers_the_adapter_for_bv_urls(monkeypatch):
    def extract(self, url):
        return {
            "id": "BV1uzhX6LEVa", "title": "Bilibili CDN regression", "duration": 12,
            "formats": self.extract_formats(play_info()),
        }

    monkeypatch.setattr(BiliBiliCDNIE, "_real_extract", extract)
    result = engine.resolve_ytdlp(VIDEO_URL, "bilibili")

    assert result["public"]["title"] == "Bilibili CDN regression"
    assert len(result["public"]["formats"]) == 1
    assert result["public"]["formats"][0]["requires_mux"] is True
    streams = next(iter(result["private"]["formats"].values()))
    assert {stream["url"] for stream in streams} == {VIDEO_CDN, AUDIO_CDN}


def test_adapter_keeps_the_key_used_by_extractor_redirects(monkeypatch):
    monkeypatch.setattr(BiliBiliCDNIE, "_real_extract", lambda self, url: {
        "id": "BV1uzhX6LEVa", "title": "redirect reached adapter", "url": VIDEO_CDN,
    })
    with YoutubeDL({"quiet": True, "cachedir": False}) as ydl:
        adapter = BiliBiliCDNIE()
        ydl.add_info_extractor(adapter)
        assert ydl.get_info_extractor(BiliBiliIE.ie_key()) is adapter
        result = ydl.extract_info(VIDEO_URL, download=False, ie_key=BiliBiliIE.ie_key())

    assert result["title"] == "redirect reached adapter"


def fake_extraction(monkeypatch, formats):
    class FakeYoutubeDL:
        def __init__(self, opts):
            self._request_director = SimpleNamespace(handlers={})

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def add_info_extractor(self, extractor):
            pass

        def extract_info(self, url, download=False):
            return {"id": "regression", "title": "format selection", "formats": formats}

    monkeypatch.setattr(engine, "YoutubeDL", FakeYoutubeDL)


def test_bad_preferred_sources_do_not_hide_safe_same_resolution_fallback(monkeypatch):
    fake_extraction(monkeypatch, [
        {
            "url": "https://edge.example:4483/video.mp4", "format_id": "bad-video",
            "height": 1080, "width": 1920, "ext": "mp4", "vcodec": "avc1", "acodec": "none",
        },
        {
            "url": VIDEO_CDN, "format_id": "good-video", "height": 1080,
            "width": 1920, "ext": "mp4", "vcodec": "hev1", "acodec": "none",
        },
        {
            "url": "http://127.0.0.1/audio.m4a", "format_id": "bad-audio",
            "ext": "m4a", "vcodec": "none", "acodec": "mp4a", "abr": 192,
        },
        {
            "url": AUDIO_CDN, "format_id": "good-audio", "ext": "m4a",
            "vcodec": "none", "acodec": "mp4a", "abr": 64,
        },
    ])

    result = engine.resolve_ytdlp(VIDEO_URL, "bilibili")

    assert len(result["public"]["formats"]) == 1
    assert result["public"]["formats"][0]["has_audio"] is True
    streams = next(iter(result["private"]["formats"].values()))
    assert {stream["url"] for stream in streams} == {VIDEO_CDN, AUDIO_CDN}


def test_all_unsafe_formats_report_unavailable_media_not_bad_user_input(monkeypatch):
    fake_extraction(monkeypatch, [{
        "url": "https://edge.example:4483/video.mp4", "format_id": "bad-video",
        "height": 1080, "width": 1920, "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a",
    }])

    with pytest.raises(AppError) as error:
        engine.resolve_ytdlp(VIDEO_URL, "bilibili")
    assert error.value.code == "UNSUPPORTED_FORMAT"


def test_video_requiring_audio_is_not_offered_when_audio_sources_are_unsafe(monkeypatch):
    fake_extraction(monkeypatch, [
        {
            "url": VIDEO_CDN, "format_id": "good-video", "height": 1080,
            "width": 1920, "ext": "mp4", "vcodec": "avc1", "acodec": "none",
        },
        {
            "url": "https://edge.example:8082/audio.m4a", "format_id": "bad-audio",
            "ext": "m4a", "vcodec": "none", "acodec": "mp4a", "abr": 192,
        },
    ])

    with pytest.raises(AppError) as error:
        engine.resolve_ytdlp(VIDEO_URL, "bilibili")
    assert error.value.code == "UNSUPPORTED_FORMAT"
