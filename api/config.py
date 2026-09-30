import os
import secrets
import tempfile
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LIUYING_", env_file=ROOT / ".env", extra="ignore")
    data_dir: Path = ROOT / ".data"
    database_url: str = ""
    queue_mode: str = "local"
    redis_url: str = "redis://localhost:6379/0"
    max_bytes: int = 8 * 1024 * 1024 * 1024
    max_duration: int = 4 * 3600
    artifact_ttl: int = 3600
    parse_timeout: int = 90
    download_timeout: int = 4 * 3600
    max_workers: int = 2
    max_queued: int = 24
    dtk_url: str = ""
    dtk_api_key: str = ""
    cookie_file: str = ""
    proxy: str = ""
    access_password: str = ""
    secure_cookie: bool = False
    allowed_hosts: list[str] = ["127.0.0.1", "localhost", "testserver"]
    secret: str = ""

    def prepare(self):
        self.data_dir = self.data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.data_dir / "jobs").mkdir(exist_ok=True, mode=0o700)
        if not self.database_url:
            self.database_url = f"sqlite:///{self.data_dir / 'liuying.db'}"
        if not self.secret:
            path = self.data_dir / "session.key"
            if not path.exists():
                # Link a fully written file atomically; concurrent workers never read an empty key.
                with tempfile.NamedTemporaryFile(mode="w", dir=self.data_dir, delete=False) as handle:
                    handle.write(secrets.token_hex(32))
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.link(handle.name, path)
                except FileExistsError:
                    pass
                finally:
                    Path(handle.name).unlink(missing_ok=True)
            self.secret = path.read_text().strip()
            if len(self.secret) < 32:
                raise ValueError("Invalid session signing key")
        if self.proxy:
            parsed = urlsplit(self.proxy)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or not parsed.port
                or parsed.username
                or parsed.password
            ):
                raise ValueError("LIUYING_PROXY 需要 http(s)://主机:端口 格式，且不包含账号密码。")
            self.proxy = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        return self


@lru_cache
def settings():
    return Settings().prepare()
