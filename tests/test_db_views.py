"""The conversations_with_user view (app/db.py): the sign-in name shown next to user_id."""
from sqlalchemy import text

from app import auth
from app.db import Conversation, init_db


def _row(db, conversation_id: int):
    return db.execute(text("SELECT * FROM conversations_with_user WHERE id = :i"), {"i": conversation_id}).mappings().one()


def test_view_puts_the_sign_in_name_right_after_user_id(client, db):
    user = auth.get_or_create_user(db, "Noa Levi")
    conv = Conversation(user_id=user.id, title="Challah in August")
    db.add(conv)
    db.commit()

    row = _row(db, conv.id)

    assert list(row.keys())[:3] == ["id", "user_id", "user_name"]
    assert row["user_id"] == user.id
    assert row["user_name"] == "Noa Levi"
    assert row["title"] == "Challah in August"


def test_view_follows_each_user_and_survives_a_second_start(client, db):
    dana = auth.get_or_create_user(db, "Dana")
    omer = auth.get_or_create_user(db, "Omer")
    a = Conversation(user_id=dana.id, title="A")
    b = Conversation(user_id=omer.id, title="B")
    db.add_all([a, b])
    db.commit()

    init_db()  # a restart drops and recreates the view; it must not fail or lose rows

    assert _row(db, a.id)["user_name"] == "Dana"
    assert _row(db, b.id)["user_name"] == "Omer"
