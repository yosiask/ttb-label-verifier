"""Server-side usage protection for a public demo without login.

Budget alerts only notify; these limits stop spending. All counters are in memory,
per replica, so with a known maximum replica count the worst case is bounded:
    max cloud calls per day = CLOUD_DAILY_CAP x max replicas.
The Azure OpenAI deployment's tokens-per-minute quota is a further hard limit enforced by Azure.
CLOUD_REQUESTS_PER_MINUTE paces cloud calls per replica to stay inside that quota (set it to
roughly deployment TPM / tokens counted per label / max replicas). Over the pace, or while Azure
asks us to back off after a 429, auto mode uses offline OCR at once instead of queueing.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from datetime import datetime, timezone

from fastapi import Request


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class RateLimiter:
    """Sliding one-minute window per client IP."""

    def __init__(self, per_minute: int, window_s: float = 60.0, max_clients: int = 10_000):
        self.per_minute, self.window_s, self.max_clients = per_minute, window_s, max_clients
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> float:
        """Record a hit. Returns 0 if allowed, else seconds until the next slot frees up."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if len(self._hits) > self.max_clients:
                self._evict(now)
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] >= self.window_s:
                q.popleft()
            if len(q) >= self.per_minute:
                return max(1.0, self.window_s - (now - q[0]))
            q.append(now)
            return 0.0

    def check_n(self, key: str, n: int, now: float | None = None) -> float:
        """Record n hits at once only if all n fit. Returns 0 if recorded, else seconds to wait."""
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] >= self.window_s:
                q.popleft()
            if len(q) + n > self.per_minute:
                k = len(q) + n - self.per_minute  # hits that must expire first
                return max(0.5, self.window_s - (now - q[k - 1])) if k <= len(q) else self.window_s
            q.extend([now] * n)
            return 0.0

    def _evict(self, now: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or now - q[-1] >= self.window_s]:
            del self._hits[k]


class DailyCap:
    """Counts cloud vision calls per UTC day."""

    def __init__(self, limit: int):
        self.limit = limit
        self._day = None
        self._count = 0
        self._lock = threading.Lock()

    def _roll(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day, self._count = today, 0

    def try_take(self, n: int = 1) -> bool:
        with self._lock:
            self._roll()
            if self._count + n > self.limit:
                return False
            self._count += n
            return True

    def remaining(self) -> int:
        with self._lock:
            self._roll()
            return max(0, self.limit - self._count)


CLOUD_COOLDOWN = "The cloud AI engine is at its usage limit right now."
CLOUD_BUSY = "The cloud AI engine is busy with other labels right now."
CLOUD_CAP_REACHED = "Today's cloud AI limit has been reached."


class Protection:
    def __init__(self):
        self.rate = RateLimiter(_int_env("RATE_LIMIT_PER_MINUTE", 120))
        self.cloud_cap = DailyCap(_int_env("CLOUD_DAILY_CAP", 1000))
        pace = _int_env("CLOUD_REQUESTS_PER_MINUTE", 0)  # 0: no pacing beyond Azure's own limit
        self.cloud_pace = RateLimiter(pace) if pace > 0 else None
        self.concurrency = threading.BoundedSemaphore(_int_env("MAX_CONCURRENT_VERIFICATIONS", 4))
        self.queue_wait_s = float(os.environ.get("QUEUE_WAIT_S", "30"))
        self.trusted_proxy_hops = _int_env("TRUSTED_PROXY_HOPS", 0)
        self.cloud_wait_s = float(os.environ.get("CLOUD_WAIT_S", "45"))  # batch: wait this long for a cloud slot

    def cloud_block_reason(self, cooldown_s: float, calls: int = 1) -> str | None:
        """Why the cloud should not be called for this request (one call per label image),
        or None to call it. Counts against the pace and the daily cap only when calls will be made."""
        if cooldown_s > 0:
            return CLOUD_COOLDOWN
        if self.cloud_pace is not None and self.cloud_pace.check_n("cloud", calls):
            return CLOUD_BUSY
        if not self.cloud_cap.try_take(calls):  # counted before the call: the cost is incurred either way
            return CLOUD_CAP_REACHED
        return None

    def wait_for_cloud(self, cooldown_fn, calls: int, max_wait_s: float, sleep=time.sleep) -> str | None:
        """Like cloud_block_reason, but waits up to max_wait_s for a busy cloud to free up
        (pace or a 429 cooldown). Used by batch runs, so every label gets the cloud reader
        instead of the first ones taking all the slots. Never waits for the daily cap."""
        deadline = time.monotonic() + max_wait_s
        while True:
            reason = self.cloud_block_reason(cooldown_fn(), calls)
            left = deadline - time.monotonic()
            if reason is None or reason == CLOUD_CAP_REACHED or left <= 0:
                return reason
            sleep(min(1.0, left))

    def client_ip(self, request: Request) -> str:
        """Socket peer, or the address added by our own trusted proxies (e.g. 1 for Azure
        Container Apps ingress). Entries further left are client-supplied and ignored."""
        if self.trusted_proxy_hops > 0:
            xff = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
            if len(xff) >= self.trusted_proxy_hops:
                return xff[-self.trusted_proxy_hops]
        return request.client.host if request.client else "unknown"


PROTECTION = Protection()


def reset_for_tests() -> Protection:
    global PROTECTION
    PROTECTION = Protection()
    return PROTECTION


class BodySizeLimit:
    """ASGI middleware: refuse request bodies over the limit before they are parsed,
    whether or not the client sends Content-Length."""

    def __init__(self, app, max_bytes_fn, shown_mb_fn=None):
        """shown_mb_fn: the limit to tell the user (the image limit, not the whole-request one)."""
        self.app, self.max_bytes_fn = app, max_bytes_fn
        self.shown_mb_fn = shown_mb_fn or (lambda: max_bytes_fn() // (1024 * 1024))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            return await self.app(scope, receive, send)
        limit = self.max_bytes_fn()
        headers = dict(scope.get("headers") or [])
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = 0
        if declared > limit:
            return await _too_large(send, self.shown_mb_fn())

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await _too_large(send, self.shown_mb_fn())


class _BodyTooLarge(Exception):
    pass


async def _too_large(send, shown_mb: float) -> None:
    import json

    body = json.dumps({"error_code": "file_too_large",
                       "message": f"The image is larger than {shown_mb:g} MB. "
                                  "Use a smaller photo or lower resolution."}).encode()
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
