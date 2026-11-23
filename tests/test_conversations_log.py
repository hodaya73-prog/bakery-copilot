"""The `conversations` table (app/db.py): one row per question, with the sign-in name and two times.

Columns, in order: conversation_id, user_id, user_name, message, time_message_sent, time_answer_sent.
`time_message_sent` is when the user's message came in; `time_answer_sent` is when the bot's reply finished.
The app's own chat list lives in `chats`; messages keep both sides of every chat.
"""
import pytest
from sqlalchemy import create_engine, inspect, select, text

from app.agent import ModelEvent, run_turn
from app.costs import Usage
from app.db import SessionLocal, User, conversation_log, init_db
from tests.conftest import read_sse

COLUMNS = ["conversation_id", "user_id", "user_name", "message", "time_message_sent", "time_answer_sent"]


def _reply(text_: str):
    return [ModelEvent(type="text", text=text_),
            ModelEvent(type="stop", stop_reason="end_turn", usage=Usage(10, 5), content=[{"type": "text", "text": text_}])]


def _rows(db, conversation_id: int):
    q = select(conversation_log).where(conversation_log.c.conversation_id == conversation_id).order_by(conversation_log.c.time_message_sent)
    return db.execute(q).mappings().all()


def test_table_has_exactly_the_six_columns_in_order():
    assert conversation_log.name == "conversations"
    assert conversation_log.c.keys() == COLUMNS


def test_an_answered_question_is_stored_with_name_and_both_times(client, db, logged_in, fake):
    fake.turns.append(_reply("Challah sold best."))
    events = read_sse(client.post("/api/chat", json={"message": "What sold best last week?"}))
    conv_id = events[0]["conversation_id"]

    (row,) = _rows(db, conv_id)

    assert list(row.keys()) == COLUMNS
    assert row["conversation_id"] == conv_id
    assert row["user_id"] == logged_in["id"]
    assert row["user_name"] == "Dana"
    assert row["message"] == "What sold best last week?"
    assert row["time_message_sent"] is not None
    assert row["time_answer_sent"] >= row["time_message_sent"]


def test_each_follow_up_gets_its_own_row_in_the_same_conversation(client, db, logged_in, fake):
    fake.turns.extend([_reply("First answer."), _reply("Second answer.")])
    first = read_sse(client.post("/api/chat", json={"message": "first question"}))
    conv_id = first[0]["conversation_id"]
    read_sse(client.post("/api/chat", json={"message": "second question", "conversation_id": conv_id}))

    rows = _rows(db, conv_id)

    assert [r["message"] for r in rows] == ["first question", "second question"]
    assert {r["user_name"] for r in rows} == {"Dana"}


def test_a_dropped_connection_keeps_the_question_but_has_no_answer_time(client, db, logged_in, fake):
    fake.turns.append(_reply("This reply will be cut off."))
    with SessionLocal() as s:
        user = s.query(User).filter_by(name="Dana").one()
        gen = run_turn(s, user=user, conversation=None, text="cut me off", image=None, client=fake)
        meta = next(gen)
        next(gen)
        gen.close()

    (row,) = _rows(db, meta["conversation_id"])

    assert row["message"] == "cut me off"
    assert row["time_message_sent"] is not None
    assert row["time_answer_sent"] is None


# ---- the one-time switch from the old layout (conversations with a title) ----

OLD_LAYOUT = """
CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR(40) UNIQUE, created_at DATETIME);
CREATE TABLE conversations (id INTEGER PRIMARY KEY, user_id INTEGER, title VARCHAR(120), created_at DATETIME, updated_at DATETIME);
CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INTEGER REFERENCES conversations(id), user_id INTEGER,
                       role VARCHAR(10), content TEXT, has_image BOOLEAN, created_at DATETIME);
CREATE TABLE runs (id INTEGER PRIMARY KEY, conversation_id INTEGER REFERENCES conversations(id), user_id INTEGER, model VARCHAR(60));
CREATE VIEW conversations_with_user AS SELECT c.id, c.user_id, u.name AS user_name FROM conversations c JOIN users u ON u.id = c.user_id;
"""


def _old_database(tmp_path, with_data: bool):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        for stmt in [s for s in OLD_LAYOUT.split(";") if s.strip()]:
            conn.execute(text(stmt))
        if with_data:
            conn.execute(text("INSERT INTO users (id, name) VALUES (1, 'Dana')"))
            conn.execute(text("INSERT INTO conversations (id, user_id, title) VALUES (1, 1, 'hello')"))
    return engine


def test_an_empty_old_layout_is_replaced_by_the_new_tables(tmp_path):
    engine = _old_database(tmp_path, with_data=False)

    init_db(bind=engine, data_dir=tmp_path)

    insp = inspect(engine)
    assert [c["name"] for c in insp.get_columns("conversations")] == COLUMNS
    assert {"chats", "messages", "runs"} <= set(insp.get_table_names())
    assert "conversations_with_user" not in insp.get_view_names()
    init_db(bind=engine, data_dir=tmp_path)  # a second start changes nothing and does not fail


def test_an_old_layout_that_holds_chats_stops_startup_instead_of_losing_them(tmp_path):
    engine = _old_database(tmp_path, with_data=True)

    with pytest.raises(RuntimeError, match="conversations"):
        init_db(bind=engine, data_dir=tmp_path)

    assert "title" in [c["name"] for c in inspect(engine).get_columns("conversations")]  # untouched


# ---- the one-time rename of the two time columns (the layout first deployed on 2026-11-11) ----

FIRST_SIX_COLUMNS = """
CREATE TABLE conversations (conversation_id INTEGER NOT NULL, user_id INTEGER NOT NULL, user_name VARCHAR(40) NOT NULL,
                            message TEXT NOT NULL, time_user_entered DATETIME NOT NULL, time_message_sent DATETIME)
"""


def test_the_first_time_column_names_are_renamed_and_their_values_move_with_them(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'first.db'}")
    with engine.begin() as conn:
        conn.execute(text(FIRST_SIX_COLUMNS))
        conn.execute(text("INSERT INTO conversations VALUES (7, 1, 'Dana', 'hi', '2026-11-11 10:00:00', '2026-11-11 10:00:05')"))

    init_db(bind=engine, data_dir=tmp_path)

    assert [c["name"] for c in inspect(engine).get_columns("conversations")] == COLUMNS
    with engine.connect() as conn:
        row = conn.execute(select(conversation_log)).mappings().one()
    assert str(row["time_message_sent"]) == "2026-11-11 10:00:00"  # was time_user_entered
    assert str(row["time_answer_sent"]) == "2026-11-11 10:00:05"  # was time_message_sent
    init_db(bind=engine, data_dir=tmp_path)  # run twice: the second start must be a no-op
    assert [c["name"] for c in inspect(engine).get_columns("conversations")] == COLUMNS
