import os

import structlog
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    multiprocess,
    start_http_server,
)

logger = structlog.get_logger(__name__)

# Labels have a few fixed values only. Never label by feed, url or user:
# every new value creates a new time series, and Prometheus runs out of memory.
ARTICLES_FETCHED = Counter(
    "articles_fetched_total", "New articles stored by feed collection"
)
FETCH_ERRORS = Counter(
    "fetch_errors_total",
    "Failed feed fetch attempts by kind (temporary, permanent, parse, unexpected)",
    ["kind"],
)
SUMMARIES = Counter(
    "summaries_total",
    "Outcomes of summarization (done, cache_hit, skipped, failed)",
    ["status"],
)
LLM_TOKENS = Counter("llm_tokens_total", "Tokens spent on summaries")
SUMMARY_LATENCY = Histogram(
    "summary_latency_seconds",
    "Duration of one successful LLM summarization call",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)

# Create every series at zero. Otherwise a series appears with the value 1 and
# Prometheus's increase() never sees the first event.
for _kind in ("temporary", "permanent", "parse", "unexpected"):
    FETCH_ERRORS.labels(kind=_kind)
for _status in ("done", "cache_hit", "skipped", "failed"):
    SUMMARIES.labels(status=_status)


def start_metrics_server(port: int) -> bool:
    """Serve the worker's metrics over HTTP (called once, in the main process).

    A Celery worker runs tasks in child processes, so each of them writes its
    counters to files in PROMETHEUS_MULTIPROC_DIR and the server sums them up.
    """
    if port <= 0:
        return False
    if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        logger.warning(
            "worker_metrics_disabled", reason="PROMETHEUS_MULTIPROC_DIR is not set"
        )
        return False
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    start_http_server(port, registry=registry)
    return True


def mark_worker_process_dead(pid: int) -> None:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        multiprocess.mark_process_dead(pid)
