"""Redis response-cache service.

Architecture note
-----------------
All route handlers in this project are **synchronous** FastAPI routes.
Using the standard (sync) ``redis.Redis`` client avoids any sync/async
bridging complexity while keeping the decorator implementation simple and
straightforward.  The cache falls through transparently if Redis is
unavailable so the API degrades gracefully without returning errors.
"""

import json
import logging
import functools
from collections.abc import Callable
from typing import Any

import redis
from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)

CACHE_PREFIX = "tracker:cache:"

# Module-level singleton; initialised lazily or explicitly via init_redis().
_client: redis.Redis | None = None


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


def get_client() -> redis.Redis:
    """Return the module-level Redis client, creating it on first call."""
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def init_redis() -> None:
    """Eagerly create the Redis client and verify connectivity with PING.

    Called from the FastAPI lifespan startup hook so connection errors
    surface immediately rather than on the first cache access.
    """
    client = get_client()
    client.ping()
    logger.info("Redis connection established: %s", settings.redis_url)


def close_redis() -> None:
    """Close the global Redis connection pool.

    Called from the FastAPI lifespan shutdown hook.
    """
    global _client
    if _client is not None:
        _client.close()
        _client = None
        logger.info("Redis connection closed")


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------


def _make_cache_key(request: Request) -> str:
    """Build a deterministic Redis key from the full request URL.

    Query parameters are included verbatim so that
    ``/countries?year=2023`` and ``/countries?year=2022`` produce distinct
    keys.  Example output: ``tracker:cache:/countries?year=2023``.
    """
    query = str(request.url.query)
    suffix = f"{request.url.path}?{query}" if query else request.url.path
    return f"{CACHE_PREFIX}{suffix}"


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def cache_response(ttl: int = 3600) -> Callable:
    """Decorator that transparently caches a FastAPI route's JSON response.

    Usage::

        @router.get("/")
        @cache_response(ttl=3600)
        def my_route(request: Request, ...):
            ...

    **Requirements**

    * The decorated function **must** include a ``request: Request``
      parameter.  FastAPI injects this automatically; the decorator uses it
      to build the cache key.
    * Because ``functools.wraps`` sets ``__wrapped__``, FastAPI's
      ``inspect.signature`` call follows the chain and sees the original
      parameter list, so dependency injection (``Depends``, query params,
      ``Request``) works exactly as without the decorator.

    **Failure mode**

    Redis errors are caught and logged at WARNING level.  On a read error
    the request is served normally (cache-miss path).  On a write error
    the result is returned to the client without being cached.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            request: Request | None = kwargs.get("request")

            if request is None:
                # Guard: if the route omitted Request, skip caching entirely.
                logger.debug("cache_response: no Request found — bypassing cache for %s", func.__name__)
                return func(*args, **kwargs)

            cache_key = _make_cache_key(request)

            # ---- cache read ----
            try:
                cached = get_client().get(cache_key)
                if cached is not None:
                    logger.debug("Cache HIT  %s", cache_key)
                    return JSONResponse(content=json.loads(cached))
            except redis.RedisError as exc:
                logger.warning("Redis read error (cache miss fallback): %s", exc)

            # ---- execute route ----
            result = func(*args, **kwargs)

            # ---- cache write ----
            try:
                serialized = json.dumps(jsonable_encoder(result))
                get_client().setex(cache_key, ttl, serialized)
                logger.debug("Cache SET  %s  ttl=%ds", cache_key, ttl)
            except redis.RedisError as exc:
                logger.warning("Redis write error (result not cached): %s", exc)

            return result

        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


def clear_all_cache() -> int:
    """Delete every ``tracker:cache:*`` key using SCAN (non-blocking).

    Prefers ``scan_iter`` over ``KEYS`` to avoid blocking Redis on large
    keyspaces.

    Returns:
        Number of keys deleted, or 0 if Redis is unavailable.
    """
    try:
        client = get_client()
        keys = list(client.scan_iter(f"{CACHE_PREFIX}*"))
        if not keys:
            logger.debug("clear_all_cache: no keys to delete")
            return 0
        deleted: int = client.delete(*keys)
        logger.info("Cache cleared: %d key(s) deleted", deleted)
        return deleted
    except redis.RedisError as exc:
        logger.error("Redis error while clearing cache: %s", exc)
        return 0
