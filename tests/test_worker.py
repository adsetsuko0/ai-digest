import app.worker.tasks as tasks
from app.models import Feed, User, UserFeed
from app.worker.celery_app import celery_app


def test_ping_task():
    assert tasks.ping() == "pong"


def test_celery_is_configured_for_safe_retries():
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.beat_schedule["fetch-all-feeds"]["schedule"] == 1800


def test_retry_delay_grows():
    assert [tasks.retry_delay(n) for n in range(3)] == [60, 240, 960]


def test_fetch_all_feeds_schedules_only_active_subscribed_feeds(
    use_sync_db, monkeypatch
):
    factory = use_sync_db
    with factory() as session:
        user = User(email="a@example.com", hashed_password="x")
        active = Feed(url="https://a.example.com/rss", is_active=True)
        inactive = Feed(url="https://b.example.com/rss", is_active=False)
        orphan = Feed(url="https://c.example.com/rss", is_active=True)  # no subscribers
        session.add_all([user, active, inactive, orphan])
        session.flush()
        session.add_all(
            [
                UserFeed(user_id=user.id, feed_id=active.id),
                UserFeed(user_id=user.id, feed_id=inactive.id),
            ]
        )
        session.commit()
        active_id = active.id
    scheduled = []
    monkeypatch.setattr(
        tasks.fetch_feed,
        "apply_async",
        lambda args, countdown: scheduled.append((args, countdown)),
    )

    assert tasks.fetch_all_feeds() == 1
    assert scheduled[0][0] == [active_id]
    assert 0 <= scheduled[0][1] <= 60
