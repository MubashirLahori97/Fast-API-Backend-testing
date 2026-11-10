import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator

from app.core.errors import AppError, register_error_handlers


class Form(BaseModel):
    email: str
    age: int

    @field_validator("email")
    @classmethod
    def email_has_at_sign(cls, value: str) -> str:
        if "@" not in value:
            raise ValueError("Please enter a valid email address.")
        return value


@pytest.fixture
def error_client() -> TestClient:
    """A small app with the real error handlers and routes that fail in each way."""
    small_app = FastAPI()
    register_error_handlers(small_app)

    @small_app.post("/form")
    def submit(form: Form):
        return {"ok": True}

    @small_app.get("/taken")
    def taken():
        raise AppError(409, "email_taken", "An account with this email already exists.", "email")

    @small_app.get("/listed")
    def listed():
        raise AppError(
            422,
            "policy_not_accepted",
            "First problem.",
            "policy_version_ids",
            details=[{"field": "policy_version_ids", "message": "First problem."}],
        )

    @small_app.get("/crash")
    def crash():
        raise RuntimeError("internal detail")

    return TestClient(small_app, raise_server_exceptions=False)


def test_app_error_uses_the_error_format(error_client):
    response = error_client.get("/taken")

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "email_taken",
            "message": "An account with this email already exists.",
            "field": "email",
        }
    }


def test_app_error_can_list_details(error_client):
    response = error_client.get("/listed")

    assert response.status_code == 422
    assert response.json()["error"]["details"] == [
        {"field": "policy_version_ids", "message": "First problem."}
    ]


def test_validation_error_shows_our_message_under_the_field(error_client):
    response = error_client.post("/form", json={"email": "not-an-email", "age": 30})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["message"] == "Please enter a valid email address."
    assert error["field"] == "email"


def test_validation_error_lists_every_problem(error_client):
    response = error_client.post("/form", json={"email": "not-an-email", "age": "old"})

    fields = [detail["field"] for detail in response.json()["error"]["details"]]
    assert fields == ["email", "age"]


def test_unknown_route_uses_the_error_format(client):
    response = client.get("/no-such-route")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_unexpected_error_hides_internal_details(error_client):
    response = error_client.get("/crash")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "internal detail" not in response.text
