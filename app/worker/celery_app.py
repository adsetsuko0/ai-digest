import os

from celery import Celery
from celery.signals import worker_init, worker_process_init, worker_process_shutdown

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.metrics import mark_worker_process_dead, start_metrics_server

celery_app = Celery(
    "digest", broker=settings.CELERY_BROKER_URL, include=["app.worker.tasks"]
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=60,
    task_time_limit=90,
    timezone="UTC",
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "fetch-all-feeds": {
            "task": "app.worker.tasks.fetch_all_feeds",
            "schedule": settings.FETCH_INTERVAL_SECONDS,
        },
    },
)


@worker_process_init.connect
def _setup_logging(**kwargs) -> None:
    configure_logging()


@worker_init.connect
def _start_metrics(**kwargs) -> None:
    port = int(os.environ.get("WORKER_METRICS_PORT", "0"))
    start_metrics_server(port)


@worker_process_shutdown.connect
def _cleanup_metrics(pid=None, **kwargs) -> None:
    if pid is not None:
        mark_worker_process_dead(pid)
