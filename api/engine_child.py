"""Isolated extractor/downloader. Input JSON on stdin; bounded JSON events on stdout.

No database credentials, browser state, or remote command execution is needed.
Media URLs stay here/on the server; FFmpeg receives local files only.
"""

import hashlib
import http.cookiejar
import io
import json
import os
import random
import re
import shutil
import string
import subprocess
import sys
import time
from copy import copy
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import httpx
import json5
from imageio_ffmpeg import get_ffmpeg_exe
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
from yt_dlp.version import __version__ as YTDLP_VERSION

from .bilibili import BiliBiliCDNIE
from .config import settings
from .douyin_mint import MintError, mint_identity
from .douyin_sign import VERIFY_FP_PARAMS, ABogus, encode_pairs, websign_sign
from .errors import AppError, upstream_error
from .security import PLATFORMS, install_network_guard, safe_url

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# 海外平台:从国内网络直连通常不可达,需要出口代理。
FOREIGN_PLATFORMS = ("youtube", "tiktok", "instagram", "twitter")


def proxy_url():
    """出口代理:显式配置优先,其次继承环境变量 https_proxy / http_proxy。"""
    cfg = settings()
    if cfg.proxy:
        return cfg.proxy
    return os.environ.get("https_proxy") or os.environ.get("http_proxy") or ""


def platform_proxy(platform):
    if platform == "douyin":
        return settings().douyin_proxy or None
    if platform in FOREIGN_PLATFORMS:
        return proxy_url() or None
    return None


def proxy_endpoint(url):
    if not url:
        return None
    parsed = urlsplit(url)
    return (parsed.hostname.lower().rstrip("."), parsed.port or (443 if parsed.scheme == "https" else 80))


def emit(event, **data):
    print(json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)


def client(proxy=None):
    jar = http.cookiejar.MozillaCookieJar()
    cookie_file = settings().cookie_file
    if cookie_file:
        try:
            jar.load(Path(cookie_file).expanduser(), ignore_discard=True, ignore_expires=True)
        except (OSError, UnicodeError):
            raise AppError(
                "COOKIE_CONFIG_INVALID", "服务的 Cookie 文件无法读取，请联系实例管理员检查配置。", 502
            ) from None
        for cookie in jar:
            # Netscape exports may use zero for a session cookie.
            if cookie.expires == 0:
                cookie.expires, cookie.discard = None, True
        jar.clear_expired_cookies()
    options = {
        "timeout": httpx.Timeout(20, connect=10),
        "follow_redirects": False,
        "trust_env": False,
        "headers": {"User-Agent": UA, "Accept-Encoding": "identity"},
        "cookies": jar,
    }
    if proxy:
        options["proxy"] = proxy
    return httpx.Client(**options)


def response(client_, url, method="GET", headers=None, *, allow_statuses=()):
    """Manual redirects, with credential/header stripping across origins."""
    headers = dict(headers or {})
    for _ in range(7):
        safe_url(url)
        req = client_.build_request(method, url, headers=headers)
        res = client_.send(req, stream=True)
        if res.status_code in (301, 302, 303, 307, 308):
            target = urljoin(url, res.headers.get("location", ""))
            res.close()
            if urlsplit(url).netloc != urlsplit(target).netloc:
                headers = {k: v for k, v in headers.items() if k.lower() not in ("authorization", "cookie")}
            url = target
            continue
        if res.status_code >= 400 and res.status_code not in allow_statuses:
            res.close()
            raise AppError(
                "SOURCE_EXPIRED" if res.status_code in (401, 403) else "UPSTREAM_CHANGED",
                "视频源暂时不可访问，请重新解析或稍后重试。",
                502,
                True,
            )
        return res
    raise AppError("INVALID_INPUT", "分享链接跳转次数过多，请使用作品页面链接。")


def read_bounded(res, maximum=5 * 1024 * 1024):
    data = bytearray()
    try:
        for chunk in res.iter_bytes(64 * 1024):
            data.extend(chunk)
            if len(data) > maximum:
                raise AppError("LIMIT_EXCEEDED", "平台响应超出处理上限。", 422)
        return bytes(data)
    finally:
        res.close()


def descriptor(url, platform, title, author="", duration=None, thumbnail=None, adapter=""):
    return {
        "public": {
            "title": str(title or "未命名视频")[:300],
            "author": str(author or "")[:120],
            "platform": platform,
            "duration": duration,
            "formats": [],
            "cover": False,
            "adapter": adapter,
            "resolved_at": time.time(),
        },
        "private": {"url": url, "platform": platform, "formats": {}, "thumbnail": thumbnail},
    }


def add_format(
    data,
    key,
    streams,
    width=None,
    height=None,
    ext="mp4",
    size=None,
    has_audio=None,
    watermark="unknown",
    codec="",
    quality=None,
):
    if not streams:
        return
    for stream in streams:
        safe_url(stream["url"])
    fmt_id = hashlib.sha256(str(key).encode()).hexdigest()[:20]
    ext = ext if ext in ("mp4", "webm", "mov", "m4v", "mkv") else "mkv"
    data["public"]["formats"].append(
        {
            "id": fmt_id,
            "width": width,
            "height": height,
            "ext": ext,
            "quality": quality or (f"{min(width, height)}p" if width and height else "原始画质"),
            "size_bytes": size,
            "size_kind": "estimated" if size else "unknown",
            "has_audio": has_audio,
            "watermark": watermark,
            "codec": codec,
            "requires_mux": len(streams) > 1,
        }
    )
    data["private"]["formats"][fmt_id] = streams


class QuietLog:
    def debug(self, *_):
        pass

    def info(self, *_):
        pass

    def warning(self, *_):
        pass

    def error(self, *_):
        pass


