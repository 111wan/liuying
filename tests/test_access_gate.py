from fastapi.testclient import TestClient

from api import main
from api.db import Base, engine, init_db


class NoWorker:
    def join(self, _):
        return None


def make_client(monkeypatch, password):
    monkeypatch.setattr(main, "LOGIN_ATTEMPTS", {})
    monkeypatch.setattr(main.cfg, "access_password", password)
    monkeypatch.setattr(main, "start_supervisor", lambda: NoWorker())
    Base.metadata.drop_all(engine)
    init_db()
    return TestClient(main.app)


def test_gate_off_by_default(monkeypatch):
    with make_client(monkeypatch, "") as client:
        assert client.get("/api/v1/session").status_code == 200


def test_gate_blocks_api_and_serves_login_page(monkeypatch):
    with make_client(monkeypatch, "secret123") as client:
        assert client.get("/api/v1/session").status_code == 401
        assert client.get("/api/v1/platforms").status_code == 401
        assert client.get("/api/v1/health").status_code == 200
        page = client.get("/")
        assert page.status_code == 200
        assert "访问密码" in page.text
        assert "/api/v1/login" in page.text


def test_login_sets_auth_cookie(monkeypatch):
    with make_client(monkeypatch, "secret123") as client:
        bad = client.post("/api/v1/login", data={"password": "wrong"}, follow_redirects=False)
        assert bad.status_code == 303
        assert "/?err=1" in bad.headers["location"]
        assert "liuying_auth" not in bad.cookies
        good = client.post("/api/v1/login", data={"password": "secret123"}, follow_redirects=False)
        assert good.status_code == 303
        assert good.headers["location"] == "/"
        assert "liuying_auth" in good.cookies
        session = client.get("/api/v1/session")
        assert session.status_code == 200
        client.headers["X-CSRF-Token"] = session.json()["csrf_token"]
        assert client.get("/api/v1/platforms").status_code == 200


def test_login_rate_limited(monkeypatch):
    with make_client(monkeypatch, "secret123") as client:
        for _ in range(5):
            client.post("/api/v1/login", data={"password": "wrong"}, follow_redirects=False)
        limited = client.post("/api/v1/login", data={"password": "secret123"}, follow_redirects=False)
        assert limited.status_code == 303
        assert "/?err=2" in limited.headers["location"]


def test_changed_password_invalidates_old_cookie(monkeypatch):
    with make_client(monkeypatch, "secret123") as client:
        logged = client.post("/api/v1/login", data={"password": "secret123"}, follow_redirects=False)
        assert logged.status_code == 303
    with make_client(monkeypatch, "another456") as client:
        assert client.get("/api/v1/session").status_code == 401
