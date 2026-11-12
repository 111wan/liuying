import asyncio
import hashlib
import hmac
import json
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import ROOT, settings
from .db import TERMINAL, Artifact, Job, Media, Session, init_db, snapshot
from .errors import AppError
from .security import PLATFORMS, extract_url
from .worker import STOP, start_supervisor

cfg = settings()
signer = URLSafeTimedSerializer(cfg.secret)
SAMPLE = "https://media.w3.org/2010/05/sintel/trailer.mp4"


@asynccontextmanager
async def lifespan(_):
    init_db()
    thread = start_supervisor()
    yield
    STOP.set()
    await asyncio.to_thread(thread.join, 5)


app = FastAPI(title="留影 API", version="0.1.0", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=cfg.allowed_hosts)


def csrf(owner):
    return hmac.new(cfg.secret.encode(), owner.encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# 访问密码门:LIUYING_ACCESS_PASSWORD 非空时启用。健康检查保持公开,便于存活监控。
# 登录页为纯 HTML 表单(不依赖前端 bundle);登录失败按 IP 限流防爆破。
# ---------------------------------------------------------------------------
AUTH_COOKIE = "liuying_auth"
AUTH_SALT = "access"
LOGIN_ATTEMPTS: dict[str, list[float]] = {}
LOGIN_WINDOW = 600
LOGIN_MAX_ATTEMPTS = 5

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
}


def secure_headers(response):
    for name, value in _SECURITY_HEADERS.items():
        response.headers[name] = value
    return response


def auth_ok(request: Request) -> bool:
    password = cfg.access_password
    if not password:
        return True
    try:
        return signer.loads(
            request.cookies.get(AUTH_COOKIE, ""), salt=AUTH_SALT, max_age=30 * 86400
        ) == hashlib.sha256(password.encode()).hexdigest()
    except BadSignature:
        return False