def permitted_format_url(url):
    if not isinstance(url, str):
        return False
    try:
        safe_url(url)
    except AppError:
        return False
    return True


def tiktok_extraction_error(error, proxied):
    detail = str(error).lower()
    if "log in" in detail or "login" in detail:
        return AppError("AUTH_REQUIRED", "TikTok 要求登录后访问这条作品，请在原平台确认访问权限。", 422)
    if proxied and any(term in detail for term in ("connection refused", "proxyerror", "tunnel connection failed")):
        return AppError("NETWORK_TIMEOUT", "连接 TikTok 出口代理失败，请联系管理员检查代理是否可达。", 502, True)
    if any(term in detail for term in (
        "unexpected response from webpage request",
        "unable to extract universal data for rehydration",
        "unable to extract challenge data",
        "unable to solve js challenge",
        "your ip address is blocked",
    )):
        return AppError(
            "ACCESS_DENIED",
            "TikTok 未向当前服务出口返回视频数据，请在原平台确认作品可播放，或联系管理员检查 TikTok 出口。",
            502,
        )
    return upstream_error(error)


def resolve_ytdlp(url, platform, *, tiktok_cookies=None):
    cfg = settings()
    cookiefile = None
    if cfg.cookie_file:
        try:
            # yt-dlp writes its jar on close. Keep each job's updates in memory.
            cookiefile = io.StringIO(Path(cfg.cookie_file).expanduser().read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            raise AppError("COOKIE_CONFIG_INVALID", "服务的 Cookie 文件无法读取，请联系实例管理员检查配置。", 502) from None
    opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": QuietLog(),
        "noplaylist": True,
        "playlistend": 1,
        "socket_timeout": 12,
        "retries": 1,
        "extractor_retries": 0,
        "cachedir": False,
        "cookiefile": cookiefile,
        "js_runtimes": {"node": {}},
        "remote_components": [],
        "extract_flat": False,
    }
    if platform in FOREIGN_PLATFORMS:
        # 海外平台走出口代理;空字符串表示显式直连(与代理未配置时行为一致)。
        opts["proxy"] = proxy_url() or ""
    else:
        opts["proxy"] = ""  # 国内平台保持直连,不走环境代理。
    if platform == "tiktok":
        # The default yt-dlp UA receives a maintenance page on some exits.
        opts["http_headers"] = {"User-Agent": UA}
    with YoutubeDL(opts) as ydl:
        if platform == "bilibili":
            ydl.add_info_extractor(BiliBiliCDNIE())
        # Native curl, external downloaders and websockets do not enter this worker.
        for key in list(ydl._request_director.handlers):
            if key != "Urllib":
                handler = ydl._request_director.handlers.pop(key)
                handler.close()
        try:
            info = ydl.extract_info(url, download=False)
        except DownloadError as error:
            if platform == "tiktok":
                raise tiktok_extraction_error(error, bool(opts["proxy"])) from None
            raise
        if platform == "tiktok" and tiktok_cookies is not None:
            # TikTok signs its CDN URLs for the originating web session. Keep its
            # domain-scoped cookies in the current child, outside media metadata.
            for cookie in ydl.cookiejar:
                domain = cookie.domain.lstrip(".").lower()
                if domain == "tiktok.com" or domain.endswith(".tiktok.com"):
                    tiktok_cookies.set_cookie(copy(cookie))
    if not info or info.get("_type") in ("playlist", "multi_video") or info.get("is_live"):
        raise AppError("UNSUPPORTED", "当前版本只处理单个已发布视频，请使用具体作品链接。", 422)
    duration = info.get("duration")
    if duration and duration > cfg.max_duration:
        limit = cfg.max_duration
        if limit % 3600 == 0:
            label = f"{limit // 3600} 小时"
        elif limit % 60 == 0:
            label = f"{limit // 60} 分钟"
        else:
            label = f"{limit} 秒"
        raise AppError("LIMIT_EXCEEDED", f"当前单条视频时长上限为 {label}。", 422)
    data = descriptor(
        url,
        platform,
        info.get("title"),
        info.get("uploader"),
        duration,
        info.get("thumbnail"),
        f"yt-dlp {YTDLP_VERSION}",
    )
    formats = [
        f
        for f in info.get("formats", [info])
        if permitted_format_url(f.get("url"))
        and f.get("protocol", "https") in ("http", "https")
        and not f.get("has_drm")
        and not f.get("fragments")
    ]
    audio = sorted(
        [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") != "none"],
        key=lambda f: (f.get("ext") == "m4a", f.get("abr") or 0),
        reverse=True,
    )
    videos = sorted(
        [f for f in formats if f.get("vcodec") != "none"],
        key=lambda f: (f.get("height") or 0, str(f.get("vcodec", "")).startswith("avc"), f.get("tbr") or 0),
        reverse=True,
    )
    seen = set()
    for video in videos:
        if len(data["public"]["formats"]) >= 10:
            break
        bucket = (video.get("height"), video.get("ext"))
        if bucket in seen:
            continue
        components = [video]
        if video.get("acodec") == "none":
            if not audio:
                continue
            components.append(audio[0])
        total = sum(f.get("filesize") or f.get("filesize_approx") or 0 for f in components)
        if total > cfg.max_bytes:
            continue
        seen.add(bucket)
        streams = []
        for component in components:
            headers = component.get("http_headers", info.get("http_headers", {}))
            if platform == "tiktok":
                # Only the current download process's cookie jar may send credentials.
                headers = {
                    key: value for key, value in (headers or {}).items()
                    if key.lower() not in ("cookie", "authorization")
                }
            streams.append({"url": component["url"], "headers": headers})
        ext = video.get("ext", "mp4")
        if len(components) > 1 and not (ext == "mp4" and components[1].get("ext") == "m4a"):
            ext = "mkv"
        add_format(
            data,
            "+".join(str(f.get("format_id")) for f in components),
            streams,
            video.get("width"),
            video.get("height"),
            ext,
            total or None,
            len(components) > 1 or video.get("acodec") not in ("none", None),
            codec=video.get("vcodec", ""),
        )
    if not data["public"]["formats"]:
        raise AppError(
            "UNSUPPORTED_FORMAT", "这条作品暂时没有可下载的直连视频格式。直播、DRM 和分片 HLS 暂未开放。", 422
        )
    return data


def resolve_direct(url):
    headers = {"User-Agent": "liuying/0.1"}
    with client() as c:
        try:
            res = response(c, url, "HEAD", headers=headers)
        except AppError as error:
            if error.code != "UPSTREAM_CHANGED":
                raise
            res = response(c, url, headers=headers)  # Some media CDNs do not implement HEAD.
        try:
            size = int(res.headers.get("content-length", "0")) or None
            mime = res.headers.get("content-type", "")
            if "text/html" in mime:
                raise AppError("MEDIA_INVALID", "这个地址返回的是网页，请粘贴作品分享链接。", 422)
            if size and size > settings().max_bytes:
                raise AppError("LIMIT_EXCEEDED", "视频文件超过当前 500 MB 上限。", 422)
        finally:
            res.close()
    title = unquote(Path(urlsplit(url).path).stem)[:160]
    if url == "https://media.w3.org/2010/05/sintel/trailer.mp4":
        title = "Sintel · 官方公开预告片"
    data = descriptor(url, "direct", title, "", adapter="Direct HTTP")
    add_format(
        data,
        "source",
        [{"url": url, "headers": headers}],
        ext=Path(urlsplit(url).path).suffix.lstrip("."),
        size=size,
    )
    return data


# 小红书分享页使用常规浏览器导航请求头。
XHS_PAGE_HEADERS = {
    "User-Agent": UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.xiaohongshu.com/",
}
XHS_MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": XHS_PAGE_HEADERS["Accept-Language"],
    "Accept-Encoding": XHS_PAGE_HEADERS["Accept-Encoding"],
}
XHS_NOTE_PATH = re.compile(r"/(?:explore|discovery/item|user/profile/[^/]+)/([A-Za-z0-9]+)/?")
XHS_INITIAL_STATE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(.*?)</script\s*>", re.DOTALL | re.IGNORECASE)
XHS_STATE_TOKEN = re.compile(
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|(?P<undefined>\bundefined\b)|(?P<empty_set>\bnew\s+Set\(\[\]\))'
)
XHS_FRESH_LINK = "请在小红书 App 中从原笔记重新复制完整分享链接。"


