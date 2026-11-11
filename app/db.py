"""Database layer: models, engine, session, startup migration and seeding.

Postgres on Railway (DATABASE_URL from the plugin) or SQLite locally. The
schema is created at start with `create_all`; `schema_version` records which
version is live so a later real migration tool has somewhere to start.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    create_engine,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .config import ROOT, settings

SCHEMA_VERSION = 1


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Conversation(Base):
    """One chat: owner and title, the sidebar list. Table `chats`; `conversations` is the log below."""

    __tablename__ = "chats"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("chats.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)  # plain text shown in the UI
    has_image: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Run(Base):
    """One model turn: the record behind the cost cap, the digest and the runbook."""

    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("chats.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    model: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok | refusal | error | aborted | capped
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_names: Mapped[str] = mapped_column(String(200), default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# The conversation log, for people who read the database (Railway's Data tab): one row per question,
# with the sign-in name beside the ids. Plain columns, no primary key: nothing in the app reads it
# back and a row is written once, when the turn ends. Times are UTC. `time_message_sent` is when the
# reply finished and stays empty when no reply was saved (error, or the browser went away).
conversation_log = Table(
    "conversations",
    Base.metadata,
    Column("conversation_id", Integer, ForeignKey("chats.id"), nullable=False, index=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
    Column("user_name", String(40), nullable=False),
    Column("message", Text, nullable=False),
    Column("time_user_entered", DateTime, nullable=False, index=True),
    Column("time_message_sent", DateTime, nullable=True),
)


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    item: Mapped[str] = mapped_column(String(120))
    unit: Mapped[str] = mapped_column(String(20))
    price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3))


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier: Mapped[str] = mapped_column(String(120), index=True)
    invoice_number: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="ILS")
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="logged")  # logged | needs_a_look
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)  # over the spec threshold
    source_ref: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)  # the dedup key
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    logged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Sale(Base):
    """One line of the Lesson 4 bakery dataset (29,115 rows, Sep 2025 to Aug 2026)."""

    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(String(20), index=True)
    order_datetime: Mapped[datetime] = mapped_column(DateTime)
    order_date: Mapped[date] = mapped_column(Date, index=True)
    branch: Mapped[str] = mapped_column(String(60), index=True)
    channel: Mapped[str] = mapped_column(String(30))
    payment_method: Mapped[str] = mapped_column(String(20))
    customer_type: Mapped[str] = mapped_column(String(20))
    product: Mapped[str] = mapped_column(String(60), index=True)
    category: Mapped[str] = mapped_column(String(30))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column(Float)
    line_total: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), index=True)  # completed | refunded


# ---------------------------------------------------------------------------
# Engine and session
# ---------------------------------------------------------------------------

def make_engine(url: str | None = None):
    url = url or settings.database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Startup: schema, version, seed data
# ---------------------------------------------------------------------------

def _retire_old_conversations_layout(bind) -> None:
    """One-time switch (2026-11-11): the old `conversations` table (id, user_id, title) became `chats`
    and the name now belongs to the log above. `create_all` never alters a table, so while the old
    layout is still there, and only if it holds no chats, drop it with the two tables that point at it
    (`messages`, `runs`) and the short-lived view; `create_all` then builds all of them fresh. If
    anything has been saved, stop with a clear message instead of deleting it."""
    insp = inspect(bind)
    tables = set(insp.get_table_names())
    if "conversations" not in tables or "title" not in {c["name"] for c in insp.get_columns("conversations")}:
        return  # new database, or already switched
    doomed = [t for t in ("messages", "runs", "conversations") if t in tables]  # children first
    with bind.begin() as conn:
        held = {t: conn.scalar(text(f"SELECT COUNT(*) FROM {t}")) for t in doomed}
        if any(held.values()):
            raise RuntimeError(
                "The old `conversations` table (id, user_id, title) still holds chats, so it was not replaced "
                f"by the new layout. Rows now: {held}. Export what you need, then drop `messages`, `runs` and "
                "`conversations` and start again (runbook.md)."
            )
        conn.execute(text("DROP VIEW IF EXISTS conversations_with_user"))
        for t in doomed:
            conn.execute(text(f"DROP TABLE {t}"))


def init_db(bind=None, data_dir: Path | None = None) -> dict:
    """Create tables, record the schema version, seed reference data if empty."""
    bind = bind or engine
    data_dir = data_dir or (ROOT / "data")
    _retire_old_conversations_layout(bind)
    Base.metadata.create_all(bind)
    report = {"schema_version": SCHEMA_VERSION, "suppliers_seeded": 0, "sales_seeded": 0}
    with Session(bind) as db:
        if db.scalar(select(func.count()).select_from(SchemaVersion)) == 0:
            db.add(SchemaVersion(version=SCHEMA_VERSION))
            db.commit()
        if db.scalar(select(func.count()).select_from(Supplier)) == 0:
            report["suppliers_seeded"] = _seed_suppliers(db, data_dir / "suppliers.csv")
        if db.scalar(select(func.count()).select_from(Sale)) == 0:
            report["sales_seeded"] = _seed_sales(db, data_dir / "bakery_sales.csv")
    return report


def _seed_suppliers(db: Session, path: Path) -> int:
    if not path.exists():
        return 0
    rows = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(Supplier(name=r["supplier"].strip(), item=r["item"].strip(), unit=r["unit"].strip(),
                                 price=float(r["price"]), currency=r["currency"].strip().upper()))
    db.add_all(rows)
    db.commit()
    return len(rows)


def _seed_sales(db: Session, path: Path, chunk: int = 2000) -> int:
    if not path.exists():
        return 0
    total = 0
    batch: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            dt = datetime.strptime(r["order_datetime"], "%Y-%m-%d %H:%M")
            # Clean at the door (Lesson 5): the source file has a "Herzliya " variant with a trailing space.
            batch.append({
                "order_id": r["order_id"].strip(), "order_datetime": dt, "order_date": dt.date(),
                "branch": r["branch"].strip(), "channel": r["channel"].strip(), "payment_method": r["payment_method"].strip(),
                "customer_type": r["customer_type"].strip(), "product": r["product"].strip(), "category": r["category"].strip(),
                "quantity": int(r["quantity"]), "unit_price": float(r["unit_price"]),
                "line_total": float(r["line_total"]), "status": r["status"],
            })
            if len(batch) >= chunk:
                db.execute(Sale.__table__.insert(), batch)
                total += len(batch)
                batch = []
    if batch:
        db.execute(Sale.__table__.insert(), batch)
        total += len(batch)
    db.commit()
    return total
