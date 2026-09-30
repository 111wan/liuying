import os
import tempfile

import pytest

# Isolated database: never touch the running app's history or credentials.
_directory = tempfile.TemporaryDirectory(prefix="liuying-tests-")
os.environ["LIUYING_DATA_DIR"] = _directory.name
os.environ["LIUYING_DATABASE_URL"] = "sqlite:///" + _directory.name + "/test.db"
os.environ["LIUYING_COOKIE_FILE"] = ""
os.environ["LIUYING_DTK_URL"] = ""
# 测试环境不启用访问密码(真实 .env 中可能配置了公网密码)
os.environ["LIUYING_ACCESS_PASSWORD"] = ""
# 测试客户端走 http,Secure Cookie 不会被回传,强制关闭(真实 .env 可能为 true)
os.environ["LIUYING_SECURE_COOKIE"] = "false"


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from api import main
    from api.db import Base, engine, init_db

    class NoWorker:
        def join(self, _):
            return None

    monkeypatch.setattr(main, "start_supervisor", lambda: NoWorker())
    Base.metadata.drop_all(engine)
    init_db()
    with TestClient(main.app) as test_client:
        token = test_client.get("/api/v1/session").json()["csrf_token"]
        test_client.headers["X-CSRF-Token"] = token
        yield test_client