def xhs_auth_required():
    return AppError(
        "AUTH_REQUIRED",
        f"小红书要求登录后查看这条笔记。{XHS_FRESH_LINK}若仍受限，请由实例管理员配置本人的有效登录态。",
        422,
    )


def xhs_initial_state(html):
    match = XHS_INITIAL_STATE.search(html)
    if match is None:
        if html.strip().casefold() == "login required":
            raise xhs_auth_required()
        raise AppError("UPSTREAM_CHANGED", f"小红书未返回笔记页面数据。{XHS_FRESH_LINK}", 502, True)
    # The page serializes missing values and empty Sets as JavaScript expressions.
    # Normalize those literals without touching the title or other quoted fields.
    replacements = {"undefined": "null", "empty_set": "[]"}
    raw = XHS_STATE_TOKEN.sub(
        lambda token: replacements.get(token.lastgroup, token[0]), match[1].strip().rstrip(";")
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            return json5.loads(raw, consume_trailing=False)
        except ValueError:
            raise AppError("UPSTREAM_CHANGED", "小红书的笔记页面数据无法读取，请稍后重试。", 502, True) from None


def xhs_landing_note(res, requested_url):
    landing = urlsplit(str(res.url))
    if res.status_code == 429:
        raise AppError("RATE_LIMITED", "小红书暂时限制请求，请稍后再试。", 429, True)
    host = (landing.hostname or "").lower().rstrip(".")
    if not any(host == domain or host.endswith("." + domain) for domain in ("xiaohongshu.com", "rednote.com")):
        raise AppError("INVALID_INPUT", f"小红书分享链接未进入笔记页面。{XHS_FRESH_LINK}", 422)
    path = landing.path.rstrip("/")
    if path == "/login" or path.startswith("/login/") or res.status_code == 401:
        raise xhs_auth_required()
    if res.status_code == 403 or path.startswith(("/captcha", "/verify", "/website-login")):
        raise AppError("ACCESS_DENIED", f"小红书暂未允许访问这条笔记。{XHS_FRESH_LINK}", 422)
    if res.status_code in (404, 410) or path == "/404" or path.startswith("/404/"):
        raise AppError("NOT_FOUND", f"小红书未能打开这条笔记。{XHS_FRESH_LINK}", 422)
    note = XHS_NOTE_PATH.fullmatch(path)
    if note is None:
        raise AppError("INVALID_INPUT", f"小红书分享链接未跳转到具体笔记。{XHS_FRESH_LINK}", 422)
    requested_note = XHS_NOTE_PATH.fullmatch(urlsplit(requested_url).path)
    if requested_note is not None and note[1] != requested_note[1]:
        raise AppError("NOT_FOUND", f"小红书跳转到了另一条笔记。{XHS_FRESH_LINK}", 422)
    return note[1]


def xhs_note_page(url, page_headers):
    with client() as c:
        res = response(c, url, headers=page_headers, allow_statuses=(401, 403, 404, 410, 429))
        try:
            note_id = xhs_landing_note(res, url)
        except AppError:
            res.close()
            raise
        html = read_bounded(res).decode("utf-8", errors="replace")
    state = xhs_initial_state(html)
    try:
        note = state["note"]["noteDetailMap"][note_id]["note"]
    except (KeyError, TypeError):
        note = None
    if isinstance(note, dict) and note and note.get("noteId", note_id) == note_id:
        return note, res.url, False
    try:
        note = state["noteData"]["data"]["noteData"]
    except (KeyError, TypeError):
        note = None
    if isinstance(note, dict) and note.get("noteId") == note_id:
        return note, res.url, True
    raise AppError("UPSTREAM_CHANGED", f"小红书未返回所链接的笔记。{XHS_FRESH_LINK}", 502, True)


def resolve_xhs(url):
    page_headers = XHS_PAGE_HEADERS
    try:
        note, landing, mobile_note = xhs_note_page(url, page_headers)
    except AppError as error:
        if error.code not in ("AUTH_REQUIRED", "UPSTREAM_CHANGED"):
            raise
        requested = httpx.URL(url)
        signed_note = XHS_NOTE_PATH.fullmatch(requested.path) and requested.params.get("xsec_token")
        share_link = requested.host.lower().rstrip(".") in (
            "xhslink.com", "www.xhslink.com", "xhslink.cn", "www.xhslink.cn",
        )
        if not (signed_note or share_link):
            raise
        # RedNote can send desktop visitors to login while serving the same signed public note on mobile.
        page_headers = {**XHS_MOBILE_HEADERS, "Referer": f"{requested.scheme}://{requested.netloc.decode()}/"}
        note, landing, mobile_note = xhs_note_page(url, page_headers)
    video = note.get("video")
    if not isinstance(video, dict) or not video:
        if note.get("type") == "normal":
            raise AppError("UNSUPPORTED", "这是小红书图文笔记，请使用视频笔记的分享链接。", 422)
        raise AppError("UNSUPPORTED_FORMAT", "小红书未提供这条笔记的可下载视频。", 422)
    images = note.get("imageList") or []
    cover_url = None
    if images:
        cover_url = images[0].get("urlDefault") or images[0].get("url")
    author = note.get("user") or {}
    data = descriptor(
        url,
        "xiaohongshu",
        note.get("title") or note.get("desc"),
        author.get("nickname") or author.get("nickName"),
        thumbnail=cover_url,
        adapter="XHS SSR 1",
    )
    origin = (video.get("consumer") or {}).get("originVideoKey")
    headers = {"Referer": f"{landing.scheme}://{landing.netloc.decode()}/", "User-Agent": page_headers["User-Agent"]}
    # Mobile detail pages can include an origin key whose synthesized CDN URL rejects downloads.
    # Use the signed renditions the mobile page actually exposes.
    if origin and not mobile_note:
        add_format(
            data,
            "origin",
            [{"url": "https://sns-video-bd.xhscdn.com/" + str(origin).lstrip("/"), "headers": headers}],
            watermark="absent",
            quality="无水印原流",
        )
    streams = (video.get("media") or {}).get("stream") or {}
    codecs = sorted(streams, key=lambda codec: codec != "h264") if mobile_note else streams
    for codec in codecs:
        for variant in streams[codec][:6]:
            addresses = [variant.get("masterUrl"), *(variant.get("backupUrls") or [])]
            address = next((address for address in addresses if permitted_format_url(address)), None)
            if address:
                add_format(
                    data,
                    f"{codec}-{variant.get('height')}-{variant.get('videoBitrate')}",
                    [{"url": address, "headers": headers}],
                    variant.get("width"),
                    variant.get("height"),
                    size=variant.get("size"),
                    codec=codec,
                )
    return data


KUAISHOU_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"
)
# Existing tasks use the ID generated from the guest source key.
KUAISHOU_GUEST_FORMAT_ID = hashlib.sha256(b"source").hexdigest()[:20]


