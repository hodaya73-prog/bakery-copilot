"""The local .env loader (app/config.py): a copy of .env.example must load as the README says."""
import os
import re

import pytest

from app import config

EXAMPLE = config.ROOT / ".env.example"
NAMES = re.findall(r"^#?\s*([A-Z_]+)=", EXAMPLE.read_text(encoding="utf-8"), re.M)


def _clean_env(monkeypatch, names):
    # setenv first so monkeypatch records the original state and restores it after the test,
    # including removing variables the loader adds.
    for name in names:
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)


def test_copied_env_example_loads(monkeypatch):
    _clean_env(monkeypatch, NAMES)
    config._load_dotenv(EXAMPLE)
    s = config.load_settings()
    assert s.environment == "local"
    assert s.app_password == "change-me"
    assert s.database_url == "sqlite:///./local.db"
    assert s.history_limit == 20
    assert s.daily_cap_usd == 3.0
    assert s.anthropic_api_key is None  # the line holds only a comment


def _production_env(monkeypatch, **overrides):
    _clean_env(monkeypatch, NAMES)
    values = {"APP_ENV": "production", "APP_PASSWORD": "a-long-enough-passphrase", "APP_SECRET": "s" * 40,
              "MODEL_PROVIDER": "fake", **overrides}
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_production_refuses_a_short_password(monkeypatch):
    _production_env(monkeypatch, APP_PASSWORD="bakery123")

    with pytest.raises(RuntimeError, match="APP_PASSWORD.*16"):
        config.load_settings()


def test_production_accepts_a_long_password(monkeypatch):
    _production_env(monkeypatch)

    assert config.load_settings().is_production


def test_a_missing_environment_name_means_production_not_local(monkeypatch):
    # With APP_ENV unset the app must not fall back to the built-in password "bakery".
    _clean_env(monkeypatch, NAMES)
    monkeypatch.setenv("MODEL_PROVIDER", "fake")

    with pytest.raises(RuntimeError, match="APP_PASSWORD"):
        config.load_settings()


def test_local_is_still_allowed_on_purpose_and_keeps_the_dev_defaults(monkeypatch):
    _clean_env(monkeypatch, NAMES)
    monkeypatch.setenv("APP_ENV", "local")

    s = config.load_settings()

    assert not s.is_production
    assert s.app_password == "bakery"


def test_quoted_value_keeps_its_hash(tmp_path, monkeypatch):
    _clean_env(monkeypatch, ["APP_PASSWORD", "TIMEZONE", "MODEL"])
    env = tmp_path / ".env"
    env.write_text('APP_PASSWORD="pa ss#word"   # team password\n'
                   "MODEL='claude-opus-5-5'\n"
                   "TIMEZONE=Asia/Jerusalem#not-a-comment\n", encoding="utf-8")
    config._load_dotenv(env)
    assert os.environ["APP_PASSWORD"] == "pa ss#word"
    assert os.environ["MODEL"] == "claude-opus-5-5"
    assert os.environ["TIMEZONE"] == "Asia/Jerusalem#not-a-comment"
