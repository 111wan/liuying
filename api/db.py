import time
import uuid

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text, create_engine, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uuid.uuid4().hex)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    platform: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(24), default="queued")
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)
    version: Mapped[int] = mapped_column(Integer, default=1)
    idempotency: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    dispatched_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    slot: Mapped[str | None] = mapped_column(String(90), unique=True, nullable=True)


class Media(Base):
    __tablename__ = "media"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uuid.uuid4().hex)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    public: Mapped[dict] = mapped_column(JSON)
    private: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uuid.uuid4().hex)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    job_id: Mapped[str] = mapped_column(String(40), unique=True)
    path: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(240))
    size: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[float] = mapped_column(Float, index=True)


_cfg = settings()
engine = create_engine(
    _cfg.database_url,
    connect_args={"check_same_thread": False, "timeout": 30}
    if _cfg.database_url.startswith("sqlite")
    else {},
    pool_pre_ping=True,
)
Session = sessionmaker(engine, expire_on_commit=False)
TERMINAL = {"ready", "failed", "cancelled"}


def init_db():
    Base.metadata.create_all(engine)
    if engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")


def change(job_id, **values):
    if values.get("status") in TERMINAL:
        values["slot"] = None
    with Session.begin() as session:
        session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status.not_in(TERMINAL))
            .values(**values, updated_at=time.time(), version=Job.version + 1)
        )


def snapshot(job):
    return {
        key: getattr(job, key)
        for key in (
            "id",
            "kind",
            "platform",
            "status",
            "stage",
            "result",
            "error",
            "progress",
            "created_at",
            "updated_at",
            "version",
        )
    } | {"title": job.payload.get("title"), "quality": job.payload.get("quality")}


def pending():
    with Session() as session:
        return session.scalars(
            select(Job.id).where(Job.status == "queued").order_by(Job.created_at).limit(24)
        ).all()