def ks_video(url, work, address, headers, adapter, *, duration=None, mobile_photo=None):
    author = work.get("author")
    poster = work.get("poster")
    width, height = work.get("width"), work.get("height")
    if not (type(width) is int and width > 0 and type(height) is int and height > 0):
        width, height = None, None
    data = descriptor(
        url,
        "kuaishou",
        work.get("caption") or work.get("title"),
        work.get("userName") or (author.get("name") if isinstance(author, dict) else None),
        duration=duration,
        thumbnail=poster if permitted_format_url(poster) else None,
        adapter=adapter,
    )
    key = "source"
    quality = None
    if mobile_photo:
        key = f"mobile:{mobile_photo}"
        quality = f"移动网页 · {min(width, height)}p" if width and height else "移动网页"
    add_format(data, key, [{"url": address, "headers": headers}], width=width, height=height, quality=quality)
    return data


def resolve_ks_mobile(url, photo=None):
    headers = {"User-Agent": KUAISHOU_MOBILE_UA}
    try:
        with client() as c:
            res = response(c, url, headers=headers)
            landing = urlsplit(str(res.url))
            host = landing.hostname or ""
            work_path = re.fullmatch(r"/fw/photo/([A-Za-z0-9_-]+)/?", landing.path)
            platform_host = any(
                host == domain or host.endswith("." + domain) for domain in PLATFORMS["kuaishou"][1]
            )
            if not work_path or not platform_host or (photo is not None and work_path[1] != photo):
                res.close()
                return None
            photo = work_path[1]
            html = read_bounded(res).decode("utf-8", errors="replace")
        state_match = re.search(r"window\.INIT_STATE\s*=\s*", html)
        if not state_match:
            return None
        state, _ = json.JSONDecoder().raw_decode(html, state_match.end())
    except (AppError, httpx.HTTPError, OSError, ValueError):
        return None
    if not isinstance(state, dict):
        return None

    for entry in state.values():
        work = entry.get("photo") if isinstance(entry, dict) else None
        if not isinstance(work, dict) or not isinstance(work.get("mainMvUrls"), list):
            continue
        for media in work["mainMvUrls"]:
            address = media.get("url") if isinstance(media, dict) else None
            if not permitted_format_url(address):
                continue
            source = urlsplit(address)
            # The mobile page's photoId is internal. The CDN cache key identifies the public work.
            cache_key = (parse_qs(source.query).get("clientCacheKey") or [""])[0]
            if not re.fullmatch(re.escape(photo) + r"(?:_[A-Za-z0-9-]+)?\.mp4", cache_key):
                continue
            cdn_host = source.hostname or ""
            if not cdn_host.endswith((".kwimgs.com", ".kwaicdn.com")):
                continue
            duration_ms = work.get("duration")
            duration = duration_ms / 1000 if type(duration_ms) is int and duration_ms > 0 else None
            covers = work.get("coverUrls")
            if isinstance(covers, list) and covers and isinstance(covers[0], dict):
                work = work | {"poster": covers[0].get("url")}
            headers["Referer"] = f"{landing.scheme}://{landing.netloc}/"
            return ks_video(
                url, work, address, headers, "Kuaishou mobile SSR", duration=duration, mobile_photo=photo
            )
    return None


