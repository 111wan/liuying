from celery import Celery

from .config import settings

app = Celery("liuying", broker=settings().redis_url)
app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_ignore_result=True,
    task_soft_time_limit=960,
    task_time_limit=1000,
)


@app.task(name="liuying.execute")
def execute(job_id):
    from .db import init_db
    from .worker import run_job

    init_db()
    run_job(job_id)