def login_page(request: Request) -> HTMLResponse:
    message = {"1": "密码不正确，请重试。", "2": "尝试次数过多，请十分钟后再试。"}.get(
        request.query_params.get("err", ""), ""
    )
    error = f'<p class="err">{message}</p>' if message else ""
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>留影 · 访问验证</title>
<style>
body{{font-family:-apple-system,"SF Pro Text","PingFang SC","Helvetica Neue",sans-serif;background:#f5f5f7;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.card{{background:#fff;border-radius:18px;padding:40px 36px;width:300px;text-align:center;box-shadow:0 8px 30px rgba(0,0,0,.08)}}
h1{{font-size:22px;margin:0 0 6px;color:#1d1d1f}}
.sub{{color:#6e6e73;font-size:13px;margin:0 0 20px}}
input{{width:100%;box-sizing:border-box;padding:12px 14px;border:1px solid #d2d2d7;border-radius:12px;font-size:15px;margin-bottom:12px;outline:none}}
input:focus{{border-color:#0071e3;box-shadow:0 0 0 3px rgba(0,113,227,.18)}}
button{{width:100%;background:#0071e3;color:#fff;border:0;border-radius:12px;padding:12px;font-size:15px;cursor:pointer}}
button:hover{{background:#0077ed}}
.err{{color:#d70015;font-size:13px;margin-bottom:12px}}
</style>
</head>
<body>
<div class="card">
<h1>留影</h1>
<p class="sub">输入访问密码以继续</p>
{error}
<form method="post" action="/api/v1/login">
<input type="password" name="password" placeholder="访问密码" autofocus required>
<button type="submit">进入</button>
</form>
</div>
</body>
</html>"""
    return HTMLResponse(html)


async def handle_login(request: Request):
    if request.headers.get("content-type", "").startswith("application/json"):
        body = await request.json()
        password = str(body.get("password", ""))
    else:
        form = await request.form()
        password = str(form.get("password", ""))
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    attempts = [t for t in LOGIN_ATTEMPTS.get(ip, []) if t > now - LOGIN_WINDOW]
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        LOGIN_ATTEMPTS[ip] = attempts
        return secure_headers(RedirectResponse("/?err=2", status_code=303))
    if not hmac.compare_digest(password.encode(), cfg.access_password.encode()):
        attempts.append(now)
        LOGIN_ATTEMPTS[ip] = attempts
        return secure_headers(RedirectResponse("/?err=1", status_code=303))
    LOGIN_ATTEMPTS.pop(ip, None)
    response = secure_headers(RedirectResponse("/", status_code=303))
    response.set_cookie(
        AUTH_COOKIE,
        signer.dumps(hashlib.sha256(cfg.access_password.encode()).hexdigest(), salt=AUTH_SALT),
        httponly=True,
        secure=cfg.secure_cookie and request.url.scheme == "https",
        samesite="strict",
        max_age=30 * 86400,
    )
    return response


@app.middleware("http")
async def session_middleware(request: Request, call_next):
    fresh = False
    try:
        owner = signer.loads(request.cookies.get("liuying_session", ""), salt="session", max_age=30 * 86400)
        if not isinstance(owner, str) or len(owner) != 64:
            raise BadSignature("Invalid session")
    except BadSignature:
        owner, fresh = secrets.token_hex(32), True
    request.state.owner = owner
    if cfg.access_password:
        if request.url.path == "/api/v1/login" and request.method == "POST":
            return await handle_login(request)
        if not auth_ok(request) and request.url.path != "/api/v1/health":
            if request.url.path.startswith("/api/"):
                return secure_headers(
                    JSONResponse(
                        {
                            "error": {
                                "code": "AUTH_REQUIRED",
                                "message": "请先输入访问密码。",
                                "retryable": False,
                            }
                        },
                        401,
                    )
                )
            return secure_headers(login_page(request))
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.url.path.startswith("/api/"):
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf(owner)):
            return JSONResponse(
                {
                    "error": {
                        "code": "SESSION_EXPIRED",
                        "message": "会话已过期，请刷新页面后重试。",
                        "retryable": False,
                    }
                },
                403,
            )
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"error": {"code": "FORBIDDEN", "message": "请求来源不受支持。"}}, 403)
        try:
            content_length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"error": {"code": "INVALID_INPUT", "message": "请求长度无效。"}}, 400)
        if content_length > 16384:
            return JSONResponse({"error": {"code": "LIMIT_EXCEEDED", "message": "输入内容过长。"}}, 413)
    response = await call_next(request)
    if fresh:
        response.set_cookie(
            "liuying_session",
            signer.dumps(owner, salt="session"),
            httponly=True,
            secure=cfg.secure_cookie and request.url.scheme == "https",
            samesite="strict",
            max_age=30 * 86400,
        )
    secure_headers(response)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(AppError)
async def app_error(_, error):
    return JSONResponse({"error": error.public()}, status_code=error.status)


@app.get("/api/v1/session")
def session_info(request: Request):
    return {
        "csrf_token": csrf(request.state.owner),
        "sample_url": SAMPLE,
        "limits": {"max_bytes": cfg.max_bytes, "max_duration": cfg.max_duration},
        "version": "0.1.0",
    }


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "queue_mode": cfg.queue_mode, "version": "0.1.0"}


@app.get("/api/v1/platforms")
def platforms():
    descriptions = {
        "douyin": "本机 Chrome 铸造访客身份 + 原生签名解析(免登录);配置专用服务后优先走专用服务"
        if cfg.dtk_url
        else "本机 Chrome 铸造访客身份 + 原生 a_bogus/secsdk 签名解析,免登录",
        "kuaishou": "游客接口适配，平台返回结果取决于当前访问条件",
        "xiaohongshu": "完整分享链接解析；部分内容需要实例管理员配置本人登录态",
        "bilibili": "单个视频 / 分集，支持可访问的音视频分轨合并",
        "youtube": "可访问的直连格式；地区、访问凭据及平台限制可能影响结果",
        "tiktok": "单个公开视频；可选接入专用解析服务",
        "instagram": "单个视频链接，访问要求取决于平台",
        "twitter": "单个视频帖子，访问要求取决于平台",
    }
    return [
        {
            "id": key,
            "name": name,
            "status": "experimental",
            "label": "已接入 · 待实测",
            "description": descriptions[key],
        }
        for key, (name, _) in PLATFORMS.items()
    ] + [
        {
            "id": "direct",
            "name": "视频直链",
            "status": "available",
            "label": "可使用",
            "description": "公开 MP4 / MOV / WebM 视频链接；下载后检查文件是否可播放",
        },
        {
            "id": "ixigua",
            "name": "西瓜 / 视频号",
            "status": "planned",
            "label": "暂未开放",
            "description": "完成独立适配和验证后开放",
        },
    ]


class ResolveBody(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class DownloadBody(BaseModel):
    media_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    format_id: str = Field(pattern=r"^[a-f0-9]{20}$")


def create_job(request, kind, platform, payload):
    owner = request.state.owner
    fingerprint = hashlib.sha256(json.dumps([kind, payload], sort_keys=True).encode()).hexdigest()
    key = request.headers.get("idempotency-key")
    if key and len(key) > 100:
        raise AppError("INVALID_INPUT", "请求标识过长。")
    idem = hashlib.sha256(f"{owner}:{key}".encode()).hexdigest() if key else None
    try:
        with Session.begin() as session:
            if idem:
                existing = session.scalar(select(Job).where(Job.idempotency == idem))
                if existing:
                    if existing.fingerprint != fingerprint:
                        raise AppError("IDEMPOTENCY_CONFLICT", "重复请求的内容不一致，请重新提交。", 409)
                    return snapshot(existing)
            current = session.scalar(select(Job).where(Job.slot == f"{owner}:{kind}"))
            if current:
                if current.fingerprint == fingerprint:
                    return snapshot(current)
                raise AppError("BUSY", "已有任务正在处理，请先完成或取消它。", 409)
            count = session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.owner == owner, Job.created_at > time.time() - 60)
            )
            if count >= 15:
                raise AppError("RATE_LIMITED", "请求较频繁，请一分钟后再试。", 429, True)
            queued = session.scalar(select(func.count()).select_from(Job).where(Job.status.not_in(TERMINAL)))
            if queued >= cfg.max_queued:
                raise AppError("QUEUE_FULL", "当前任务较多，请稍后重试。", 503, True)
            job = Job(
                owner=owner,
                kind=kind,
                platform=platform,
                payload=payload,
                slot=f"{owner}:{kind}",
                idempotency=idem,
                fingerprint=fingerprint,
            )
            session.add(job)
            session.flush()
            return snapshot(job)
    except IntegrityError:
        raise AppError("BUSY", "任务已提交，请在下载任务中查看。", 409) from None


@app.post("/api/v1/resolutions", status_code=202)
def resolve(body: ResolveBody, request: Request):
    url, platform = extract_url(body.text)
    return create_job(request, "resolve", platform, {"url": url})


def owned(session, model, identifier, owner):
    item = session.get(model, identifier)
    if not item or item.owner != owner:
        raise AppError("NOT_FOUND", "记录不存在或已过期。", 404)
    return item


@app.get("/api/v1/jobs")
def list_jobs(request: Request):
    with Session() as session:
        return [
            snapshot(job)
            for job in session.scalars(
                select(Job).where(Job.owner == request.state.owner).order_by(Job.created_at.desc()).limit(100)
            )
        ]


@app.get("/api/v1/jobs/{identifier}")
def get_job(identifier: str, request: Request):
    with Session() as session:
        return snapshot(owned(session, Job, identifier, request.state.owner))


@app.get("/api/v1/jobs/{identifier}/events")
async def job_events(identifier: str, request: Request):
    with Session() as session:
        owned(session, Job, identifier, request.state.owner)

    async def events():
        last, heartbeat = -1, time.monotonic()
        while not await request.is_disconnected():
            with Session() as session:
                job = owned(session, Job, identifier, request.state.owner)
                data = snapshot(job)
            if data["version"] != last:
                last = data["version"]
                yield f"id: {last}\nevent: snapshot\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            if data["status"] in TERMINAL:
                return
            if time.monotonic() - heartbeat > 12:
                yield ": heartbeat\n\n"
                heartbeat = time.monotonic()
            await asyncio.sleep(0.7)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@app.post("/api/v1/jobs/{identifier}/cancel")
def cancel_job(identifier: str, request: Request):
    with Session.begin() as session:
        # Write-first CAS also serializes SQLite, where SELECT FOR UPDATE is a no-op.
        session.execute(
            update(Job)
            .where(Job.id == identifier, Job.owner == request.state.owner, Job.status.not_in(TERMINAL))
            .values(
                cancelled=True,
                status="cancelled",
                stage="cancelled",
                slot=None,
                version=Job.version + 1,
                updated_at=time.time(),
            )
        )
        job = session.get(Job, identifier)
        if not job or job.owner != request.state.owner:
            raise AppError("NOT_FOUND", "任务不存在。", 404)
        return snapshot(job)


@app.post("/api/v1/jobs/{identifier}/retry", status_code=202)
def retry_job(identifier: str, request: Request):
    with Session() as session:
        job = owned(session, Job, identifier, request.state.owner)
        if job.status not in TERMINAL:
            return snapshot(job)
        kind, platform, payload = job.kind, job.platform, job.payload
    return create_job(request, kind, platform, payload)


@app.get("/api/v1/media/{identifier}")
def media_info(identifier: str, request: Request):
    with Session() as session:
        media = owned(session, Media, identifier, request.state.owner)
        return {"id": identifier, **media.public}


@app.get("/api/v1/media/{identifier}/cover")
def media_cover(identifier: str, request: Request):
    with Session() as session:
        media = owned(session, Media, identifier, request.state.owner)
        path = Path(media.private.get("cover_path", ""))
        if not path.is_file() or not path.resolve().is_relative_to(cfg.data_dir / "jobs"):
            raise AppError("NOT_FOUND", "封面不可用。", 404)
        return FileResponse(path, media_type=media.private.get("cover_mime", "image/jpeg"))


@app.post("/api/v1/downloads", status_code=202)
def prepare_download(body: DownloadBody, request: Request):
    with Session() as session:
        media = owned(session, Media, body.media_id, request.state.owner)
        fmt = next((fmt for fmt in media.public["formats"] if fmt["id"] == body.format_id), None)
        if not fmt:
            raise AppError("INVALID_INPUT", "请选择有效的视频格式。")
        platform = media.public["platform"]
        payload = {
            "media_id": media.id,
            "format_id": fmt["id"],
            "watermark": fmt["watermark"],
            "title": media.public["title"],
            "quality": fmt["quality"],
        }
    return create_job(request, "download", platform, payload)


@app.post("/api/v1/artifacts/{identifier}/download-ticket")
def download_ticket(identifier: str, request: Request):
    with Session() as session:
        artifact = owned(session, Artifact, identifier, request.state.owner)
        if artifact.expires_at <= time.time() or not Path(artifact.path).is_file():
            raise AppError("ARTIFACT_EXPIRED", "文件已过期，请在任务列表中重新准备。", 410, True)
        token = signer.dumps({"id": identifier, "owner": request.state.owner}, salt="download")
        return {"url": f"/api/v1/files/{identifier}?ticket={token}", "expires_in": 300}


@app.get("/api/v1/files/{identifier}")
def download_file(identifier: str, ticket: str, request: Request):
    try:
        data = signer.loads(ticket, salt="download", max_age=300)
    except (SignatureExpired, BadSignature):
        raise AppError("TICKET_EXPIRED", "下载链接已失效，请重新点击保存。", 410) from None
    if data != {"id": identifier, "owner": request.state.owner}:
        raise AppError("NOT_FOUND", "文件不可用。", 404)
    with Session() as session:
        artifact = owned(session, Artifact, identifier, request.state.owner)
        path = Path(artifact.path)
        if artifact.expires_at < time.time() or not path.is_file():
            raise AppError("ARTIFACT_EXPIRED", "文件已过期，请重新准备。", 410)
        if not path.resolve().is_relative_to(cfg.data_dir / "jobs"):
            raise AppError("NOT_FOUND", "文件不可用。", 404)
        return FileResponse(path, filename=artifact.filename, media_type="application/octet-stream")


@app.get("/{path:path}")
def frontend(path: str):
    if path.startswith("api/"):
        raise AppError("NOT_FOUND", "接口不存在。", 404)
    dist = ROOT / "web" / "dist"
    file = (dist / path).resolve()
    if file.is_relative_to(dist) and file.is_file():
        return FileResponse(file)
    if (dist / "index.html").exists():
        return FileResponse(dist / "index.html")
    return JSONResponse({"message": "留影 API 已启动。请在 web/ 执行 npm run dev，或 npm run build。"})
