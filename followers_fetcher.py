# -*- coding: utf-8 -*-

import time
import os
from typing import Callable, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

Logger = Callable[[str], None]


def _parse_count(text: str) -> int:
    val = (text or "").strip().lower().replace(",", "")
    if not val:
        return 0
    mult = 1
    if val.endswith("k"):
        mult = 1000
        val = val[:-1]
    elif val.endswith("m"):
        mult = 1000000
        val = val[:-1]
    elif val.endswith("b"):
        mult = 1000000000
        val = val[:-1]
    try:
        return int(float(val) * mult)
    except Exception:
        return 0


def _find_stat_count(driver, labels: list[str]) -> int | None:
    # Try to locate a stat label and read its sibling bold number.
    for label in labels:
        lbl = label.lower()
        try:
            label_el = driver.find_element(
                By.XPATH,
                "//span[translate(normalize-space(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')="
                f"'{lbl}']",
            )
            try:
                num_el = label_el.find_element(
                    By.XPATH, "preceding-sibling::span[contains(@class,'font-bold')][1]"
                )
            except Exception:
                num_el = label_el.find_element(
                    By.XPATH, "../span[contains(@class,'font-bold')][1]"
                )
            txt = (num_el.text or "").strip()
            return _parse_count(txt)
        except Exception:
            continue
    return None


def _safe_email(email: str) -> str:
    return (
        (email or "unknown")
        .strip()
        .replace("@", "_at_")
        .replace(".", "_")
        .replace(":", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )


def _save_profile_html(driver, email: str, logger: Logger) -> None:
    if not email:
        return
    try:
        base = os.path.join(os.path.dirname(__file__), "html_snapshots")
        os.makedirs(base, exist_ok=True)
        name = _safe_email(email)
        path = os.path.join(base, f"{name}.html")
        html = driver.page_source or ""
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as e:
        if logger:
            logger(f"[FOLLOW] Save HTML err: {e}")


def fetch_followers(
    driver_path: str,
    remote_debugging_address: str,
    logger: Logger,
    email: str = "",
) -> Tuple[int | None, str, int | None]:
    options = webdriver.ChromeOptions()
    options.add_experimental_option("debuggerAddress", remote_debugging_address.strip())
    service = Service(driver_path)
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, 20)

    try:
        # Try open menu and click Profile
        try:
            menu_btn = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "label[for='webapp-drawer-toggle']"))
            )
            driver.execute_script("arguments[0].click();", menu_btn)
            time.sleep(0.5)
        except Exception:
            pass

        try:
            prof_link = driver.find_elements(By.CSS_SELECTOR, "a[href*='/@']")
            if prof_link:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", prof_link[0])
                driver.execute_script("arguments[0].click();", prof_link[0])
                time.sleep(1.2)
        except Exception:
            pass

        # Save profile HTML only after profile stats are present
        try:
            wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, "//span[normalize-space()='Followers' or normalize-space()='Follower']")
                )
            )
            _save_profile_html(driver, email, logger)
        except Exception as e:
            if logger:
                logger(f"[FOLLOW] Save HTML skipped: {e}")

        try:
            foll_el = wait.until(
                EC.visibility_of_element_located(
                    (By.XPATH, "//div[.//span[normalize-space()='Followers' or normalize-space()='Follower']]/span[contains(@class,'font-bold')]")
                )
            )
            txt = (foll_el.text or "").strip()
            followers = _parse_count(txt)
        except Exception as e:
            if logger:
                logger(f"[FOLLOW] Read followers err: {e}")
            followers = None

        posts = None
        # Try read posts from label-based lookup
        try:
            posts = _find_stat_count(driver, ["posts", "post", "videos", "video"])
        except Exception as e:
            if logger:
                logger(f"[FOLLOW] Read posts err: {e}")

        try:
            profile_url = (driver.current_url or "").strip()
        except Exception:
            profile_url = ""

        return followers, profile_url, posts
    finally:
        try:
            driver.quit()
        except Exception:
            pass
