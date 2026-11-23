"""Smaller hardening fixes: /health detail, the API schema, the cron secret, and logging that cannot break a reply."""
from app import agent as agent_module
from app.agent import ModelEvent
from app.costs import Usage
from app.db import Run
from tests.conftest import read_sse


def test_public_health_says_only_that_the_app_is_up(client):
    r = client.get("/health")

    assert r.status_code == 200
    assert r.json() == {"status": "ok"}  # no environment, model, provider or database type


def test_health_detail_is_for_whoever_holds_the_cron_secret(client):
    r = client.get("/health", headers={"X-Cron-Secret": "cron-test"})

    body = r.json()
    assert r.status_code == 200
    assert body["status"] == "ok" and body["env"] == "local" and body["db"] == "sqlite" and "problems" in body


def test_a_wrong_cron_secret_gets_no_detail(client):
    r = client.get("/health", headers={"X-Cron-Secret": "wrong"})

    assert r.json() == {"status": "ok"}


def test_the_api_schema_is_not_published(client):
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(path).status_code == 404, path


def test_the_cron_secret_is_still_checked(client):
    assert client.post("/internal/digest").status_code == 401
    assert client.post("/internal/digest", headers={"X-Cron-Secret": "wrong"}).status_code == 401
    assert client.post("/internal/digest", headers={"X-Cron-Secret": "cron-test"}).status_code == 200


def test_the_cron_secret_is_compared_in_constant_time():
    import inspect

    from app import main

    source = inspect.getsource(main)
    assert "compare_digest" in source
    assert "x_cron_secret !=" not in source and "!= settings.cron_secret" not in source


def test_a_failing_conversations_log_does_not_break_the_reply(client, db, logged_in, fake, monkeypatch):
    class BrokenLog:
        def insert(self):
            raise RuntimeError("the log table is broken")

    monkeypatch.setattr(agent_module, "conversation_log", BrokenLog())
    fake.turns.append([ModelEvent(type="text", text="Fine."),
                       ModelEvent(type="stop", stop_reason="end_turn", usage=Usage(10, 5),
                                  content=[{"type": "text", "text": "Fine."}])])

    events = read_sse(client.post("/api/chat", json={"message": "hello"}))

    assert [e["type"] for e in events][-1] == "done"
    assert not [e for e in events if e["type"] == "error"]
    run = db.query(Run).filter_by(conversation_id=events[0]["conversation_id"]).one()
    assert run.status == "ok"  # the run record survived
