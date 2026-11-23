"""The three limits from architecture.md: per user per hour, per day in money,
and the file size at the door. (The per-minute limit towards Anthropic is
handled by the SDK's retries plus the backoff in agent.py.)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import Message, Run, utcnow
from .security import log_event


def local_day_start_utc(now_utc: datetime | None = None) -> datetime:
    """Midnight today in the business timezone, expressed in naive UTC (how we store)."""
    tz = ZoneInfo(settings.timezone)
    now_utc = now_utc or utcnow()
    local_now = now_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc).replace(tzinfo=None)


def messages_last_hour(db: Session, user_id: int) -> int:
    since = utcnow() - timedelta(hours=1)
    return int(db.scalar(select(func.count()).select_from(Message)
                         .where(Message.user_id == user_id, Message.role == "user", Message.created_at >= since)) or 0)


def spend_today_usd(db: Session) -> float:
    return float(db.scalar(select(func.coalesce(func.sum(Run.cost_usd), 0.0)).where(Run.created_at >= local_day_start_utc())) or 0.0)


def check_rate_limit(db: Session, user_id: int) -> None:
    used = messages_last_hour(db, user_id)
    if used >= settings.rate_limit_per_hour:
        log_event("rate_limit_hit", user_id=user_id, used=used)
        raise HTTPException(429, f"You have sent {used} messages this hour; the limit is {settings.rate_limit_per_hour}. Try again later.")


def check_daily_cap(db: Session) -> None:
    spent = spend_today_usd(db)
    if spent >= settings.daily_cap_usd:
        log_event("daily_cap_hit", spent_usd=f"{spent:.2f}", cap_usd=f"{settings.daily_cap_usd:.2f}")
        raise HTTPException(402, f"Today's budget (${settings.daily_cap_usd:.2f}) is used up. Back tomorrow.")


def check_upload_size(data_b64: str | None) -> None:
    if not data_b64:
        return
    approx_bytes = len(data_b64) * 3 // 4
    if approx_bytes > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Image is larger than {settings.max_upload_mb} MB.")
