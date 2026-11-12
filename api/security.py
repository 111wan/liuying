"""URL parsing and a process-local network guard for pure-Python extractor transports."""

import ipaddress
import re
import socket
from urllib.parse import urlsplit

from .errors import AppError

PLATFORMS = {
    "douyin": ("抖音", ("douyin.com", "iesdouyin.com")),
    "kuaishou": ("快手", ("kuaishou.com", "kuaishou.cn", "gifshow.com", "chenzhongtech.com")),
    "xiaohongshu": ("小红书", ("xiaohongshu.com", "rednote.com", "xhslink.com", "xhslink.cn")),
    "bilibili": ("哔哩哔哩", ("bilibili.com", "b23.tv")),
    "youtube": ("YouTube", ("youtube.com", "youtu.be")),
    "tiktok": ("TikTok", ("tiktok.com",)),
    "instagram": ("Instagram", ("instagram.com",)),
    "twitter": ("X", ("x.com", "twitter.com", "t.co")),
}


def safe_url(url: str):
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError
        if parsed.port not in (None, 80, 443):
            raise ValueError
        if any(c.isspace() or ord(c) < 32 for c in url) or "\\" in url:
            raise ValueError
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        if host in ("localhost", "localhost.localdomain") or host.endswith(
            (".local", ".localhost", ".internal")
        ):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not public_address(address):
                raise ValueError
        return parsed
    except (ValueError, UnicodeError):
        raise AppError("INVALID_INPUT", "仅接受公开的 HTTP / HTTPS 视频链接。") from None


def public_address(address):
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif ip.sixtofour or ip.teredo:
            return False
    return ip.is_global and not ip.is_multicast and not ip.is_unspecified


def extract_url(text: str):
    urls = list(dict.fromkeys(re.findall(r"https?://[^\s<>\"'，。；！？（）【】]+", text)))
    urls = [url.rstrip(".,;!?)）]") for url in urls]
    if len(urls) != 1:
        raise AppError("INVALID_INPUT", "请粘贴一条完整的视频分享链接，可以包含分享文案。")
    url = urls[0]
    parsed = safe_url(url)
    host = parsed.hostname.lower().rstrip(".")
    for platform, (_, hosts) in PLATFORMS.items():
        if any(host == item or host.endswith("." + item) for item in hosts):
            return url, platform
    if parsed.path.lower().endswith((".mp4", ".mov", ".webm", ".m4v")):
        return url, "direct"
    raise AppError("UNSUPPORTED", "暂未接入这个来源。支持页面列出了当前可尝试的平台。", 422)


def install_network_guard(proxy_endpoint=None):
    """Installed in an isolated media child, never the API/database process.

    Resolve/check/pin the destination used by connect, including redirects and
    nested requests. Native networking handlers and external downloaders are
    disabled by the caller; those cannot be covered by Python socket hooks.

    ``proxy_endpoint`` is an optional ``(host, port)`` tuple: the only
    non-public destination this process is allowed to dial (e.g. a local
    HTTP proxy used for foreign platforms). Everything else must still
    resolve to a public address on ports 80/443.
    """
    original_resolve = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def checked_resolve(host, port, *args, **kwargs):
        if proxy_endpoint and (
            str(host).lower().rstrip("."),
            int(port),
        ) == proxy_endpoint:
            return original_resolve(host, port, *args, **kwargs)
        entries = original_resolve(host, port, *args, **kwargs)
        if not entries or any(not public_address(entry[4][0]) for entry in entries):
            raise OSError("Network destination is not public")
        return entries

    def pinned(sock, address):
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            raise OSError("Unsupported network family")
        host, port = address[:2]
        if proxy_endpoint and (
            str(host).lower().rstrip("."),
            int(port),
        ) == proxy_endpoint:
            entries = original_resolve(host, int(port), sock.family, socket.SOCK_STREAM)
            return entries[0][4]
        if port not in (80, 443):
            raise OSError("Network port is not permitted")
        entries = checked_resolve(host, port, sock.family, socket.SOCK_STREAM)
        return entries[0][4]

    socket.getaddrinfo = checked_resolve
    socket.socket.connect = lambda sock, address: original_connect(sock, pinned(sock, address))
    socket.socket.connect_ex = lambda sock, address: original_connect_ex(sock, pinned(sock, address))