def resolve_ks(url, format_id=None):
    if format_id is not None and format_id != KUAISHOU_GUEST_FORMAT_ID:
        mobile = resolve_ks_mobile(url)
        if mobile is None:
            raise AppError("SOURCE_CHANGED", "快手移动网页视频源暂时不可用，请重新解析。", 409)
        return mobile
    with client() as c:
        c.cookies.set("did", "web_" + os.urandom(10).hex(), domain=".kuaishou.com")
        res = response(c, url)
        landing = str(res.url)
        html = read_bounded(res).decode("utf-8", errors="replace")
        query = parse_qs(urlsplit(landing).query)
        photo = (query.get("photoId") or [None])[0]
        if not photo:
            match = re.search(r"/(?:short-video|fw/photo)/([A-Za-z0-9_-]+)", urlsplit(landing).path)
            photo = match[1] if match else None
        principal = (query.get("userId") or query.get("principalId") or query.get("authorId") or [None])[0]
        if not principal:
            match = re.search(r'"(?:userId|principalId)"\s*:\s*"([A-Za-z0-9_-]+)"', html)
            principal = match[1] if match else None
        if not photo:
            raise AppError("INVALID_INPUT", "未识别到快手作品 ID，请从作品页面重新分享。", 422)
        endpoint = httpx.URL(
            "https://live.kuaishou.com/live_api/profile/feedbyid",
            params={"photoId": photo, "principalId": principal or ""},
        )
        body = json.loads(
            read_bounded(response(c, str(endpoint), headers={"Referer": "https://live.kuaishou.com/"}))
        )
    feed = body.get("data") if isinstance(body, dict) else None
    work = feed.get("currentWork") if isinstance(feed, dict) else None
    work = work if isinstance(work, dict) else {}
    extra = work.get("ext_params") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except ValueError:
            extra = {}
    candidates = (
        work.get("mp4Url"),
        work.get("playUrl"),
        work.get("photoUrl"),
        extra.get("mp4Url") if isinstance(extra, dict) else None,
    )
    address = next((url for url in candidates if permitted_format_url(url)), None)
    if address is None:
        if format_id == KUAISHOU_GUEST_FORMAT_ID:
            raise AppError("SOURCE_CHANGED", "快手游客视频源已变化，请重新解析后选择可用版本。", 409)
        fallback = resolve_ks_mobile(url, photo)
        if fallback is not None:
            return fallback
        raise AppError("ACCESS_DENIED", "快手未返回可用视频。请使用新分享链接，或稍后再试。", 422)
    return ks_video(
        url,
        work,
        address,
        {"Referer": "https://live.kuaishou.com/", "User-Agent": UA},
        "Kuaishou guest 2",
    )


def dtk_fetch(url):
    """Only the administrator-configured service origin is called here.

    This runs before the media network guard. No upstream URL from the returned
    data is fetched until the guard is installed. Redirects are never followed.
    """
    cfg = settings()
    with httpx.Client(
        base_url=cfg.dtk_url.rstrip("/"),
        timeout=25,
        trust_env=False,
        follow_redirects=False,
        headers={"X-API-Key": cfg.dtk_api_key},
    ) as c:
        res = c.post("/api/v1/parse", json={"url": url})
        res.raise_for_status()
        body = res.json()
        if not body.get("success"):
            raise AppError("UPSTREAM_CHANGED", "抖音 / TikTok 解析服务暂不可用。", 502, True)
        task_id = body["data"]["task_id"]
        if not re.fullmatch(r"[\w-]{1,80}", task_id):
            raise AppError("UPSTREAM_CHANGED", "解析服务返回了异常任务。", 502)
        for _ in range(45):
            res = c.get(f"/api/v1/tasks/{task_id}")
            res.raise_for_status()
            task = res.json().get("data") or {}
            if task.get("state") == "done":
                return task["data"]
            if task.get("state") == "failed":
                raise AppError("ACCESS_DENIED", "平台未返回视频，请检查原作品及解析服务的访问状态。", 422)
            time.sleep(1)
    raise AppError("NETWORK_TIMEOUT", "平台解析超时，请稍后重试。", 504, True)


