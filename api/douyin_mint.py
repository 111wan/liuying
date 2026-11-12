"""抖音访客身份铸造:用本机无头 Chrome 访问一次抖音页面,收集 secsdk 生成的 Cookie。

为什么需要浏览器:抖音 detail API 的 Argus 风控要求请求携带由页面
``secsdk``(runtime_bundler_34.js)生成的访客参数 —— 其中 ``uifid`` 必须
来自真实页面会话(服务端校验),纯随机 UUID 会被 ``Validate Error`` 拒绝。
页面还会一并下发 ``s_v_web_id`` / ``ttwid`` / ``odin_tt`` 等身份 Cookie。

铸造出的身份由调用方缓存(见 engine_child 的 ``douyin_identity.json``,
TTL 后重新铸造),签名仍然由 ``api.douyin_sign`` 纯 Python 完成,因此
浏览器只在铸造阶段出现一次,后续解析请求无需浏览器。

CDP 连接只发生在本进程安装网络守卫之前(engine_child.main 的调用顺序),
且仅连接本机调试端口,不经过任何代理。
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import shutil
import subprocess
import tempfile
import time
import urllib.request
from typing import Any

import websockets

from .config import settings

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
)

#: 抖音身份需要的关键 Cookie;铸造结果必须至少包含 uifid 与 ttwid。
WANTED_COOKIES = (
    "ttwid",
    "UIFID_TEMP",
    "UIFID",
    "s_v_web_id",
    "odin_tt",
    "msToken",
    "passport_csrf_token",
    "sid_guard",
)

MINT_TIMEOUT_SECONDS = 55


class MintError(RuntimeError):
    """无法铸造抖音访客身份。"""


def _read_cdp_version(port: int) -> dict[str, Any]:
    """Read Chrome's local CDP endpoint without inheriting system proxies."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
        return json.loads(response.read())


def find_chrome() -> str | None:
    for candidate in CHROME_CANDIDATES:
        if shutil.which(candidate):
            return candidate
    return None


def _mint(port: int, target_url: str, proc: subprocess.Popen) -> dict[str, str]:
    async def run() -> dict[str, str]:
        # 环境中的 socks 代理会让 websockets 尝试 SOCKS 连接,本地 CDP 必须直连。
        for key in ("all_proxy", "ALL_PROXY", "socks_proxy", "SOCKS_PROXY"):
            os.environ.pop(key, None)
        deadline = time.monotonic() + MINT_TIMEOUT_SECONDS
        version: dict[str, Any] | None = None
        while version is None and time.monotonic() < deadline:
            if proc.poll() is not None:
                raise MintError(f"Chrome 提前退出(exit {proc.returncode})")
            try:
                version = await asyncio.to_thread(_read_cdp_version, port)
            except Exception:  # noqa: BLE001 -- 端口未就绪,继续等
                await asyncio.sleep(0.5)
        if version is None:
            raise MintError("Chrome 调试端口未就绪")

        async with websockets.connect(
            version["webSocketDebuggerUrl"], max_size=2**26, proxy=None
        ) as ws:
            seq = 0

            async def call(method: str, params: dict | None = None, session: str | None = None):
                nonlocal seq
                seq += 1
                message: dict[str, Any] = {"id": seq, "method": method}
                if params is not None:
                    message["params"] = params
                if session:
                    message["sessionId"] = session
                await ws.send(json.dumps(message))
                while True:
                    reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.monotonic())))
                    if reply.get("id") == seq:
                        return reply

            created = await call("Target.createTarget", {"url": "about:blank"})
            attached = await call(
                "Target.attachToTarget",
                {"targetId": created["result"]["targetId"], "flatten": True},
            )
            session = attached["result"]["sessionId"]
            await call("Page.enable", session=session)
            await call("Network.enable", session=session)

            # Navigation may wait on redirects; poll cookies while it is in flight.
            seq += 1
            await ws.send(json.dumps({"id": seq, "method": "Page.navigate",
                                      "params": {"url": target_url}, "sessionId": session}))
            cookies: dict[str, str] = {}
            while time.monotonic() < deadline:
                await asyncio.sleep(min(1, max(0, deadline - time.monotonic())))
                reply = await call("Network.getAllCookies", session=session)
                for cookie in reply["result"]["cookies"]:
                    if cookie["domain"].lstrip(".") == "douyin.com" or cookie["domain"].endswith(".douyin.com"):
                        cookies[cookie["name"]] = cookie["value"]
                if cookies.get("ttwid") and (
                    cookies.get("UIFID_TEMP") or cookies.get("UIFID")
                ):
                    break
        return cookies

    return asyncio.run(run())


def mint_identity(target_url: str) -> dict[str, str]:
    """启动一次性无头 Chrome 访问目标页面,返回抖音关键 Cookie。

    返回 dict 至少含 ``ttwid`` 与 ``UIFID_TEMP``(或 ``UIFID``),否则抛
    :class:`MintError`。Chrome 以随机调试端口 + 独立临时 profile 运行,
    结束后立即销毁。
    """
    binary = find_chrome()
    if not binary:
        raise MintError("未找到 Chrome/Chromium,抖音解析需要本机浏览器铸造访客身份")
    port = random.randint(9300, 9900)
    profile = tempfile.mkdtemp(prefix="liuying_dy_mint_")
    proc = subprocess.Popen(
        [
            binary,
            "--headless=new",
            *(["--proxy-server=" + settings().douyin_proxy] if settings().douyin_proxy else []),
            "--no-sandbox",
            "--disable-dev-shm-usage",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--mute-audio",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        cookies = _mint(port, target_url, proc)
    except (TimeoutError, OSError, websockets.exceptions.WebSocketException) as error:
        raise MintError("浏览器连接超时或中断，请重试") from error
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        shutil.rmtree(profile, ignore_errors=True)
    wanted = {name: cookies[name] for name in WANTED_COOKIES if name in cookies}
    if not wanted.get("ttwid") or not (wanted.get("UIFID_TEMP") or wanted.get("UIFID")):
        if not cookies:
            raise MintError(
                "抖音页面未能加载,代理可能不可达。请检查 LIUYING_DOUYIN_PROXY 是否可达,或留空改为直连。"
            )
        raise MintError("页面未生成 uifid/ttwid,铸造失败")
    return wanted


__all__ = ["WANTED_COOKIES", "MintError", "find_chrome", "mint_identity"]
