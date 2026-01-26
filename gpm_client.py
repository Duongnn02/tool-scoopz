# -*- coding: utf-8 -*-

import json
import re
import threading
import time
from typing import Any, Dict, Optional, Tuple, List

import requests

from config import CREATE_ENDPOINT, START_ENDPOINT, CLOSE_ENDPOINT, DELETE_ENDPOINT


def build_raw_proxy(proxy: str) -> Dict[str, Any]:
    """
    Build raw_proxy dict for GPM from common proxy formats.
    Supported:
      - host:port
      - host:port:user:pass
      - user:pass@host:port
      - http://user:pass@host:port
      - socks5://host:port
    """
    p = (proxy or "").strip()
    if not p:
        return {}

    scheme = "http"
    m = re.match(r"^(?P<scheme>https?|socks5)://(.+)$", p, re.I)
    if m:
        scheme = m.group("scheme").lower()
        p = p.split("://", 1)[1].strip()

    username = ""
    password = ""

    if "@" in p:
        cred, hostport = p.split("@", 1)
        p = hostport.strip()
        if ":" in cred:
            username, password = cred.split(":", 1)
        else:
            username = cred
    else:
        parts = p.split(":")
        if len(parts) >= 4:
            host = parts[0].strip()
            port = parts[1].strip()
            username = parts[2].strip()
            password = ":".join(parts[3:]).strip()
            raw = {
                "proxy_type": scheme,
                "proxy_host": host,
                "proxy_port": port,
            }
            if username:
                raw["proxy_user"] = username
            if password:
                raw["proxy_password"] = password
            return {k: v for k, v in raw.items() if v}

    host = ""
    port = ""
    if ":" in p:
        host, port = p.rsplit(":", 1)
    else:
        host = p

    host = host.strip()
    port = port.strip()

    raw = {
        "proxy_type": scheme,
        "proxy_host": host,
        "proxy_port": port,
    }
    if username:
        raw["proxy_user"] = username
    if password:
        raw["proxy_password"] = password

    return {k: v for k, v in raw.items() if v}


def create_profile(
    profile_name: str,
    proxy: str = "",
    startup_urls: str = "",
    logger=None,
) -> Tuple[bool, Dict[str, Any], str]:
    payload = {
        "profile_name": profile_name,
        "raw_proxy": proxy or "",
        "startup_urls": startup_urls or "",
        "note": "",
    }

    last_err = ""
    for attempt in range(3):
        try:
            print("CREATE payload:", payload)
            resp = requests.post(CREATE_ENDPOINT, json=payload, timeout=90)
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            if isinstance(data, dict) and data.get("success") is False:
                msg = str(data.get("message") or "create_profile failed")
                if logger:
                    try:
                        logger(f"[GPM] create_profile failed: {msg}")
                    except Exception:
                        pass
                return False, data, msg
            return True, data, ""
        except Exception as e:
            last_err = str(e)
            time.sleep(1 + attempt)
    if logger and last_err:
        try:
            logger(f"[GPM] create_profile error: {last_err}")
        except Exception:
            pass
    return False, {}, last_err


def start_profile(
    profile_id: str,
    win_pos: Optional[str] = None,
    win_size: Optional[str] = None,
    win_scale: Optional[float] = None,
    logger=None,
) -> Tuple[bool, Dict[str, Any], str]:
    _ = win_scale
    url = f"{START_ENDPOINT}/{profile_id}"
    payload = {"automation": True, "openDevtools": False, "headless": False}
    params = {}
    if win_pos:
        params["win_pos"] = win_pos
    if win_size:
        params["win_size"] = win_size
    last_err = ""
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, params=params or None, timeout=90)
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            if isinstance(data, dict) and data.get("success") is False:
                msg = str(data.get("message") or "start_profile failed")
                if logger:
                    try:
                        logger(f"[GPM] start_profile failed: {msg}")
                    except Exception:
                        pass
                return False, data, msg
            return True, data, ""
        except Exception as e:
            last_err = str(e)
            time.sleep(1 + attempt)
    if logger and last_err:
        try:
            logger(f"[GPM] start_profile error: {last_err}")
        except Exception:
            pass
    return False, {}, last_err


def close_profile(profile_id: str, timeout_s: int = 10, logger=None) -> Tuple[bool, str]:
    url = f"{CLOSE_ENDPOINT}/{profile_id}"
    try:
        resp = requests.post(url, timeout=timeout_s)
        resp.raise_for_status()
        return True, ""
    except Exception as e:
        msg = str(e)
        if logger:
            try:
                logger(f"[GPM] close_profile error: {msg}")
            except Exception:
                pass
        return False, msg


def delete_profile(profile_id: str, timeout_s: int = 10, logger=None) -> Tuple[bool, str]:
    url = f"{DELETE_ENDPOINT}/{profile_id}"
    try:
        resp = requests.get(url, timeout=timeout_s)
        resp.raise_for_status()
        return True, ""
    except Exception as e:
        msg = str(e)
        if logger:
            try:
                logger(f"[GPM] delete_profile error: {msg}")
            except Exception:
                pass
        return False, msg


def extract_driver_info(data: Dict[str, Any], logger=None) -> Tuple[Optional[str], Optional[str]]:
    if not isinstance(data, dict):
        if logger:
            try:
                logger("[GPM] extract_driver_info: invalid data")
            except Exception:
                pass
        return None, None

    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    driver_path = None
    remote = None

    for k in ("driver_path", "webdriver", "driver", "chromedriver", "selenium_driver_path"):
        v = payload.get(k) if isinstance(payload, dict) else None
        if isinstance(v, str) and v.strip():
            driver_path = v.strip()
            break

    for k in ("remote_debugging_address", "remoteDebuggingAddress", "debuggerAddress", "ws", "selenium"):
        v = payload.get(k) if isinstance(payload, dict) else None
        if isinstance(v, str) and ":" in v:
            remote = v.strip()
            break

    return driver_path, remote


if __name__ == "__main__":
    test_proxy = "154.6.83.85:6556:uvsmvbyr:6d9c706mwyge"
    num_profiles = 5
    created_ids: List[str] = []
    start_results = []
    lock = threading.Lock()

    def _worker(idx: int):
        name = f"test_profile_{idx+1}"
        ok_c, data_c, msg_c = create_profile(name, test_proxy)
        print(f"[{name}] CREATE OK:", ok_c, "MSG:", msg_c)
        if not ok_c:
            return
        pid = None
        if isinstance(data_c, dict):
            pid = (data_c.get("data") or {}).get("id") or data_c.get("id") or data_c.get("profile_id")
        if not pid:
            print(f"[{name}] Missing profile_id")
            return
        with lock:
            created_ids.append(pid)

        ok_s, data_s, msg_s = start_profile(pid)
        print(f"[{name}] START OK:", ok_s, "MSG:", msg_s)
        if ok_s:
            driver_path, remote = extract_driver_info(data_s)
            with lock:
                start_results.append((pid, driver_path, remote))

    threads = []
    for i in range(num_profiles):
        t = threading.Thread(target=_worker, args=(i,), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.3)

    for t in threads:
        t.join()

    print("STARTED:", len(start_results))
    time.sleep(5)

    for pid in list(created_ids):
        ok, msg = close_profile(pid)
        print(f"[CLOSE] {pid} OK={ok} MSG={msg}")
