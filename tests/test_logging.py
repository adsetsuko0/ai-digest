import json

import pytest
import structlog

from app.core.config import settings
from app.core.logging import configure_logging


@pytest.fixture(autouse=True)
def reset_structlog():
    yield
    structlog.reset_defaults()


def test_json_logs(capsys):
    configure_logging(json_logs=True)
    structlog.get_logger().info("hello", feed_id=1)
    entry = json.loads(capsys.readouterr().out)
    assert entry["event"] == "hello"
    assert entry["feed_id"] == 1
    assert entry["level"] == "info"


def test_console_logs_are_readable(capsys):
    configure_logging(json_logs=False)
    structlog.get_logger().info("hello", feed_id=1)
    assert "hello" in capsys.readouterr().out


def test_log_format_comes_from_settings(monkeypatch, capsys):
    monkeypatch.setattr(settings, "LOG_JSON", True)
    configure_logging()
    structlog.get_logger().info("hello")
    assert json.loads(capsys.readouterr().out)["event"] == "hello"
