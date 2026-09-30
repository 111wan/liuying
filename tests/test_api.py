import time

from fastapi.testclient import TestClient

from api.db import Artifact, Job, Session, change
from api.main import app, cfg

SAMPLE = {"text": "https://media.w3.org/2010/05/sintel/trailer.mp4"}


def create(client):
    response = client.post("/api/v1/resolutions", json=SAMPLE)
    assert response.status_code == 202, response.text
    return response.json()


def test_csrf_and_host(client):
    assert client.post("/api/v1/resolutions", json=SAMPLE, headers={"X-CSRF-Token": "bad"}).status_code == 403
    assert (
        client.post("/api/v1/resolutions", json=SAMPLE, headers={"Sec-Fetch-Site": "cross-site"}).status_code
        == 403
    )
    assert client.get("/api/v1/session", headers={"Host": "evil.example"}).status_code == 400


def test_idempotency_and_owner_isolation(client):
    first = client.post("/api/v1/resolutions", json=SAMPLE, headers={"Idempotency-Key": "same"})
    second = client.post("/api/v1/resolutions", json=SAMPLE, headers={"Idempotency-Key": "same"})
    assert first.json()["id"] == second.json()["id"]
    assert "url" not in first.text
    conflict = client.post(
        "/api/v1/resolutions", json={"text": "https://a.example/a.mp4"}, headers={"Idempotency-Key": "same"}
    )
    assert conflict.status_code == 409
    other = TestClient(app)
    assert other.get("/api/v1/jobs/" + first.json()["id"]).status_code == 404
    assert other.get("/api/v1/jobs").json() == []


def test_cancel_is_terminal_and_retry_is_new(client):
    first = create(client)
    cancelled = client.post(f"/api/v1/jobs/{first['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    change(first["id"], status="ready", stage="ready")
    assert client.get(f"/api/v1/jobs/{first['id']}").json()["status"] == "cancelled"
    retry = client.post(f"/api/v1/jobs/{first['id']}/retry")
    assert retry.status_code == 202
    assert retry.json()["id"] != first["id"]


def test_busy_slot_and_invalid_source(client):
    create(client)
    assert client.post("/api/v1/resolutions", json={"text": "https://a.example/other.mp4"}).status_code == 409
    assert client.post("/api/v1/resolutions", json={"text": "http://127.0.0.1/video.mp4"}).status_code == 400


def test_signed_download_ranges_and_expiry(client):
    job = create(client)
    with Session.begin() as session:
        owner = session.get(Job, job["id"]).owner
        directory = cfg.data_dir / "jobs" / job["id"]
        directory.mkdir()
        path = directory / "video.mp4"
        path.write_bytes(b"0123456789")
        artifact = Artifact(
            owner=owner,
            job_id=job["id"],
            path=str(path),
            filename="测试视频.mp4",
            size=10,
            expires_at=time.time() + 100,
        )
        session.add(artifact)
        session.flush()
        identifier = artifact.id
    url = client.post(f"/api/v1/artifacts/{identifier}/download-ticket").json()["url"]
    response = client.get(url, headers={"Range": "bytes=0-3"})
    assert response.status_code == 206
    assert response.content == b"0123"
    assert response.headers["content-range"] == "bytes 0-3/10"
    assert "attachment" in response.headers["content-disposition"]
    assert TestClient(app).get(url).status_code == 404
    with Session.begin() as session:
        session.get(Artifact, identifier).expires_at = time.time() - 1
    assert client.get(url).status_code == 410


def test_worker_cannot_publish_after_cancel(client, monkeypatch):
    from api.worker import STOP, run_job

    job = create(client)

    def interrupted_child(*_args):
        client.post(f"/api/v1/jobs/{job['id']}/cancel")
        return {"public": {"title": "test"}, "private": {}}

    monkeypatch.setattr("api.worker.child", interrupted_child)
    STOP.clear()
    run_job(job["id"])
    final = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert final["status"] == "cancelled"
    assert final["result"] is None


def test_event_stream_contains_terminal_snapshot(client):
    job = create(client)
    client.post(f"/api/v1/jobs/{job['id']}/cancel")
    result = client.get(f"/api/v1/jobs/{job['id']}/events")
    assert "event: snapshot" in result.text
    assert '"status": "cancelled"' in result.text
