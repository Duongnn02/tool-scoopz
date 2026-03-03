#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from savef_api_config import load_savef_config


DEFAULT_URL = "https://www.facebook.com/reel/1199809415261599"
OUTPUT_DIR = Path("video/savef_test")


def extract_720_link(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")

    # Target exact UI shown by user.
    exact = soup.select_one('a.download-link-fb[title="Download 720p (HD)"][href]')
    if exact:
        href = (exact.get("href") or "").strip()
        if href:
            return href

    # Fallback: any download-link-fb containing 720 in title/text.
    for a in soup.select("a.download-link-fb[href]"):
        title = (a.get("title") or "").strip().lower()
        text = (a.get_text(" ", strip=True) or "").lower()
        if "720" in title or "720" in text:
            href = (a.get("href") or "").strip()
            if href:
                return href

    # Fallback by row quality 720p (HD) then anchor in same row.
    for row in soup.select("#fbdownloader .tab__content table tbody tr"):
        q = (row.select_one(".video-quality").get_text(" ", strip=True) if row.select_one(".video-quality") else "").lower()
        if "720" in q:
            a = row.select_one("a.download-link-fb[href]")
            if a:
                href = (a.get("href") or "").strip()
                if href:
                    return href
    return ""


def main() -> int:
    cfg = load_savef_config()
    payload = {
        "p": "home",
        "k_exp": cfg["k_exp"],
        "k_token": cfg["k_token"],
        "q": DEFAULT_URL,
        "lang": cfg["lang"],
        "web": cfg["web"],
        "v": cfg["v"],
        "w": cfg["w"],
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://savef.app",
        "Referer": cfg["referer"],
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
    }

    try:
        resp = requests.post(cfg["api_url"], data=payload, headers=headers, timeout=60)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERR] API request failed: {e}")
        return 1

    try:
        data = resp.json()
    except json.JSONDecodeError:
        print("[ERR] API did not return JSON")
        print(resp.text[:500])
        return 1

    status = str(data.get("status") or "").lower()
    if status != "ok":
        print("[ERR] API status not ok")
        print(json.dumps(data, ensure_ascii=False)[:1000])
        return 1

    html = data.get("data") or ""
    link_720 = extract_720_link(html)
    if not link_720:
        print("[ERR] No 720p download link found")
        short = re.sub(r"\s+", " ", html)[:800]
        print(short)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUTPUT_DIR / f"savef_720_{int(time.time())}.mp4"
    dl_headers = {
        "User-Agent": headers["User-Agent"],
        "Referer": "https://savef.app/",
    }
    try:
        with requests.get(link_720, headers=dl_headers, stream=True, timeout=(20, 300)) as dl:
            dl.raise_for_status()
            with out_file.open("wb") as f:
                for chunk in dl.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
    except Exception as e:
        print(f"[ERR] Download failed: {e}")
        print(link_720)
        return 1

    if not out_file.exists() or out_file.stat().st_size <= 0:
        print("[ERR] Downloaded file is empty")
        print(link_720)
        return 1

    print(f"[OK] Downloaded: {out_file.resolve()}")
    print(f"[OK] Size: {out_file.stat().st_size} bytes")
    print(f"[OK] Source: {link_720}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