def resolve_dtk(url, platform, content):
    if not isinstance(content, dict) or not isinstance(content.get("media"), dict):
        raise AppError("UNSUPPORTED", "链接未返回单个视频，请使用具体作品链接。", 422)
    media = content["media"]
    covers = media.get("covers") or []
    data = descriptor(
        url,
        platform,
        content.get("title"),
        (content.get("author") or {}).get("nickname"),
        (content.get("duration_ms") or 0) / 1000 or None,
        covers[0].get("url") if covers else None,
        "Evil0ctal v5",
    )
    seen = set()
    for index, stream in enumerate(
        ([media["video"]] if media.get("video") else []) + media.get("streams", [])
    ):
        if stream.get("url") in seen:
            continue
        seen.add(stream.get("url"))
        add_format(
            data,
            f"dtk-{index}-{stream.get('height')}",
            [{"url": stream["url"], "headers": {"User-Agent": UA}}],
            stream.get("width"),
            stream.get("height"),
            stream.get("format") or "mp4",
            stream.get("size_bytes"),
            watermark="present"
            if stream.get("watermark") is True
            else "absent"
            if stream.get("watermark") is False
            else "unknown",
        )
    return data


def resolve(url, platform, dtk=None, douyin_identity=None, *, tiktok_cookies=None, format_id=None):
    safe_url(url)
    if platform == "direct":
        data = resolve_direct(url)
    elif platform == "xiaohongshu":
        data = resolve_xhs(url)
    elif platform == "kuaishou":
        data = resolve_ks(url, format_id)
    elif platform == "douyin" and dtk is not None:
        data = resolve_dtk(url, platform, dtk)
    elif platform == "douyin":
        data = resolve_douyin(url, douyin_identity)
    elif dtk is not None:
        data = resolve_dtk(url, platform, dtk)
    elif platform == "tiktok":
        data = resolve_ytdlp(url, platform, tiktok_cookies=tiktok_cookies)
    else:
        data = resolve_ytdlp(url, platform)
    if not data["public"]["formats"]:
        raise AppError("UNSUPPORTED_FORMAT", "该作品没有当前可用的视频格式。", 422)
    if data["public"].get("duration", 0) and data["public"]["duration"] > settings().max_duration:
        raise AppError("LIMIT_EXCEEDED", "视频超过当前时长上限。", 422)
    return data


# ---------------------------------------------------------------------------
# 抖音:无头 Chrome 铸造访客身份 + 纯 Python 原生签名(a_bogus + secsdk websign)
# ---------------------------------------------------------------------------

#: 与签名指纹保持一致的桌面 Chrome 身份(参数值须与 User-Agent 互相印证)。
DOUYIN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
DOUYIN_REFERER = "https://www.douyin.com/"
DOUYIN_IDENTITY_FILE = "douyin_identity.json"
DOUYIN_IDENTITY_TTL = 1200  # 铸造一次身份缓存 20 分钟


def douyin_base_params(aweme_id: str) -> list[tuple[str, str]]:
    return [
        ("device_platform", "webapp"),
        ("aid", "6383"),
        ("channel", "channel_pc_web"),
        ("pc_client_type", "1"),
        ("version_code", "290100"),
        ("version_name", "29.1.0"),
        ("cookie_enabled", "true"),
        ("screen_width", "1920"),
        ("screen_height", "1080"),
        ("browser_language", "zh-CN"),
        ("browser_platform", "Win32"),
        ("browser_name", "Chrome"),
        ("browser_version", "130.0.0.0"),
        ("browser_online", "true"),
        ("engine_name", "Blink"),
        ("engine_version", "130.0.0.0"),
        ("os_name", "Windows"),
        ("os_version", "10"),
        ("cpu_core_num", "12"),
        ("device_memory", "8"),
        ("platform", "PC"),
        ("downlink", "10"),
        ("effective_type", "4g"),
        ("round_trip_time", "0"),
        ("update_version_code", "170400"),
        ("aweme_id", aweme_id),
    ]


def fake_ms_token() -> str:
    alphabet = string.ascii_letters + string.digits + "+-"
    return "".join(random.choices(alphabet, k=126)) + "=="


def load_or_mint_douyin_identity(url: str) -> dict[str, str]:
    """读缓存的身份;过期或缺失时用本机 Chrome 铸造一次。

    铸造需要在网络守卫安装前完成(CDP 走本机回环),因此本函数由
    ``main`` 在 ``install_network_guard`` 之前调用。
    """
    path = settings().data_dir / DOUYIN_IDENTITY_FILE
    now = time.time()
    try:
        if path.exists():
            cached = json.loads(path.read_text())
            cookies = cached.get("cookies") or {}
            if cached.get("expires", 0) > now and cookies.get("ttwid") and (cookies.get("UIFID_TEMP") or cookies.get("UIFID")):
                return cookies
    except (OSError, ValueError):
        pass
    try:
        cookies = mint_identity(url)
    except MintError as error:
        raise AppError(
            "UPSTREAM_CHANGED",
            f"抖音访客身份铸造失败({error})。请确认本机已安装 Chrome/Chromium,"
            "或配置 LIUYING_DTK_URL 使用专用解析服务。",
            502,
            True,
        ) from None
    try:
        path.write_text(json.dumps({"cookies": cookies, "expires": now + DOUYIN_IDENTITY_TTL}))
    except OSError:
        pass  # 缓存失败不影响本次解析
    return cookies


