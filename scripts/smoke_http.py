"""Live opt-in test: fetch the W3C-hosted public Sintel trailer from the running app."""

import json
import time

import httpx


def wait(client, job):
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        response = client.get("/api/v1/jobs/" + job["id"])
        response.raise_for_status()
        state = response.json()
        if state["status"] in ("failed", "cancelled"):
            raise RuntimeError(json.dumps(state["error"], ensure_ascii=False))
        if state["status"] == "ready":
            return state
        time.sleep(0.4)
    raise RuntimeError("Live smoke test timed out")


def main():
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=30, trust_env=False) as client:
        info = client.get("/api/v1/session").json()
        client.headers["X-CSRF-Token"] = info["csrf_token"]
        result = client.post("/api/v1/resolutions", json={"text": info["sample_url"]})
        result.raise_for_status()
        job = wait(client, result.json())
        media = client.get("/api/v1/media/" + job["result"]["media_id"]).json()
        print("RESOLVED", media["title"], media["formats"][0]["watermark"], flush=True)
        result = client.post(
            "/api/v1/downloads", json={"media_id": media["id"], "format_id": media["formats"][0]["id"]}
        )
        result.raise_for_status()
        job = wait(client, result.json())
        ticket = client.post("/api/v1/artifacts/" + job["result"]["artifact_id"] + "/download-ticket").json()
        response = client.get(ticket["url"])
        response.raise_for_status()
        assert len(response.content) == job["result"]["size_bytes"]
        assert response.content[4:8] == b"ftyp"
        partial = client.get(ticket["url"], headers={"Range": "bytes=0-31"})
        assert partial.status_code == 206 and len(partial.content) == 32
        with httpx.Client(base_url=str(client.base_url), trust_env=False) as other:
            assert other.get(ticket["url"]).status_code == 404
            assert other.get("/api/v1/media/" + media["id"]).status_code == 404
        print(
            "PASS",
            json.dumps(
                {
                    "filename": job["result"]["filename"],
                    "bytes": len(response.content),
                    "range": partial.status_code,
                    "cross_session": "blocked",
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
