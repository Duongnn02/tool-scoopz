# -*- coding: utf-8 -*-
import json
import os
import sqlite3
import threading
import time
import secrets
import string
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Callable, Optional


class _Store:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS keys (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        key TEXT UNIQUE NOT NULL,
                        status TEXT NOT NULL DEFAULT 'ACTIVE',
                        hwid TEXT DEFAULT '',
                        note TEXT DEFAULT '',
                        created_at REAL,
                        activated_at REAL,
                        last_check_at REAL
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def _gen_key(self) -> str:
        alphabet = string.ascii_uppercase + string.digits
        parts = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4)]
        return "SCPZ-" + "-".join(parts)

    def create_key(self, note: str = "") -> str:
        key = self._gen_key()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO keys (key, status, hwid, note, created_at) VALUES (?, 'ACTIVE', '', ?, ?)",
                    (key, note or "", time.time()),
                )
                conn.commit()
                return key
            finally:
                conn.close()

    def list_keys(self) -> list:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT key, status, hwid, note, created_at, activated_at, last_check_at FROM keys ORDER BY id DESC"
                )
                rows = cur.fetchall()
                out = []
                for r in rows:
                    out.append(
                        {
                            "key": r[0],
                            "status": r[1],
                            "hwid": r[2],
                            "note": r[3],
                            "created_at": r[4],
                            "activated_at": r[5],
                            "last_check_at": r[6],
                        }
                    )
                return out
            finally:
                conn.close()

    def revoke_key(self, key: str) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("UPDATE keys SET status='REVOKED' WHERE key = ?", (key,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def verify_key(self, key: str, hwid: str) -> tuple[bool, str]:
        if not hwid:
            return False, "MISSING_HWID"
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT status, hwid, activated_at FROM keys WHERE key = ?",
                    (key,),
                )
                row = cur.fetchone()
                if not row:
                    return False, "NOT_FOUND"
                status, stored_hwid, activated_at = row
                if status != "ACTIVE":
                    return False, "REVOKED"
                stored_hwid = stored_hwid or ""
                if stored_hwid and hwid and stored_hwid != hwid:
                    return False, "HWID_MISMATCH"
                now = time.time()
                if not stored_hwid and hwid:
                    conn.execute(
                        "UPDATE keys SET hwid=?, activated_at=?, last_check_at=? WHERE key=?",
                        (hwid, now, now, key),
                    )
                else:
                    if not activated_at:
                        conn.execute(
                            "UPDATE keys SET activated_at=?, last_check_at=? WHERE key=?",
                            (now, now, key),
                        )
                    else:
                        conn.execute(
                            "UPDATE keys SET last_check_at=? WHERE key=?",
                            (now, key),
                        )
                conn.commit()
                return True, "ACTIVE"
            finally:
                conn.close()


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def _json_response(handler: BaseHTTPRequestHandler, code: int, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def start_license_server(
    host: str,
    port: int,
    db_path: str,
    admin_token: str,
    log_func: Optional[Callable[[str], None]] = None,
) -> _ThreadingHTTPServer:
    store = _Store(db_path)

    class Handler(BaseHTTPRequestHandler):
        def _log(self, msg: str) -> None:
            if log_func:
                try:
                    log_func(msg)
                except Exception:
                    pass

        def _read_json(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length > 0 else b""
                if not body:
                    return {}
                return json.loads(body.decode("utf-8"))
            except Exception:
                return {}

        def _is_admin(self) -> bool:
            token = self.headers.get("X-Admin-Token", "")
            return bool(admin_token) and token == admin_token

        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                _json_response(self, 200, {"ok": True})
                return
            if self.path == "/keys":
                if not self._is_admin():
                    _json_response(self, 403, {"ok": False, "reason": "FORBIDDEN"})
                    return
                _json_response(self, 200, {"ok": True, "keys": store.list_keys()})
                return
            _json_response(self, 404, {"ok": False, "reason": "NOT_FOUND"})

        def do_POST(self):  # noqa: N802
            if self.path == "/verify":
                payload = self._read_json()
                key = (payload.get("key") or "").strip()
                hwid = (payload.get("hwid") or "").strip()
                if not key:
                    _json_response(self, 400, {"ok": False, "reason": "MISSING_KEY"})
                    return
                ok, status = store.verify_key(key, hwid)
                _json_response(self, 200, {"ok": ok, "status": status})
                return
            if self.path == "/keys/create":
                if not self._is_admin():
                    _json_response(self, 403, {"ok": False, "reason": "FORBIDDEN"})
                    return
                payload = self._read_json()
                note = (payload.get("note") or "").strip()
                key = store.create_key(note=note)
                _json_response(self, 200, {"ok": True, "key": key})
                return
            if self.path == "/keys/revoke":
                if not self._is_admin():
                    _json_response(self, 403, {"ok": False, "reason": "FORBIDDEN"})
                    return
                payload = self._read_json()
                key = (payload.get("key") or "").strip()
                if not key:
                    _json_response(self, 400, {"ok": False, "reason": "MISSING_KEY"})
                    return
                ok = store.revoke_key(key)
                _json_response(self, 200, {"ok": ok})
                return
            _json_response(self, 404, {"ok": False, "reason": "NOT_FOUND"})

        def log_message(self, _format: str, *args) -> None:
            self._log(f"[LICENSE] {self.address_string()} - {args}")

    server = _ThreadingHTTPServer((host, int(port)), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server
