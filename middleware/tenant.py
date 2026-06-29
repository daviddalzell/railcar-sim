from dataclasses import dataclass
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from database import SessionLocal, _is_sqlite

# Paths that bypass tenant resolution entirely
_BYPASS_PATHS = {"/health", "/static", "/favicon.ico"}
_BYPASS_SLUGS = {"www", "api"}


@dataclass
class TenantContext:
    id: int
    slug: str
    name: str
    schema_name: str | None
    subscription_status: str
    subscription_expires_at: datetime | None
    gemini_api_key: str | None
    anthropic_api_key: str | None
    openai_api_key: str | None
    vision_provider: str | None


_LOCAL_TENANT = TenantContext(
    id=0,
    slug="local",
    name="Local Dev",
    schema_name=None,
    subscription_status="active",
    subscription_expires_at=None,
    gemini_api_key=None,
    anthropic_api_key=None,
    openai_api_key=None,
    vision_provider=None,
)

_cache: dict[str, TenantContext | None] = {}


def _lookup(slug: str) -> TenantContext | None:
    if slug in _cache:
        return _cache[slug]
    from models import Tenant
    db = SessionLocal()
    try:
        t = db.query(Tenant).filter(Tenant.slug == slug).first()
        if not t:
            _cache[slug] = None
            return None
        ctx = TenantContext(
            id=t.id,
            slug=t.slug,
            name=t.name,
            schema_name=t.schema_name,
            subscription_status=t.subscription_status,
            subscription_expires_at=t.subscription_expires_at,
            gemini_api_key=t.gemini_api_key,
            anthropic_api_key=t.anthropic_api_key,
            openai_api_key=t.openai_api_key,
            vision_provider=t.vision_provider,
        )
        _cache[slug] = ctx
        return ctx
    finally:
        db.close()


def invalidate_tenant_cache(slug: str | None = None):
    """Call after updating a tenant record."""
    if slug:
        _cache.pop(slug, None)
    else:
        _cache.clear()


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Local SQLite dev: skip DB lookup, use synthetic tenant
        if _is_sqlite:
            request.state.tenant = _LOCAL_TENANT
            return await call_next(request)

        # Static files and health don't need a tenant
        path = request.url.path
        if any(path.startswith(p) for p in _BYPASS_PATHS):
            request.state.tenant = None
            return await call_next(request)

        host = request.headers.get("host", "")
        slug = host.split(".")[0].split(":")[0]

        if slug in _BYPASS_SLUGS:
            request.state.tenant = None
            return await call_next(request)

        tenant = _lookup(slug)
        if not tenant:
            return Response(f"Unknown tenant: {slug!r}", status_code=404)

        if tenant.subscription_status == "suspended":
            expires = tenant.subscription_expires_at
            if expires and expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if not expires or expires < datetime.now(timezone.utc):
                return Response("Subscription expired", status_code=402)
            request.state.subscription_warning = True

        request.state.tenant = tenant
        return await call_next(request)
