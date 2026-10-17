"""Telling clients apart for the per-client limit, without keeping their addresses."""

import hashlib

from fastapi import Request

from incident_agent.config import Settings

UNKNOWN_ADDRESS = "unknown"


def forwarded_address(header: str | None) -> str | None:
    """The first address of an `X-Forwarded-For` value, or None if it holds none."""
    if not header:
        return None
    return header.split(",")[0].strip() or None


def client_address(request: Request) -> str:
    """The address behind the request: the forwarded one if a proxy added it, else the socket's."""
    forwarded = forwarded_address(request.headers.get("x-forwarded-for"))
    if forwarded:
        return forwarded
    return request.client.host if request.client else UNKNOWN_ADDRESS


def hash_address(address: str, settings: Settings) -> str:
    """16 hex characters of sha256(salt + address): all that is ever stored of a client."""
    salt = settings.client_hash_salt.get_secret_value() if settings.client_hash_salt else ""
    return hashlib.sha256((salt + address).encode()).hexdigest()[:16]


def client_key(request: Request, settings: Settings) -> str:
    return hash_address(client_address(request), settings)
