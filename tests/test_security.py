import ipaddress
import socket

import pytest

from api.errors import AppError
from api.security import extract_url, install_network_guard, public_address, safe_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/a.mp4",
        "http://127.0.0.1/a.mp4",
        "https://10.0.0.1/a.mp4",
        "http://169.254.169.254/latest",
        "http://[::1]/a.mp4",
        "http://[::ffff:127.0.0.1]/a.mp4",
        "http://example.internal/a.mp4",
        "http://example.com:8080/a.mp4",
        "https://user:secret@example.com/a.mp4",
        "http://example.com\\@127.0.0.1/a.mp4",
        "https://example.com/\na.mp4",
    ],
)
def test_unsafe_urls(url):
    with pytest.raises(AppError):
        safe_url(url)


def test_share_text():
    assert extract_url("看看这条作品 https://v.douyin.com/abc/，复制打开") == (
        "https://v.douyin.com/abc/",
        "douyin",
    )
    signed = "https://www.xiaohongshu.com/explore/123?xsec_token=secret&xsec_source=share"
    assert extract_url(signed) == (signed, "xiaohongshu")


def test_platform_boundaries_and_multiple_links():
    for text in [
        "https://douyin.com.evil.example/watch",
        "https://a.example/x.mp4 https://b.example/x.mp4",
        "hello",
    ]:
        with pytest.raises(AppError):
            extract_url(text)


@pytest.mark.parametrize(
    "ip", ["127.0.0.1", "192.168.0.1", "100.64.0.1", "224.0.0.1", "::1", "2002:7f00:1::"]
)
def test_non_public_ips(ip):
    assert not public_address(ipaddress.ip_address(ip))


def test_dns_rebinding_blocked(monkeypatch):
    original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    # Register restoration because install_network_guard mutates these in-place.
    monkeypatch.setattr(socket.socket, "connect", original_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", original_connect_ex)
    install_network_guard()
    with pytest.raises(OSError, match="not public"):
        socket.getaddrinfo("public-looking.example", 443)
    with socket.socket() as sock, pytest.raises(OSError, match="not public"):
        sock.connect(("public-looking.example", 443))


def test_container_rejects_playlist(tmp_path):
    from api.engine_child import media_container

    path = tmp_path / "video.mp4"
    path.write_bytes(b"#EXTM3U\nfile:///etc/passwd")
    with pytest.raises(AppError, match="视频文件"):
        media_container(path)
    path.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 20)
    assert media_container(path) == "mov"
