# -*- coding: utf-8 -*-

"""
Pool of upstream proxies loaded from `proxy.txt`.

Each non-empty / non-comment line is one of:
  - A static proxy: `host:port:user:pass` (or `host:port`).
  - A gateway template containing `{sid}` somewhere in the user/pass field;
    each call to `take()` substitutes a fresh random session id, so a single
    rotating-gateway entry can serve many parallel profiles with sticky-but-
    distinct IPs (e.g. flyproxy: `..._session-{sid}`).

`take()` is thread-safe, hands out one proxy per call without repeats, and
re-shuffles once the pool is drained.
"""

import os
import random
import string
import threading
from typing import List, Optional


_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "proxy.txt")


def _new_sid(length: int = 8) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choices(alphabet, k=length))


class ProxyPool:
    def __init__(self, path: str = _DEFAULT_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._all: List[str] = []
        self._available: List[str] = []
        self.reload()

    def reload(self) -> None:
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
            except Exception:
                raw = []
            valid: List[str] = []
            seen = set()
            for ln in raw:
                if ":" not in ln:
                    continue
                if ln in seen:
                    continue
                seen.add(ln)
                valid.append(ln)
            self._all = valid
            self._available = list(valid)
            random.shuffle(self._available)

    def take(self) -> str:
        """Pop one proxy off the pool. Re-shuffles when drained.
        If the chosen entry is a `{sid}` template, substitute a fresh random
        session id so each caller gets a distinct sticky IP from the gateway.
        Template entries stay in the pool forever (effectively infinite)."""
        with self._lock:
            if not self._available:
                self._available = list(self._all)
                random.shuffle(self._available)
            if not self._available:
                return ""

            # If any entry is a gateway template, we keep handing it out
            # (with a fresh sid each time) without depleting the pool.
            templates = [e for e in self._all if "{sid}" in e]
            if templates:
                tpl = random.choice(templates)
                return tpl.replace("{sid}", _new_sid())

            return self._available.pop()

    def size(self) -> int:
        return len(self._all)


_global_pool: Optional[ProxyPool] = None
_global_lock = threading.Lock()


def get_pool(path: str = _DEFAULT_PATH) -> ProxyPool:
    global _global_pool
    with _global_lock:
        if _global_pool is None or _global_pool.path != path:
            _global_pool = ProxyPool(path)
    return _global_pool
