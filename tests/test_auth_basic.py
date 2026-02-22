"""FIX 3 Tests: Dashboard Basic Auth.

- Auth config varken /static/index.html creds olmadan 401
- Dogru creds ile 200
- /health her zaman 200
"""

import base64
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_basic_header(username: str, password: str) -> dict:
    """Basic auth header olustur."""
    creds = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


def _create_auth_app(db_path: str, username: str = "admin", password: str = "secret"):
    """Auth middleware ile test app olustur."""
    from src.dashboard.api import router as dashboard_router
    from src.main import BasicAuthMiddleware

    app = FastAPI()
    app.add_middleware(BasicAuthMiddleware, username=username, password=password)
    app.include_router(dashboard_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/")
    async def root():
        return {"page": "home"}

    # Mock app state
    app.state.db_path = db_path
    app.state.mqtt_collector = MagicMock(is_connected=MagicMock(return_value=False))

    return app


def test_auth_required_returns_401(initialized_db):
    """Auth config varken creds olmadan /api/status 401 donmeli."""
    app = _create_auth_app(initialized_db)
    client = TestClient(app)

    resp = client.get("/api/status")
    assert resp.status_code == 401


def test_auth_correct_creds_returns_200(initialized_db):
    """Dogru creds ile /api/status 200 donmeli."""
    app = _create_auth_app(initialized_db, username="admin", password="secret")
    client = TestClient(app)

    headers = _make_basic_header("admin", "secret")
    resp = client.get("/api/status", headers=headers)
    assert resp.status_code == 200


def test_auth_wrong_creds_returns_401(initialized_db):
    """Yanlis creds ile 401 donmeli."""
    app = _create_auth_app(initialized_db, username="admin", password="secret")
    client = TestClient(app)

    headers = _make_basic_header("admin", "wrong_password")
    resp = client.get("/api/status", headers=headers)
    assert resp.status_code == 401


def test_health_always_200_without_auth(initialized_db):
    """/health auth olmadan her zaman 200 donmeli."""
    app = _create_auth_app(initialized_db)
    client = TestClient(app)

    resp = client.get("/health")
    assert resp.status_code == 200


def test_root_requires_auth(initialized_db):
    """Root (/) auth gerektirmeli."""
    app = _create_auth_app(initialized_db)
    client = TestClient(app)

    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 401


def test_auth_disabled_when_empty_creds(initialized_db):
    """Username/password bos iken auth devre disi, tum yollar 200."""
    app = _create_auth_app(initialized_db, username="", password="")
    client = TestClient(app)

    resp = client.get("/api/status")
    assert resp.status_code == 200

    resp = client.get("/")
    assert resp.status_code == 200
