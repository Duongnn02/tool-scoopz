# -*- coding: utf-8 -*-

"""
Native-app view-tracking client for Scoopz.

Reverse-engineered from a live iOS app traffic capture (mitmproxy):
    POST https://api.scoopzapp.com/Website/proxy/real-time-log?<query>
    Content-Type: application/x-www-form-urlencoded
    Headers:
        x-user-id: <scoopz_user_id>
        cookie: JSESSIONID=<session>
        user-agent: Scoopz/5 CFNetwork/3860.300.31 Darwin/25.2.0
    Body: log=<URL-encoded JSON {"subType":"videoEnd","docid":"...",...}>

Each successful POST = one "view" recorded server-side. The dashboard call
to https://thescoopz.com/dashboard returns `nativeView` count which is the
target metric — this endpoint feeds it.
"""

import json
import random
import re
import string
import time
import urllib.parse
from typing import Optional

import requests


API_BASE = "https://api.scoopzapp.com"
NATIVE_UA = "Scoopz/5 CFNetwork/3860.300.31 Darwin/25.2.0"

# Captured experiment IDs (these change but the server seems to accept anything)
DEFAULT_EXPS = [
    "scoopz_feed_recall_26h1-v7",
    "bloom_video_backend_2602-v3",
    "bloom_video_user_2604-v4",
    "scoopz_feed_ranking_26h1-v1",
    "bloom_video_server_26q2-v2",
]


def extract_userid_from_profile_url(profile_url: str) -> str:
    """Scoopz profile URLs always end with `-<numeric_userid>`. The web JWT's
    `sub` claim was confirmed to match that trailing digit run for every
    account we tested, so we skip web login entirely and pull it from here."""
    if not profile_url:
        return ""
    m = re.search(r"-(\d{6,})/?$", profile_url.strip())
    return m.group(1) if m else ""


def extract_doc_id_from_video_url(video_url: str, proxy: Optional[str] = None,
                                   timeout: float = 30.0) -> str:
    """Fetch the SSR HTML for /v/<id> and pull the `pageKey` (= internal
    docId). Returns "" if the page is gone / the marker can't be found."""
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Safari/604.1",
        "Accept": "text/html",
    }
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        r = requests.get(video_url, proxies=proxies, headers=headers, timeout=timeout)
    except Exception:
        return ""
    if r.status_code != 200:
        return ""
    text = r.text
    # Two reliable extraction patterns from SSR HTML:
    m = re.search(r'\\"pageKey\\":\\"([0-9A-Za-z]{6,})\\"', text)
    if m:
        return m.group(1)
    m = re.search(r"docid=([0-9A-Za-z]{6,})", text)
    if m:
        return m.group(1)
    return ""


def _new_uuid() -> str:
    """Mimic an iOS-style upper-case UUID."""
    parts = [
        "".join(random.choices(string.hexdigits.upper()[:16], k=8)),
        "".join(random.choices(string.hexdigits.upper()[:16], k=4)),
        "".join(random.choices(string.hexdigits.upper()[:16], k=4)),
        "".join(random.choices(string.hexdigits.upper()[:16], k=4)),
        "".join(random.choices(string.hexdigits.upper()[:16], k=12)),
    ]
    return "-".join(parts)


