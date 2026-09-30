"""Publish this local instance through its named Cloudflare Tunnel."""

import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "wanxingchen666.xyz"
NAME = "liuying"
LABEL = "com.liuying.tunnel"
CF_DIR = Path.home() / ".cloudflared"


def run(*args, capture=False):
    return subprocess.run(args, check=True, text=True, capture_output=capture)


def main():
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    from api.config import settings

    cfg = settings()
    if not cfg.access_password or not cfg.secure_cookie or DOMAIN not in cfg.allowed_hosts:
        raise SystemExit("请先配置访问密码、Secure Cookie 和正式域名白名单。")
    binary = shutil.which("cloudflared")
    if not binary:
        raise SystemExit("未找到 cloudflared。")
    CF_DIR.mkdir(mode=0o700, exist_ok=True)
    cert = CF_DIR / "cert.pem"
    if not cert.exists():
        downloaded = Path.home() / "Downloads" / "cert.pem"
        if not downloaded.exists():
            raise SystemExit("尚未授权：请运行 cloudflared tunnel login 并完成浏览器授权。")
        if b"BEGIN ARGO TUNNEL TOKEN" not in downloaded.read_bytes():
            raise SystemExit("Downloads/cert.pem 不是 Cloudflare Tunnel 授权证书。")
        shutil.move(str(downloaded), cert)
    cert.chmod(0o600)

    tunnels = json.loads(run(binary, "tunnel", "list", "--output", "json", capture=True).stdout) or []
    matches = [t for t in tunnels if t["name"] == NAME]
    if not matches:
        run(binary, "tunnel", "create", NAME)
        tunnels = json.loads(run(binary, "tunnel", "list", "--output", "json", capture=True).stdout) or []
        matches = [t for t in tunnels if t["name"] == NAME]
    if len(matches) != 1:
        raise SystemExit("无法唯一确定 liuying 隧道，请检查 Cloudflare 隧道列表。")
    tunnel_id = matches[0]["id"]
    credentials = CF_DIR / f"{tunnel_id}.json"
    if not credentials.exists():
        raise SystemExit(f"隧道已存在，但本机缺少凭据文件：{credentials}")
    credentials.chmod(0o600)
    config = CF_DIR / "liuying.yml"
    config.write_text(
        f"tunnel: {json.dumps(tunnel_id)}\n"
        f"credentials-file: {json.dumps(str(credentials))}\n"
        "ingress:\n"
        f"  - hostname: {DOMAIN}\n"
        "    service: http://127.0.0.1:8000\n"
        "  - service: http_status:404\n"
    )
    config.chmod(0o600)
    run(binary, "tunnel", "--config", str(config), "ingress", "validate")
    # Do not overwrite an existing DNS record belonging to another application.
    run(binary, "tunnel", "route", "dns", tunnel_id, DOMAIN)

    logs = ROOT / ".data" / "logs"
    logs.mkdir(mode=0o700, parents=True, exist_ok=True)
    plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [binary, "tunnel", "--config", str(config), "--no-autoupdate", "run", tunnel_id],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "StandardOutPath": str(logs / "tunnel.out.log"),
        "StandardErrorPath": str(logs / "tunnel.err.log"),
    }))
    plist.chmod(0o600)
    target = f"gui/{os.getuid()}"
    loaded = subprocess.run(["launchctl", "print", f"{target}/{LABEL}"], capture_output=True, check=False)
    if loaded.returncode == 0:
        run("launchctl", "bootout", f"{target}/{LABEL}")
        # launchd removes a stopped job asynchronously.
        for _ in range(20):
            stopped = subprocess.run(
                ["launchctl", "print", f"{target}/{LABEL}"], capture_output=True, check=False
            )
            if stopped.returncode != 0:
                break
            time.sleep(0.5)
    run("launchctl", "bootstrap", target, str(plist))
    print(f"隧道及 DNS 已配置：https://{DOMAIN}")
    print("等待连接建立和 DNS 生效后，运行 .venv/bin/python scripts/smoke_public.py 验证。")


if __name__ == "__main__":
    main()
