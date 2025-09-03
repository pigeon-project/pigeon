from fastapi.testclient import TestClient

from app.main import app


def test_health():
    client = TestClient(app)
    assert client.get("/v1/health").json() == {"status": "ok"}
