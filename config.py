# -*- coding: utf-8 -*-

import os
import sys

API_BASE = "http://127.0.0.1:19995/api/v3"
CREATE_ENDPOINT = f"{API_BASE}/profiles/create"
START_ENDPOINT = f"{API_BASE}/profiles/start"
CLOSE_ENDPOINT = f"{API_BASE}/profiles/close"
DELETE_ENDPOINT = f"{API_BASE}/profiles/delete"
SCOOPZ_URL = "https://thescoopz.com/"
SCOOPZ_UPLOAD_URL = "https://thescoopz.com/upload"
UPDATE_ENDPOINT = f"{API_BASE}/profiles"
COOKIES_FILE = "cookies.txt"
COOKIES_FILE_FALLBACK = "cookies_alt.txt"

# App data directory (per-user, with fallback if APPDATA is blocked)
def _pick_data_dir() -> str:
    appdata = os.getenv("APPDATA")
    if appdata:
        path = os.path.join(appdata, "ScoopzToolData")
        try:
            os.makedirs(path, exist_ok=True)
            test_file = os.path.join(path, ".__write_test__")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(test_file)
            return path
        except Exception:
            pass
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(__file__)
    path = os.path.join(base, "ScoopzToolData")
    os.makedirs(path, exist_ok=True)
    return path

DATA_DIR = _pick_data_dir()

# License server (local machine as server)
LICENSE_SERVER_ENABLED = True
LICENSE_SERVER_HOST = "0.0.0.0"
LICENSE_SERVER_PORT = 7860
LICENSE_SERVER_URL = "http://127.0.0.1:7860"
LICENSE_ADMIN_TOKEN = "CHANGE_ME_ADMIN_TOKEN"