class ScoopzNativeClient:
    """One client = one synthetic iOS device + Scoopz user session."""

    def __init__(
        self,
        userid: str,
        proxy: Optional[str] = None,
        device_id: Optional[str] = None,
        ios_id: Optional[str] = None,
    ):
        self.userid = str(userid)
        self.device_id = device_id or _new_uuid()
        self.ios_id = ios_id or _new_uuid()
        self.session_id = int(time.time() * 1000)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": NATIVE_UA,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "Screen-Width": "1206",
            "Screen-Height": "2622",
            "Sp-Video-Types": "h.264,h.265,av1",
            "Priority": "u=3, i",
            "x-user-id": self.userid,
        })
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}

    # --- Common query params (all calls include these) -----------------
    def _common_params(self) -> dict:
        return {
            "appid": "bloom",
            "cv": "4.2.8.5",
            "av": "250313",
            "version": "020086",
            "platform": "0",
            "deviceID": self.device_id,
            "device_id_ios": self.ios_id,
            "distribution": "com.apple.appstore",
            "languages": "en",
            "countries": "US",
            "net": "wifi",
        }

    # --- Bootstrap a JSESSIONID by registering the synthetic install ---
    def init_session(self) -> bool:
        """Hit upload-install + upload-device so the server returns
        a JSESSIONID cookie tied to this synthetic device."""
        install_id = _new_uuid() + "-13743-" + "".join(random.choices(string.hexdigits.upper()[:16], k=16))
        body = {
            "install_app_version": "1",
            "deferred_link": "",
            "install_id": install_id,
            "appid": "bloom",
            "device_id_ios": self.device_id,
            "ad_id": self.ios_id,
            "deviceID": self.device_id,
            "first_open_source": "deeplink",
            "adjust_data": {
                "network": "Organic", "trackerToken": "19h4jffg",
                "trackerName": "Organic",
                "jsonResponse": {
                    "engagement_time": "0001-01-01T00:00:00Z",
                    "tracker_token": "19h4jffg", "tracker_name": "Organic",
                    "is_reattributed": False,
                    "first_session_time": "2025-11-02T03:39:25Z",
                    "installed_at": "2025-11-02T03:39:25Z",
                    "network": "Organic",
                },
            },
        }
        url = f"{API_BASE}/Website/userprofile/upload-install"
        try:
            r = self.session.put(url, params=self._common_params(), json=body, timeout=20)
            return r.status_code == 200
        except Exception:
            return False

    # --- Send a videoEnd event (= 1 view) for a specific docId ----------
    def send_video_end(
        self,
        docid: str,
        duration: int = 15,
        progress: float = 0.95,
        time_elapsed: int = 14,
        source: str = "test",
    ) -> dict:
        meta = f"{self.userid}_bloom-foryou_{int(time.time()*1000)}_{random.randint(100, 9999)}"
        log_payload = {
            "docid": docid,
            "source": source,
            "subType": "videoEnd",
            "play_style": "immersive_feed",
            "isLoadSuccess": True,
            "timeElapsed": int(time_elapsed),
            "userid": self.userid,
            "countries": "US",
            "exps": DEFAULT_EXPS,
            "meta": meta,
            "progress": float(progress),
            "languages": "en",
            "network": "wifi",
            "nb_session_id": self.session_id,
            "videoLoadDuration": random.randint(8, 20),
            "reason": "scroll",
            "v_timeElapsedFloat": float(time_elapsed),
            "duration": int(duration),
        }
        body = "log=" + urllib.parse.quote(json.dumps(log_payload, separators=(",", ":")))
        url = f"{API_BASE}/Website/proxy/real-time-log"
        try:
            r = self.session.post(url, params=self._common_params(), data=body, timeout=20)
            return {
                "ok": r.status_code == 200 and '"code":0' in r.text,
                "status": r.status_code,
                "body": r.text[:200],
                "meta": meta,
            }
        except Exception as e:
            return {"ok": False, "status": "ERR", "body": str(e)[:200], "meta": meta}

    # --- Bulk-report a list of docIds as "checkedView" -----------------
    def send_checked_view(self, docids: list, show_time_ms: int = 9000) -> dict:
        """Some flows fire a `changeChannel`-shaped log with a `checkedView`
        list — bulk view registration. Backup approach if videoEnd alone
        isn't enough."""
        meta = f"{self.userid}_bloom-foryou_{int(time.time()*1000)}_{random.randint(100, 9999)}"
        log_payload = {
            "subType": "changeChannel",
            "actionSrc": "homeTab",
            "userid": self.userid,
            "languages": "en",
            "countries": "US",
            "nb_session_id": self.session_id,
            "exps": DEFAULT_EXPS,
            "srcChannelId": "",
            "srcChannelName": "",
            "dayin": random.randint(100, 600),
            "checkedView": [{"meta": meta, "docIds": list(docids)}],
            "showTime": [{d: show_time_ms for d in docids}],
            "thumbUpCounts": {d: 0 for d in docids},
            "thumbDownCounts": {d: 0 for d in docids},
            "commentCounts": {d: 0 for d in docids},
        }
        body = "log=" + urllib.parse.quote(json.dumps(log_payload, separators=(",", ":")))
        url = f"{API_BASE}/Website/proxy/real-time-log"
        try:
            r = self.session.post(url, params=self._common_params(), data=body, timeout=20)
            return {
                "ok": r.status_code == 200 and '"code":0' in r.text,
                "status": r.status_code,
                "body": r.text[:200],
            }
        except Exception as e:
            return {"ok": False, "status": "ERR", "body": str(e)[:200]}
