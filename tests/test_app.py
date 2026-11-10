import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.database import get_db
from app.main import app

# The client fixture's base URL ends in /api/v1. These absolute URLs leave it out, for the
# pages that stay at the root and for the old paths.
ROOT = "http://testserver"


class UnreachableDatabase:
    """Stands in for a session whose database is down."""

    def execute(self, *args, **kwargs):
        raise OperationalError("SELECT 1", None, ConnectionError("database is down"))


def test_health_reports_database_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_reports_database_unavailable(client):
    app.dependency_overrides[get_db] = UnreachableDatabase

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unavailable"}


def test_cors_allows_the_web_app_origin(client):
    origin = settings.cors_origins[0]
    response = client.options(
        "/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_cors_ignores_other_origins(client):
    response = client.options(
        "/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )

    assert "access-control-allow-origin" not in response.headers


# Every route is under /api/v1 (docs/PLAN.md); the API docs stay at the root.


def test_health_answers_under_api_v1(client):
    response = client.get(f"{ROOT}/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/health"),
        ("post", "/auth/signup"),
        ("post", "/auth/signin"),
        ("get", "/me"),
        ("get", "/profiles"),
    ],
)
def test_old_path_without_the_prefix_is_not_found(client, method, path):
    response = client.request(method, f"{ROOT}{path}")

    assert response.status_code == 404


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_stay_at_the_root(client, path):
    assert client.get(f"{ROOT}{path}").status_code == 200


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_are_not_under_the_prefix(client, path):
    assert client.get(f"{ROOT}/api/v1{path}").status_code == 404


def test_every_documented_path_is_under_api_v1(client):
    paths = client.get(f"{ROOT}/openapi.json").json()["paths"]

    assert "/api/v1/health" in paths
    assert [path for path in paths if not path.startswith("/api/v1/")] == []