def douyin_signed_detail_url(aweme_id: str, identity: dict[str, str]) -> tuple[str, dict[str, str]]:
    """构造带 a_bogus + secsdk 三件套签名的 detail API 请求 URL 与请求头。"""
    params = douyin_base_params(aweme_id)
    params.append(("msToken", identity.get("msToken") or fake_ms_token()))
    query = encode_pairs(params)
    a_bogus = ABogus(DOUYIN_UA).get_value(query)
    pairs = []
    for part in query.split("&"):
        if not part:
            continue
        name, _, value = part.partition("=")
        pairs.append((unquote(name), unquote(value)))
    pairs.append(("a_bogus", a_bogus))
    uifid = identity.get("UIFID_TEMP") or identity.get("UIFID")
    if not uifid:
        raise AppError("UPSTREAM_CHANGED", "抖音访客身份缺少 uifid,请稍后重试。", 502, True)
    verify_fp = identity.get("s_v_web_id")
    if verify_fp:
        for name in VERIFY_FP_PARAMS:
            pairs.append((name, verify_fp))
    final_query, _, extra_headers = websign_sign(pairs, uifid)
    headers = {
        "User-Agent": DOUYIN_UA,
        "Referer": DOUYIN_REFERER,
        "Accept": "application/json",
        **extra_headers,
    }
    cookie_names = ("ttwid", "s_v_web_id", "odin_tt", "UIFID_TEMP", "UIFID", "msToken")
    cookie = "; ".join(f"{k}={v}" for k, v in identity.items() if k in cookie_names)
    if cookie:
        headers["Cookie"] = cookie
    return f"https://www.douyin.com/aweme/v1/web/aweme/detail/?{final_query}", headers


def resolve_douyin(url: str, identity: dict[str, str] | None):
    if not identity:
        raise AppError("UPSTREAM_CHANGED", "抖音访客身份不可用,请稍后重试。", 502, True)
    with client(proxy=settings().douyin_proxy or None) as c:
        res = response(c, url)
        landing = str(res.url)
        html = read_bounded(res).decode("utf-8", errors="replace")
    match = re.search(r"/(?:video|note)/(\d{10,})", landing)
    aweme_id = match.group(1) if match else None
    if not aweme_id:
        match = re.search(r'"(?:aweme_id|item_id)"\s*:\s*"(\d{10,})"', html) or re.search(
            r"/video/(\d{10,})", html
        )
        aweme_id = match.group(1) if match else None
    if not aweme_id:
        raise AppError("INVALID_INPUT", "未识别到抖音作品 ID,请重新复制完整分享链接。", 422)

    detail_url, headers = douyin_signed_detail_url(aweme_id, identity)
    with client(proxy=settings().douyin_proxy or None) as c:
        res = response(c, detail_url, headers=headers)
        body = read_bounded(res).decode("utf-8", errors="replace")
    try:
        payload = json.loads(body)
    except ValueError:
        raise AppError("UPSTREAM_CHANGED", "抖音未返回视频信息,可能触发风控,请稍后重试。", 502, True) from None
    aweme = payload.get("aweme_detail")
    if not aweme or not aweme.get("video"):
        if aweme and aweme.get("images"):
            raise AppError("UNSUPPORTED", "图文作品暂未支持,请选择视频作品链接。", 422)
        raise AppError(
            "UPSTREAM_CHANGED", "抖音未返回视频信息,可能触发风控,请稍后重试。", 502, True
        )
    video = aweme["video"]
    duration_ms = video.get("duration") or 0
    data = descriptor(
        url,
        "douyin",
        aweme.get("desc") or aweme.get("title"),
        (aweme.get("author") or {}).get("nickname"),
        duration_ms / 1000 or None,
        (video.get("cover") or {}).get("url_list", [None])[0],
        "Douyin native",
    )
    stream_headers = {"User-Agent": DOUYIN_UA, "Referer": DOUYIN_REFERER}
    seen: set[str] = set()

    def push(streams, key, quality, watermark):
        address = (streams or [None])[0]
        if not address or address in seen:
            return
        seen.add(address)
        add_format(
            data,
            key,
            [{"url": address, "headers": stream_headers}],
            quality=quality,
            watermark=watermark,
        )

    for gear in sorted(
        video.get("bit_rate") or [],
        key=lambda g: g.get("bit_rate") or 0,
        reverse=True,
    ):
        height = None
        match = re.search(r"(\d{3,4})", gear.get("gear_name") or "")
        if match:
            height = int(match.group(1))
            if 720 <= height <= 4320 and height % 2 == 0:
                quality = f"{height}p"
            else:
                quality = gear.get("gear_name") or f"{height}p"
        else:
            quality = gear.get("gear_name") or "官方档"
        push(gear.get("play_addr", {}).get("url_list"), f"gear-{gear.get('gear_name')}", quality, "absent")
        if len(data["public"]["formats"]) >= 8:
            break
    push(video.get("play_addr", {}).get("url_list"), "play-addr", "官方原画", "absent")
    push(video.get("download_addr", {}).get("url_list"), "download-addr", "下载版", "present")
    return data


def cover(data, directory):
    url = data["private"].pop("thumbnail", None)
    if not url:
        return
    proxy = platform_proxy(data["public"]["platform"])
    try:
        with client(proxy=proxy) as c:
            res = response(c, url)
            mime = res.headers.get("content-type", "").split(";")[0]
            if mime not in ("image/jpeg", "image/png", "image/webp"):
                res.close()
                return
            content = read_bounded(res, 3 * 1024 * 1024)
        target = directory / "cover.img"
        target.write_bytes(content)
        data["private"]["cover_path"] = str(target)
        data["private"]["cover_mime"] = mime
        data["public"]["cover"] = True
    except (AppError, httpx.HTTPError, OSError, ValueError):
        data["public"]["cover"] = False  # Artwork is optional.


def media_container(path):
    """Reject HTML/playlists before giving any untrusted file to FFmpeg."""
    with path.open("rb") as handle:
        head = handle.read(32)
    if head[4:8] in (b"ftyp", b"moov", b"mdat", b"wide", b"free"):
        return "mov"
    if head.startswith(b"\x1aE\xdf\xa3"):
        return "matroska,webm"
    raise AppError("MEDIA_INVALID", "来源未返回受支持的视频文件，无法保存。", 422)


