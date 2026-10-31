"""Retry a flaky online request with exponential back-off.

For worker threads only: it sleeps between tries, so never call it on the UI
thread. Timeouts, connection errors and HTTP 408/429/5xx are worth another
go; any other HTTP error (404, 403 ...) won't change, so it is raised at once.
A Retry-After on a 429/503 is honoured, within the cap."""

import http.client
import time
import urllib.error

TRANSIENT_HTTP = (408, 425, 429, 500, 502, 503, 504)


def backoff(attempt, base=1.0, cap=30.0):
    """Seconds to wait after failed try number `attempt` (0, 1, 2 ...)."""
    return min(cap, base * 2 ** attempt)


def retry_after(error):
    """Seconds from an HTTPError's Retry-After header (the number form), or None."""
    try:
        return max(0.0, float(error.headers.get("Retry-After")))
    except (AttributeError, TypeError, ValueError):
        return None


def transient(error):
    """True if trying again could work."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code in TRANSIENT_HTTP
    return isinstance(error, (OSError, TimeoutError, http.client.HTTPException))   # URLError is an OSError


def call(fn, tries=3, base=1.0, cap=8.0, is_transient=transient):
    """fn() with up to `tries` attempts; the last error is raised."""
    for attempt in range(tries):
        try:
            return fn()
        except Exception as e:
            if attempt == tries - 1 or not is_transient(e):
                raise
            wait = retry_after(e) if isinstance(e, urllib.error.HTTPError) else None
            time.sleep(min(cap, wait) if wait is not None else backoff(attempt, base, cap))
