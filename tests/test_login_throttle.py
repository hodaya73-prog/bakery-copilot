"""Login throttling and security logging (app/security.py, SecurityProblems.md SP-02 and SP-17)."""
import logging

import pytest

from app import limits, security
from app.security import LoginThrottle

GOOD = {"name": "Probe", "password": "test-pass"}


@pytest.fixture(autouse=True)
def fresh_throttle():
    security.login_throttle.reset()
    yield
    security.login_throttle.reset()


def _wrong(client, ip_header: str, name: str = "Probe"):
    return client.post("/api/login", json={"name": name, "password": "nope"}, headers={"X-Forwarded-For": ip_header})


def _security_messages(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "bakery.security"]


def test_the_ninth_wrong_password_from_one_address_is_blocked(client):
    codes = [_wrong(client, "203.0.113.9").status_code for _ in range(9)]

    assert codes[:8] == [401] * 8
    assert codes[8] == 429


def test_a_blocked_address_cannot_get_in_even_with_the_right_password(client):
    for _ in range(8):
        _wrong(client, "203.0.113.9")

    r = client.post("/api/login", json=GOOD, headers={"X-Forwarded-For": "203.0.113.9"})

    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > 0
    assert "bc_session" not in r.cookies


def test_other_addresses_are_not_affected(client):
    for _ in range(8):
        _wrong(client, "203.0.113.9")

    r = client.post("/api/login", json=GOOD, headers={"X-Forwarded-For": "198.51.100.7"})

    assert r.status_code == 200


def test_a_forged_first_address_does_not_dodge_the_block(client):
    # The proxy appends the real client address last; anything before it is the caller's own claim.
    codes = [_wrong(client, f"10.0.0.{i}, 203.0.113.9").status_code for i in range(9)]

    assert codes[8] == 429


def test_a_good_login_clears_the_count(client):
    for _ in range(5):
        _wrong(client, "203.0.113.20")
    assert client.post("/api/login", json=GOOD, headers={"X-Forwarded-For": "203.0.113.20"}).status_code == 200

    codes = [_wrong(client, "203.0.113.20").status_code for _ in range(8)]

    assert codes == [401] * 8


def test_failures_expire_after_the_window():
    now = [1000.0]
    t = LoginThrottle(max_failures=3, window_seconds=60, clock=lambda: now[0])
    for _ in range(3):
        t.record_failure("a")
    assert t.blocked_for("a") > 0

    now[0] += 61

    assert t.blocked_for("a") == 0


def test_a_failed_login_is_logged_without_the_password_and_without_log_injection(client, caplog):
    with caplog.at_level(logging.INFO, logger="bakery.security"):
        _wrong(client, "203.0.113.30", name="Evil\nlogin_ok ip=1.2.3.4")

    failed = [m for m in _security_messages(caplog) if m.startswith("login_failed")]
    assert failed, _security_messages(caplog)
    assert "ip=203.0.113.30" in failed[0]
    assert "\n" not in failed[0]  # the forged second line cannot appear
    assert "nope" not in failed[0]  # the password is never logged


def test_a_throttled_attempt_is_logged(client, caplog):
    for _ in range(8):
        _wrong(client, "203.0.113.40")
    with caplog.at_level(logging.INFO, logger="bakery.security"):
        _wrong(client, "203.0.113.40")

    assert any(m.startswith("login_throttled") for m in _security_messages(caplog))


def test_a_message_rate_limit_hit_is_logged(client, logged_in, caplog, monkeypatch):
    monkeypatch.setattr(limits, "messages_last_hour", lambda db, user_id: 10_000)

    with caplog.at_level(logging.INFO, logger="bakery.security"):
        r = client.post("/api/chat", json={"message": "one more"})

    assert r.status_code == 429
    assert any(m.startswith("rate_limit_hit") and "user_id=" in m for m in _security_messages(caplog))


def test_a_daily_cap_hit_is_logged(client, logged_in, caplog, monkeypatch):
    monkeypatch.setattr(limits, "spend_today_usd", lambda db: 10_000.0)

    with caplog.at_level(logging.INFO, logger="bakery.security"):
        r = client.post("/api/chat", json={"message": "one more"})

    assert r.status_code == 402
    assert any(m.startswith("daily_cap_hit") for m in _security_messages(caplog))
