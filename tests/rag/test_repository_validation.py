"""Found in an independent review pass: /search and /chat accepted any
repository_id with no existence check, unlike /reindex — a bad id silently returned
an empty result set (/search) or fell into agent logic against a nonexistent
repository (/chat) instead of a clean 404."""
from fastapi.testclient import TestClient

from apps.backend.main import app


def test_search_rejects_unknown_repository_id():
    client = TestClient(app)
    resp = client.post("/api/v1/search", json={"repository_id": 999999, "query": "x"})
    assert resp.status_code == 404


def test_chat_rejects_unknown_repository_id():
    client = TestClient(app)
    resp = client.post("/api/v1/chat", json={"repository_id": 999999, "message": "x"})
    assert resp.status_code == 404
