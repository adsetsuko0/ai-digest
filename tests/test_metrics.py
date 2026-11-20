from app.core import metrics


def test_server_is_off_when_the_port_is_zero(monkeypatch):
    started = []
    monkeypatch.setattr(
        metrics, "start_http_server", lambda *a, **kw: started.append(a)
    )

    assert metrics.start_metrics_server(0) is False
    assert started == []


def test_server_needs_the_multiprocess_directory(monkeypatch):
    started = []
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    monkeypatch.setattr(
        metrics, "start_http_server", lambda *a, **kw: started.append(a)
    )

    assert metrics.start_metrics_server(9100) is False
    assert started == []


def test_server_starts_with_an_aggregating_registry(monkeypatch, tmp_path):
    started = []
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    monkeypatch.setattr(
        metrics,
        "start_http_server",
        lambda port, registry=None: started.append((port, registry)),
    )

    assert metrics.start_metrics_server(9100) is True
    assert started[0][0] == 9100
    assert started[0][1] is not None


def test_mark_dead_does_nothing_without_the_directory(monkeypatch):
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)

    metrics.mark_worker_process_dead(123)  # must not raise


def test_mark_dead_cleans_up_the_process_files(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    monkeypatch.setattr(metrics.multiprocess, "mark_process_dead", calls.append)

    metrics.mark_worker_process_dead(123)

    assert calls == [123]
