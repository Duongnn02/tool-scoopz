# -*- coding: utf-8 -*-

import json
import os
from config import DATA_DIR
from typing import Dict


DEFAULT_SAVEF_CONFIG: Dict[str, str] = {
    "api_url": "https://savef.app/api/ajaxSearch",
    "referer": "https://savef.app/vi/fb-reels-downloader",
    "k_exp": "1770646038",
    "k_token": "fb84fc479b7db1eddbfb8fe9955e3f419a40e6ac0d8c8680d30fca7fd396919a",
    "lang": "vi",
    "web": "savef.app",
    "v": "v2",
    "w": "",
}


def get_savef_config_path() -> str:
    return os.path.join(DATA_DIR, "savef_api_config.json")


def load_savef_config() -> Dict[str, str]:
    cfg = dict(DEFAULT_SAVEF_CONFIG)
    path = get_savef_config_path()
    if not os.path.exists(path):
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            for k in cfg.keys():
                val = raw.get(k, cfg[k])
                if val is None:
                    continue
                cfg[k] = str(val)
    except Exception:
        pass
    return cfg
