"""Verify Google's signed identity, without accessing any customer database."""

from functools import partial
from typing import Any

import requests
from google.auth.transport.requests import Request
from google.oauth2 import id_token


def verify_google_token(credential: str, client_id: str) -> dict[str, Any]:
    """The SDK checks the signature, client audience, issuer and token lifetime."""
    with requests.Session() as session:
        transport = partial(Request(session=session), timeout=5)
        try:
            return dict(
                id_token.verify_oauth2_token(credential, transport, audience=client_id)
            )
        except (TypeError, KeyError) as exc:
            # Malformed untrusted JWT header/claim types can trigger these
            # exceptions inside the SDK before signature checking finishes.
            raise ValueError("Malformed Google identity token.") from exc
