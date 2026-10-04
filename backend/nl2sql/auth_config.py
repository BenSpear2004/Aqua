"""Validate the browser origin used by Google sign-in and cookie protection."""

import re
from ipaddress import ip_address
from urllib.parse import urlsplit

_HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


def normalize_app_origin(value: str) -> str:
    """Normalize one browser origin, raising a redacted ValueError if invalid."""
    error = (
        "APP_ORIGIN must be a single HTTPS origin without credentials, path, "
        "query or fragment; HTTP is allowed only for localhost development."
    )
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(error)
    if "\\" in value:
        raise ValueError(error)
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError(error) from None
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or "?" in value
        or "#" in value
        or port == 0
        or parsed.netloc.endswith(":")
        or "%" in hostname
    ):
        raise ValueError(error)
    try:
        ip_address(hostname)
    except ValueError:
        if len(hostname) > 253 or not all(
            _HOST_LABEL.fullmatch(label) for label in hostname.split(".")
        ):
            raise ValueError(error) from None
    if ":" in hostname:
        if not re.fullmatch(r"\[[0-9a-fA-F:.]+\](?::[0-9]+)?", parsed.netloc):
            raise ValueError(error)
    elif "[" in parsed.netloc or "]" in parsed.netloc:
        raise ValueError(error)
    if parsed.scheme == "http" and hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError(error)
    host = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and port != (443 if parsed.scheme == "https" else 80):
        host = f"{host}:{port}"
    return f"{parsed.scheme}://{host}"
