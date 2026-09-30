import json
import logging
import os
import selectors
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import select, update

from .config import ROOT, settings
from .db import Artifact, Job, Media, Session, change, pending
from .errors import AppError

log = logging.getLogger(__name__)
STOP = threading.Event()


def stop_process(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=3)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=3)


def child(command, job_id, timeout):
    process = subprocess.Popen(
        [sys.executable, "-m", "api.engine_child"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    try:
        process.stdin.write((json.dumps(command) + "\n").encode())
        process.stdin.close()
        selector.register(process.stdout, selectors.EVENT_READ)
        start, last_heartbeat, buffer, result = time.monotonic(), 0, b"", None
        while True:
            if time.monotonic() - start > timeout:
                raise AppError("NETWORK_TIMEOUT", "任务超过处理时间，请稍后重试。", 504, True)
            with Session() as session:
                current = session.get(Job, job_id)
                if not current or current.cancelled or current.status == "cancelled" or STOP.is_set():
                    raise AppError("CANCELLED", "任务已取消。")
            if time.monotonic() - last_heartbeat > 4:
                change(job_id)
                last_heartbeat = time.monotonic()
            events = selector.select(0.4)
            for key, _ in events:
                block = os.read(key.fd, 65536)
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                buffer += block
                if len(buffer) > 4 * 1024 * 1024:
                    raise AppError("LIMIT_EXCEEDED", "解析结果过大，请使用单个作品链接。", 422)
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    event = json.loads(line)
                    if event["event"] == "progress":
                        change(
                            job_id,
                            stage=event.get("stage", "fetching"),
                            progress={k: v for k, v in event.items() if k not in ("event", "stage")},
                        )
                    elif event["event"] == "error":
                        error = event["error"]
                        raise AppError(
                            error["code"], error["message"], retryable=error.get("retryable", False)
                        )
                    elif event["event"] == "result":
                        result = event["data"]
            if process.poll() is not None and not selector.get_map():
                break
        if process.returncode or result is None:
            raise AppError("WORKER_ERROR", "处理进程已结束，请重试。", 500, True)
        return result
    finally:
        selector.close()
        stop_process(process)
        process.stdout.close()


def run_job(job_id):
    cfg = settings()
    directory = cfg.data_dir / "jobs" / job_id
    succeeded = False
    with Session.begin() as session:
        claimed = session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(status="running", stage="resolving", updated_at=time.time(), version=Job.version + 1)
        )
        if not claimed.rowcount:
            return
        job = session.get(Job, job_id)
        command = {"directory": str(directory), "platform": job.platform}
        if job.kind == "resolve":
            command |= {"mode": "resolve", "url": job.payload["url"]}
        else:
            media = session.get(Media, job.payload["media_id"])
            if not media or media.owner != job.owner:
                job.status, job.stage, job.slot = "failed", "failed", None
                job.error = AppError("SOURCE_EXPIRED", "作品记录已过期，请重新解析。", 410).public()
                return
            command |= {
                "mode": "download",
                "url": media.private["url"],
                "format_id": job.payload["format_id"],
                "watermark": job.payload["watermark"],
            }
    try:
        change(job_id, stage="resolving" if job.kind == "resolve" else "refreshing")
        output = child(command, job_id, cfg.parse_timeout if job.kind == "resolve" else cfg.download_timeout)
        with Session.begin() as session:
            # Serialize completion with cancellation. A cancelled job cannot publish an artifact.
            claimed = session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "running", Job.cancelled.is_(False))
                .values(version=Job.version + 1)
            )
            if not claimed.rowcount:
                return
            current = session.get(Job, job_id)
            if job.kind == "resolve":
                identifier = uuid.uuid4().hex
                media = Media(
                    id=identifier, owner=job.owner, public=output["public"], private=output["private"]
                )
                session.add(media)
                current.result = {"media_id": identifier}
            else:
                path = Path(output["path"]).resolve()
                if not path.is_relative_to(directory.resolve()) or not path.is_file():
                    raise AppError("WORKER_ERROR", "产物路径无效。", 500)
                identifier = uuid.uuid4().hex
                expiry = time.time() + cfg.artifact_ttl
                session.add(
                    Artifact(
                        id=identifier,
                        owner=job.owner,
                        job_id=job_id,
                        path=str(path),
                        filename=output["filename"],
                        size=output["size"],
                        expires_at=expiry,
                    )
                )
                current.result = {
                    "artifact_id": identifier,
                    "filename": output["filename"],
                    "size_bytes": output["size"],
                    "expires_at": expiry,
                }
            current.status = "ready"
            current.stage = "ready"
            current.slot = None
            current.updated_at = time.time()
        succeeded = True
    except AppError as error:
        change(
            job_id,
            status="cancelled" if error.code == "CANCELLED" else "failed",
            stage="cancelled" if error.code == "CANCELLED" else "failed",
            error=error.public(),
        )
    except Exception:
        log.exception("Job failed: %s", job_id)
        change(
            job_id,
            status="failed",
            stage="failed",
            error=AppError("WORKER_ERROR", "任务处理失败，请重试。", 500, True).public(),
        )
    finally:
        if not succeeded and directory.is_dir():
            # Only a UUID task-owned directory is eligible for cleanup.
            shutil.rmtree(directory)


def housekeeping():
    now = time.time()
    with Session.begin() as session:
        for artifact in session.scalars(
            select(Artifact).where(Artifact.expires_at < now, Artifact.path != "")
        ):
            path = Path(artifact.path)
            if path.resolve().is_relative_to((settings().data_dir / "jobs").resolve()):
                path.unlink(missing_ok=True)
            artifact.path = ""  # Keep a tombstone so the API can explain expiry.
        for media in session.scalars(select(Media).where(Media.created_at < now - 86400)):
            cover_path = Path(media.private.get("cover_path", ""))
            if cover_path.is_file() and cover_path.resolve().is_relative_to(settings().data_dir / "jobs"):
                cover_path.unlink(missing_ok=True)
            session.delete(media)
        stale = session.scalars(select(Job).where(Job.status == "running", Job.updated_at < now - 30)).all()
        for job in stale:
            job.status, job.stage, job.slot = "failed", "failed", None
            job.error = AppError(
                "INTERRUPTED", "服务重启或工作进程中断，点击重试可重新准备。", 503, True
            ).public()
            job.version += 1
            job.updated_at = now


def supervisor():
    cfg = settings()
    with ThreadPoolExecutor(max_workers=cfg.max_workers) as executor:
        active, last_clean = {}, 0
        while not STOP.is_set():
            active = {key: future for key, future in active.items() if not future.done()}
            if time.time() - last_clean > 10:
                housekeeping()
                last_clean = time.time()
            if cfg.queue_mode == "local":
                for identifier in pending():
                    if len(active) >= cfg.max_workers:
                        break
                    if identifier not in active:
                        active[identifier] = executor.submit(run_job, identifier)
            else:
                from .celery_app import execute

                with Session.begin() as session:
                    jobs = session.scalars(
                        select(Job).where(Job.status == "queued").order_by(Job.created_at).limit(24)
                    ).all()
                    for job in jobs:
                        if job.dispatched_at and time.time() - job.dispatched_at < 30:
                            continue
                        try:
                            execute.apply_async(args=[job.id], task_id=job.id)
                            job.dispatched_at = time.time()
                        except Exception:
                            log.exception("Queue temporarily unavailable; durable job remains queued")
                            break
            STOP.wait(0.5)


def start_supervisor():
    STOP.clear()
    thread = threading.Thread(target=supervisor, daemon=True, name="liuying-supervisor")
    thread.start()
    return thread
