"""Telling clients apart for the per-client limit, without keeping their addresses."""

import hashlib
import json

from fastapi import Request

from incident_agent.config import Settings

UNKNOWN_ADDRESS = "unknown"


def context_source_ip(header: str | None) -> str | None:
    """`http.sourceIp` from the Lambda request context the web adapter adds, or None.

    AWS sets this address, so unlike `X-Forwarded-For` the caller cannot choose it.
    """
    if not header:
        return None
    try:
        context = json.loads(header)
        source_ip = context["http"]["sourceIp"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(source_ip, str):
        return None
    return source_ip.strip() or None


def last_forwarded_address(header: str | None) -> str | None:
    """The last address of an `X-Forwarded-For` value (the one the nearest proxy added), or None."""
    if not header:
        return None
    return header.split(",")[-1].strip() or None


def client_address(request: Request) -> str:
    """The caller's address: AWS's source IP, else the last forwarded one, else the socket's."""
    return (
        context_source_ip(request.headers.get("x-amzn-request-context"))
        or last_forwarded_address(request.headers.get("x-forwarded-for"))
        or (request.client.host if request.client else UNKNOWN_ADDRESS)
    )


def hash_address(address: str, settings: Settings) -> str:
    """16 hex characters of sha256(salt + address): all that is ever stored of a client."""
    salt = settings.client_hash_salt.get_secret_value() if settings.client_hash_salt else ""
    return hashlib.sha256((salt + address).encode()).hexdigest()[:16]


def client_key(request: Request, settings: Settings) -> str:
    return hash_address(client_address(request), settings)
