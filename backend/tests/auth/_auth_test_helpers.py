"""Keep browser authentication helpers scoped to these HTTP tests."""

import pytest

import main

ORIGIN = "https://aqua-ai.us"
CLIENT_ID = "123-test.apps.googleusercontent.com"
EMAIL = "reader@gmail.com"
SUBJECT = "109876543210987654321"


def headers(csrf_token: str) -> dict[str, str]:
    return {"Origin": ORIGIN, "X-CSRF-Token": csrf_token}


def challenge(browser):
    client, claims, _ = browser
    response = client.get("/api/auth/config")
    assert response.status_code == 200
    data = response.json()
    claims["nonce"] = data["nonce"]
    return data


def login(browser):
    client, _, _ = browser
    data = challenge(browser)
    response = client.post(
        "/api/auth/google",
        json={"credential": "google-id-token"},
        headers=headers(data["csrf_token"]),
    )
    assert response.status_code == 200
    return response


def forbid_pipeline(monkeypatch: pytest.MonkeyPatch) -> list:
    called = []

    def unexpected(*args, **kwargs):
        called.append(True)
        pytest.fail("Unauthenticated or unauthorized request reached the pipeline")

    monkeypatch.setattr(main, "get_schema", unexpected)
    monkeypatch.setattr(main, "answer_question", unexpected)
    return called
