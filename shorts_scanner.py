# -*- coding: utf-8 -*-

import time
from typing import Callable, Dict, List, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException

from shorts_csv_store import load_shorts, prepend_new_shorts

Logger = Callable[[str], None]
StopChecker = Callable[[], bool]

CHROMEDRIVER_PATH = None


def _create_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--log-level=3")
    if CHROMEDRIVER_PATH:
        service = Service(CHROMEDRIVER_PATH)
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    driver.set_script_timeout(180)
    driver.set_window_size(1280, 800)
    return driver


def _extract_video_id(href: str) -> str:
    if not href:
        return ""
    href_main = href.split("&")[0]
    if "/shorts/" in href_main:
        return href_main.split("/shorts/")[-1].strip("/")
    return ""


def _scrape_shorts(driver, channel_shorts_url: str, stop_check: StopChecker, max_scroll: int = 60) -> List[Dict[str, str]]:
    driver.get(channel_shorts_url)
    time.sleep(2)

    last_height = 0
    same_count = 0

    for _ in range(max_scroll):
        if stop_check():
            break
        driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight);")
        time.sleep(2)
        new_height = driver.execute_script("return document.documentElement.scrollHeight;")
        if new_height == last_height:
            same_count += 1
            if same_count >= 2:
                break
        else:
            same_count = 0
        last_height = new_height

    elems = driver.find_elements(By.XPATH, "//a[@href and contains(@href, '/shorts/')]")
    videos: List[Dict[str, str]] = []
    seen_ids = set()
    for el in elems:
        if stop_check():
            break
        href = el.get_attribute("href")
        vid = _extract_video_id(href)
        if not vid or vid in seen_ids:
            continue
        seen_ids.add(vid)
        title = (el.get_attribute("title") or el.text or "").strip()
        if not title:
            try:
                parent = el.find_element(By.XPATH, ".//ancestor::ytd-rich-grid-media[1]")
                title_el = parent.find_element(By.ID, "video-title")
                title = (title_el.get_attribute("title") or title_el.text or "").strip()
            except Exception:
                title = ""
        videos.append({"video_id": vid, "title": title, "url": href})
    return videos


def scan_shorts_for_email(
    email: str,
    channel_shorts_url: str,
    stop_check: StopChecker,
    logger: Logger,
) -> Tuple[int, int]:
    if not channel_shorts_url:
        return 0, 0
    driver = _create_driver()
    try:
        existing = load_shorts(email)
        existing_ids = {row.get("video_id") for row in existing if row.get("video_id")}
        videos = _scrape_shorts(driver, channel_shorts_url, stop_check)
        new_videos: List[Dict[str, str]] = []
        for v in videos:
            if stop_check():
                break
            vid = v.get("video_id")
            if vid in existing_ids:
                break
            new_videos.append(v)
        total, added = prepend_new_shorts(email, new_videos)
        if logger:
            logger(f"[{email}] SCAN OK: added {added}, total {total}")
        return total, added
    finally:
        try:
            driver.quit()
        except Exception:
            pass
