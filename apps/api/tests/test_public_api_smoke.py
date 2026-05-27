import sys
from pathlib import Path

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_health_endpoint_exposes_public_status(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("PECKER_SIGNATURE_SECRET", "x" * 32)
    monkeypatch.setenv("PECKER_JWT_SECRET", "y" * 32)

    from api.main import app

    app.state.llm_auth = {"status": "ok", "active_routes": []}
    app.state.claude_auth = "ok"

    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["service"] == "pecker-api"
