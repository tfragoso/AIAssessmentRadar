"""Polite HTTP client: robots.txt, 1 req/s per host, retries with backoff, per-run disk cache."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; jobwatch/0.1)"
MIN_INTERVAL = 1.0  # seconds between requests to the same host
RETRY_STATUS = {429, 500, 502, 503, 504}


class RobotsDisallowed(Exception):
    pass


class OfflineMiss(Exception):
    """Raised in offline mode when a request is not in the cache."""


class Client:
    def __init__(self, cache_dir: Path | None = None, offline: bool = False, retries: int = 3):
        self.cache_dir = cache_dir
        self.offline = offline
        self.retries = retries
        self._last: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()  # sources run in parallel threads; hosts are throttled one at a time
        self._http = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en,de;q=0.8,fr;q=0.7"},
            timeout=30.0,
            follow_redirects=True,
        )
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        self._http.close()

    # -- public API -------------------------------------------------------
    def get_text(self, url: str, params: dict | None = None, headers: dict | None = None) -> str:
        return self._request("GET", url, params=params, headers=headers)

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None):
        h = {"Accept": "application/json", **(headers or {})}
        return json.loads(self._request("GET", url, params=params, headers=h))

    def post_json(self, url: str, body: dict, headers: dict | None = None):
        h = {"Accept": "application/json", "Content-Type": "application/json", **(headers or {})}
        return json.loads(self._request("POST", url, body=body, headers=h))

    # -- internals --------------------------------------------------------
    def _cache_path(self, method: str, url: str, params, body) -> Path | None:
        if not self.cache_dir:
            return None
        key = json.dumps([method, url, params or {}, body or {}], sort_keys=True)
        return self.cache_dir / (hashlib.sha1(key.encode()).hexdigest() + ".txt")

    def _request(self, method, url, params=None, body=None, headers=None) -> str:
        path = self._cache_path(method, url, params, body)
        if path and path.exists():
            return path.read_text(encoding="utf-8")
        if self.offline:
            raise OfflineMiss(url)
        if not self.allowed(url):
            raise RobotsDisallowed(url)

        delay = 2.0
        for attempt in range(self.retries + 1):
            self._throttle(url)
            try:
                resp = self._http.request(method, url, params=params, json=body, headers=headers)
            except httpx.TransportError as e:
                if attempt == self.retries:
                    raise
                log.debug("transport error %s on %s, retrying", e, url)
            else:
                if resp.status_code in RETRY_STATUS and attempt < self.retries:
                    log.debug("HTTP %s on %s, retrying", resp.status_code, url)
                else:
                    resp.raise_for_status()
                    text = resp.text
                    if path:
                        path.write_text(text, encoding="utf-8")
                    return text
            time.sleep(delay)
            delay *= 2
        raise RuntimeError("unreachable")

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc
        with self._guard:
            lock = self._locks.setdefault(host, threading.Lock())
        with lock:
            wait = self._last.get(host, 0) + MIN_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = RobotFileParser()
            try:
                self._throttle(url)
                r = self._http.get(base + "/robots.txt")
                if r.status_code >= 400:
                    rp = None  # no robots.txt: everything allowed
                else:
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError:
                rp = None
            self._robots[base] = rp
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(USER_AGENT, url)
