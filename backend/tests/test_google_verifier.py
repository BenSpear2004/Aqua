"""Check the Google verification boundary without fetching keys or using secrets."""

import base64
import json
import time
from types import SimpleNamespace

import pytest

from auth import google


@pytest.fixture
def certificate_transport(monkeypatch: pytest.MonkeyPatch) -> list:
    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status=200, data=b'{"test-key": "unused"}')

    monkeypatch.setattr(google, "Request", lambda session: request)
    return calls


def test_google_sdk_receives_exact_audience_and_bounded_transport(
    monkeypatch: pytest.MonkeyPatch, certificate_transport
) -> None:
    def verify(credential, request, audience):
        assert credential == "identity-token"
        assert audience == "123.apps.googleusercontent.com"
        request("https://www.googleapis.com/oauth2/v1/certs", method="GET")
        return {"sub": "google-subject"}

    monkeypatch.setattr(google.id_token, "verify_oauth2_token", verify)
    assert google.verify_google_token(
        "identity-token", "123.apps.googleusercontent.com"
    ) == {"sub": "google-subject"}
    assert certificate_transport[0][1]["timeout"] == 5


def _encoded(value: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()


@pytest.mark.parametrize(
    "header",
    [
        {"alg": [], "kid": "test-key"},
        {"alg": {}, "kid": "test-key"},
        {"alg": "RS256", "kid": []},
        {"alg": "RS256", "kid": {}},
        {"alg": "RS256"},
    ],
)
def test_malformed_untrusted_jwt_headers_are_invalid_credentials(
    certificate_transport, header
) -> None:
    payload = {"iat": int(time.time()), "exp": int(time.time()) + 60}
    credential = f"{_encoded(header)}.{_encoded(payload)}.c2lnbmF0dXJl"
    with pytest.raises(ValueError):
        google.verify_google_token(credential, "123.apps.googleusercontent.com")
    assert len(certificate_transport) == 1
