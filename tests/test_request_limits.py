"""Request size (app/security.py, SecurityProblems.md SP-03): big bodies are refused before anyone reads them."""
from app.config import settings

B64_CAP = settings.max_upload_mb * 1024 * 1024 * 4 // 3 + 4  # longest base64 string that decodes to the upload limit


def _chat_body(data_len: int) -> dict:
    return {"message": "x", "image": {"media_type": "image/png", "data": "A" * data_len}}


def test_a_huge_body_is_refused_before_login_is_even_checked(client):
    client.cookies.clear()

    r = client.post("/api/chat", json=_chat_body(20 * 1024 * 1024))

    assert r.status_code == 413  # not 401: it was never parsed


def test_a_body_without_a_length_is_refused(client):
    client.cookies.clear()

    r = client.post("/api/chat", content=(b"x" for _ in range(3)))  # sent as chunked, no Content-Length

    assert r.status_code == 411


def test_an_image_longer_than_the_upload_limit_is_rejected_by_validation(client, logged_in):
    r = client.post("/api/chat", json=_chat_body(B64_CAP + 1000))  # under the byte cap, over the field cap

    assert r.status_code == 422
    assert len(r.content) < 2000 and "AAAAAAAA" not in r.text  # the error never echoes the rejected input back


def test_a_refusal_still_carries_the_security_headers(client):
    r = client.post("/api/chat", json=_chat_body(20 * 1024 * 1024))

    assert r.status_code == 413
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"]


def test_normal_requests_still_work(client, logged_in, fake):
    assert client.post("/api/logout").status_code == 204  # an empty POST has no body and no Content-Length problem
    assert client.get("/health").status_code == 200