def download(data, fmt_id, directory, *, tiktok_cookies=None):
    fmt = next((f for f in data["public"]["formats"] if f["id"] == fmt_id), None)
    if not fmt:
        raise AppError("SOURCE_CHANGED", "可用画质发生变化，请重新解析后选择。", 409)
    components = data["private"]["formats"][fmt_id]
    proxy = platform_proxy(data["public"]["platform"])
    paths, received, started, last_event = [], 0, time.monotonic(), 0
    with client(proxy=proxy) as c:
        if tiktok_cookies is not None:
            c.cookies.update(tiktok_cookies)
        for index, stream in enumerate(components):
            res = response(c, stream["url"], headers=stream.get("headers"))
            total = int(res.headers.get("content-length", "0")) or None
            if total and received + total > settings().max_bytes:
                res.close()
                raise AppError("LIMIT_EXCEEDED", "文件超过当前 500 MB 上限。", 422)
            path = directory / f"track-{index}.bin"
            component_bytes = 0
            try:
                with path.open("wb") as handle:
                    for chunk in res.iter_bytes(256 * 1024):
                        received += len(chunk)
                        component_bytes += len(chunk)
                        if received > settings().max_bytes:
                            raise AppError("LIMIT_EXCEEDED", "文件超过当前下载上限。", 422)
                        handle.write(chunk)
                        now = time.monotonic()
                        if now - last_event > 0.5:
                            speed = int(received / max(now - started, 0.01))
                            emit(
                                "progress",
                                stage="fetching",
                                received_bytes=received,
                                total_bytes=total if len(components) == 1 else None,
                                speed_bps=speed,
                            )
                            last_event = now
            finally:
                res.close()
            if not component_bytes or (total and component_bytes != total):
                raise AppError("MEDIA_INVALID", "下载文件不完整，请重新准备。", 502, True)
            media_container(path)
            paths.append(path)
    output = directory / ("video." + fmt["ext"])
    ffmpeg = shutil.which("ffmpeg") or get_ffmpeg_exe()
    if len(paths) > 1:
        emit("progress", stage="muxing")
        subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-format_whitelist",
                media_container(paths[0]),
                "-i",
                str(paths[0]),
                "-protocol_whitelist",
                "file",
                "-format_whitelist",
                media_container(paths[1]),
                "-i",
                str(paths[1]),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c",
                "copy",
                "-y",
                str(output),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
    else:
        paths[0].replace(output)
    emit("progress", stage="verifying")
    # The bundled FFmpeg lets a clean install verify media without system FFprobe.
    probe = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-protocol_whitelist",
            "file",
            "-format_whitelist",
            media_container(output),
            "-i",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    length = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", probe.stderr)
    if not length:
        raise AppError("MEDIA_INVALID", "无法确定文件时长，未通过媒体校验。", 422)
    seconds = float(length[1]) * 3600 + float(length[2]) * 60 + float(length[3])
    if seconds > settings().max_duration:
        raise AppError("LIMIT_EXCEEDED", "视频超过当前时长上限。", 422)
    if output.stat().st_size > settings().max_bytes:
        raise AppError("LIMIT_EXCEEDED", "合并后的文件超过当前下载上限。", 422)
    args = [
        ffmpeg,
        "-nostdin",
        "-v",
        "error",
        "-xerror",
        "-protocol_whitelist",
        "file",
        "-format_whitelist",
        media_container(output),
        "-i",
        str(output),
        "-t",
        "2",
        "-map",
        "0:v:0",
    ]
    if fmt.get("has_audio") is True:
        args += ["-map", "0:a:0"]
    subprocess.run(args + ["-f", "null", "-"], check=True, capture_output=True, timeout=45)
    for path in paths:
        path.unlink(missing_ok=True)
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", data["public"]["title"]).strip(". ")[:100] or "video"
    return {"path": str(output), "filename": f"{title}.{fmt['ext']}", "size": output.stat().st_size}


def main():
    command = json.loads(sys.stdin.readline())
    directory = Path(command["directory"])
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    url, platform = command["url"], command["platform"]
    safe_url(url)
    dtk = dtk_fetch(url) if platform in ("douyin", "tiktok") and settings().dtk_url else None
    # 抖音访客身份必须在网络守卫安装前铸造:CDP 连接走本机回环端口。
    douyin_identity = None
    if platform == "douyin" and dtk is None:
        douyin_identity = load_or_mint_douyin_identity(url)
    install_network_guard(proxy_endpoint(platform_proxy(platform)))
    tiktok_cookies = (
        http.cookiejar.CookieJar()
        if platform == "tiktok" and dtk is None and command["mode"] == "download"
        else None
    )
    data = resolve(
        url, platform, dtk, douyin_identity, tiktok_cookies=tiktok_cookies, format_id=command.get("format_id")
    )
    if command["mode"] == "resolve":
        cover(data, directory)
        emit("result", data=data)
    else:
        previous = command.get("watermark", "unknown")
        fmt = next((f for f in data["public"]["formats"] if f["id"] == command["format_id"]), None)
        if not fmt or (previous == "absent" and fmt["watermark"] != "absent"):
            raise AppError("SOURCE_CHANGED", "视频版本已变化，请重新解析确认画质和水印状态。", 409)
        emit("result", data=download(data, command["format_id"], directory, tiktok_cookies=tiktok_cookies))


if __name__ == "__main__":
    try:
        main()
    except AppError as error:
        emit("error", error=error.public())
        sys.exit(1)
    except subprocess.CalledProcessError:
        emit(
            "error",
            error=AppError(
                "MEDIA_INVALID", "文件未通过媒体校验，可能是平台错误页或不支持的编码。", 422
            ).public(),
        )
        sys.exit(1)
    except Exception as error:  # noqa: BLE001 -- Child process boundary: sanitize upstream failures.
        emit("error", error=upstream_error(error).public())
        sys.exit(1)
