# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

from functools import lru_cache

import httpx
from starlette.requests import Request

# EU 27, EEA non-EU, UK, Switzerland
_RESTRICTED_COUNTRIES = frozenset({
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR",
    "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO",
    "SE", "SI", "SK",
    "IS", "LI", "NO",  # EEA
    "GB",              # UK
    "CH",              # Switzerland
})


def get_client_ip(request: Request) -> str:
    return (
        request.headers.get("Fly-Client-IP")
        or (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        or (request.client.host if request.client else "")
    )


@lru_cache(maxsize=4096)
def _lookup_country(ip: str) -> str | None:
    if not ip or ip in ("127.0.0.1", "::1", "localhost"):
        return None
    try:
        r = httpx.get(f"https://ipapi.co/{ip}/country/", timeout=2.0)
        code = r.text.strip()
        return code if len(code) == 2 else None
    except Exception:
        return None


def is_restricted_region(ip: str) -> bool:
    """Return True if the IP is in EU/UK/Switzerland. Fails open (returns False) on error."""
    country = _lookup_country(ip)
    return country in _RESTRICTED_COUNTRIES if country else False


def is_free_tier(tenant) -> bool:
    """Return True if the tenant has no personal API key (using the shared server key)."""
    return not (
        getattr(tenant, "gemini_api_key", None)
        or getattr(tenant, "anthropic_api_key", None)
        or getattr(tenant, "openai_api_key", None)
    )
