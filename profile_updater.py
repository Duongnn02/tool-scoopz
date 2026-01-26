# -*- coding: utf-8 -*-

import time
import os
import tempfile
import urllib.request
from typing import Callable, Tuple, Optional
import re
import tkinter as tk
import logging

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException

try:
    from pywinauto.application import Application
    from pywinauto.keyboard import send_keys
    PYWINAUTO_AVAILABLE = True
except ImportError as e:
    Application = None
    send_keys = None
    PYWINAUTO_AVAILABLE = False

Logger = Callable[[str], None]


def _log(logger: Logger | None, msg: str) -> None:
    try:
        if logger:
            logger(msg)
    except Exception:
        pass


def _set_value_js(driver, element, value: str) -> None:
    driver.execute_script(
        "arguments[0].focus(); arguments[0].value = arguments[1];"
        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
        "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
        element,
        value,
    )

def _set_clipboard(text: str) -> bool:
    try:
        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception:
        return False

def _select_file_in_dialog(file_path: str, logger: Logger | None = None, timeout: int = 8) -> bool:
    if Application is None or send_keys is None:
        return False
    file_path = os.path.abspath(file_path)
    safe_path = file_path.replace("{", "{{").replace("}", "}}")
    title_re = "Open|M\\u1edf|Ch\\u1ecdn t\\u1ec7p|Ch\\u1ecdn t\\u1eadp tin|File Upload|Upload"
    start = time.time()
    while time.time() - start < timeout:
        try:
            app = Application(backend="uia").connect(title_re=title_re, timeout=0.6)
            dlg = app.window(title_re=title_re)
            try:
                dlg.set_focus()
            except Exception:
                pass
            try:
                send_keys("%n")
                edit = dlg.child_window(auto_id="1148")
                if _set_clipboard(file_path):
                    send_keys("^v")
                else:
                    edit.set_edit_text(file_path)
            except Exception:
                try:
                    send_keys("%n")
                    edit = dlg.child_window(class_name="Edit")
                    if _set_clipboard(file_path):
                        send_keys("^v")
                    else:
                        edit.set_edit_text(file_path)
                except Exception:
                    send_keys("%n")
                    time.sleep(0.05)
                    if _set_clipboard(safe_path):
                        send_keys("^v")
                    else:
                        send_keys(safe_path, with_spaces=True, pause=0.0)
            try:
                btn = dlg.child_window(title_re="Open|M\\u1edf", class_name="Button")
                if btn.exists():
                    btn.click()
                    return True
            except Exception:
                pass
            send_keys("{ENTER}")
            return True
        except Exception:
            time.sleep(0.12)
    _log(logger, "[PROFILE] Open dialog not found")
    return False


def _sanitize_username(value: str) -> str:
    val = (value or "").strip().lower()
    val = re.sub(r"[^a-z0-9_]", "", val)
    if len(val) < 3:
        val = (val + "user")[:3]
    return val[:20]


def _sanitize_nickname(value: str) -> str:
    val = (value or "").strip()
    if len(val) > 20:
        val = val[:20].rstrip()
    return val


def _open_profile_page(driver, wait, logger: Logger | None = None) -> None:
    for attempt in range(3):
        try:
            menu_btn = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "label[for='webapp-drawer-toggle']"))
            )
            driver.execute_script("arguments[0].click();", menu_btn)
            _log(logger, f"[PROFILE] Menu clicked (try {attempt+1})")
            time.sleep(0.4)
        except Exception as e:
            _log(logger, f"[PROFILE] Menu open err (try {attempt+1}): {e}")
        try:
            prof_link = driver.find_elements(By.CSS_SELECTOR, "a[href*='/@']")
            if prof_link:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", prof_link[0])
                driver.execute_script("arguments[0].click();", prof_link[0])
                _log(logger, "[PROFILE] Profile clicked")
                time.sleep(1.0)
                return
        except Exception as e:
            _log(logger, f"[PROFILE] Profile link err (try {attempt+1}): {e}")
        time.sleep(0.4)


def _pick_thumbnail(info: dict) -> str:
    thumb = (info.get("thumbnail") or "").strip()
    thumbs = info.get("thumbnails") or []
    if thumbs:
        try:
            thumbs = sorted(thumbs, key=lambda t: t.get("width", 0) * t.get("height", 0))
            thumb = thumbs[-1].get("url") or thumb
        except Exception:
            pass
    return thumb


def _download_image(url: str, logger: Logger | None = None) -> str:
    if not url:
        return ""
    try:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile_images")
        os.makedirs(out_dir, exist_ok=True)
        fd, out_path = tempfile.mkstemp(prefix="yt_avatar_", suffix=".jpg", dir=out_dir)
        os.close(fd)
        urllib.request.urlretrieve(url, out_path)
        return out_path
    except Exception as e:
        _log(logger, f"[PROFILE] Download avatar err: {e}")
        return ""


def _get_channel_info(yt_url: str, logger: Logger | None = None) -> Tuple[str, str, str]:
    try:
        from yt_dlp import YoutubeDL  # type: ignore
    except Exception as e:
        _log(logger, f"[PROFILE] yt-dlp missing: {e}")
        return "", "", ""

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": False,
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(yt_url, download=False)
    except Exception as e:
        _log(logger, f"[PROFILE] yt-dlp error: {e}")
        return "", "", ""

    name = (info.get("channel") or info.get("uploader") or info.get("title") or "").strip()
    bio = (
        info.get("channel_description")
        or info.get("description")
        or info.get("uploader_description")
        or ""
    ).strip()
    thumb_url = _pick_thumbnail(info)
    return name, bio, thumb_url


def fetch_youtube_profile_assets(yt_url: str, logger: Logger | None = None) -> Tuple[str, str, str]:
    name, bio, thumb_url = _get_channel_info(yt_url, logger)
    avatar_path = _download_image(thumb_url, logger)
    return name, bio, avatar_path


def fetch_youtube_profile_assets_browser(
    driver_path: str,
    remote_debugging_address: str,
    yt_url: str,
    logger: Logger | None = None,
) -> Tuple[str, str, str]:
    options = webdriver.ChromeOptions()
    options.add_experimental_option("debuggerAddress", remote_debugging_address.strip())
    service = Service(driver_path)
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, 25)

    try:
        driver.get(yt_url)
        try:
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        except Exception:
            pass
        time.sleep(0.6)

        name = ""
        username = ""
        avatar_url = ""

        try:
            name_el = wait.until(
                EC.visibility_of_element_located(
                    (
                        By.XPATH,
                        "//yt-dynamic-text-view-model//h1//span | //h1[contains(@class,'dynamicTextViewModelH1')]//span",
                    )
                )
            )
            name = (name_el.text or "").strip()
        except Exception:
            pass

        try:
            handle_el = driver.find_element(
                By.XPATH,
                "//yt-content-metadata-view-model//span[starts-with(normalize-space(.), '@')]",
            )
            username = (handle_el.text or "").strip()
        except Exception:
            try:
                handle_el = driver.find_element(
                    By.XPATH,
                    "//span[starts-with(normalize-space(.), '@')]",
                )
                username = (handle_el.text or "").strip()
            except Exception:
                pass

        try:
            avatar_el = driver.find_element(
                By.XPATH,
                "//yt-decorated-avatar-view-model//img[contains(@class,'yt-spec-avatar-shape__image')]",
            )
            avatar_url = (avatar_el.get_attribute("src") or "").strip()
        except Exception:
            try:
                avatar_el = driver.find_element(
                    By.XPATH,
                    "//img[contains(@class,'yt-spec-avatar-shape__image')]",
                )
                avatar_url = (avatar_el.get_attribute("src") or "").strip()
            except Exception:
                pass

        avatar_path = _download_image(avatar_url, logger) if avatar_url else ""
        return name, username, avatar_path
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def fetch_youtube_profile_assets_local(
    yt_url: str,
    logger: Logger | None = None,
) -> Tuple[str, str, str]:
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,720")
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 25)

    try:
        driver.get(yt_url)
        try:
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        except Exception:
            pass
        time.sleep(0.6)

        name = ""
        username = ""
        avatar_url = ""

        try:
            name_el = wait.until(
                EC.visibility_of_element_located(
                    (
                        By.XPATH,
                        "//yt-dynamic-text-view-model//h1//span | //h1[contains(@class,'dynamicTextViewModelH1')]//span",
                    )
                )
            )
            name = (name_el.text or "").strip()
        except Exception:
            pass

        try:
            handle_el = driver.find_element(
                By.XPATH,
                "//yt-content-metadata-view-model//span[starts-with(normalize-space(.), '@')]",
            )
            username = (handle_el.text or "").strip()
        except Exception:
            try:
                handle_el = driver.find_element(
                    By.XPATH,
                    "//span[starts-with(normalize-space(.), '@')]",
                )
                username = (handle_el.text or "").strip()
            except Exception:
                pass

        try:
            avatar_el = driver.find_element(
                By.XPATH,
                "//yt-decorated-avatar-view-model//img[contains(@class,'yt-spec-avatar-shape__image')]",
            )
            avatar_url = (avatar_el.get_attribute("src") or "").strip()
        except Exception:
            try:
                avatar_el = driver.find_element(
                    By.XPATH,
                    "//img[contains(@class,'yt-spec-avatar-shape__image')]",
                )
                avatar_url = (avatar_el.get_attribute("src") or "").strip()
            except Exception:
                pass

        avatar_path = _download_image(avatar_url, logger) if avatar_url else ""
        return name, username, avatar_path
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def previsit_youtube(
    driver_path: str,
    remote_debugging_address: str,
    yt_url: str,
    logger: Logger | None = None,
) -> None:
    if not yt_url:
        return
    options = webdriver.ChromeOptions()
    options.add_experimental_option("debuggerAddress", remote_debugging_address.strip())
    service = Service(driver_path)
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, 20)
    try:
        driver.get(yt_url)
        try:
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        except Exception:
            pass
        time.sleep(0.6)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def update_profile_from_assets(
    driver_path: str,
    remote_debugging_address: str,
    name: str,
    username: str,
    avatar_path: str,
    logger: Logger | None = None,
) -> Tuple[bool, str]:
    if not name and not username and not avatar_path:
        return False, "Khong co du lieu cap nhat profile"

    options = webdriver.ChromeOptions()
    options.add_experimental_option("debuggerAddress", remote_debugging_address.strip())
    service = Service(driver_path)
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, 20)

    try:
        # After login, re-open menu to access Profile link
        _open_profile_page(driver, wait, logger)

        try:
            edit_btn = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Edit Profile']"))
            )
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", edit_btn)
            driver.execute_script("arguments[0].click();", edit_btn)
            _log(logger, "[PROFILE] Edit Profile clicked")
            time.sleep(0.6)
        except Exception as e:
            return False, f"Khong tim thay Edit Profile: {e}"

        if avatar_path:
            try:
                time.sleep(0.5)
                _log(logger, "[PROFILE] Uploading avatar...")
                pic_btns = driver.find_elements(
                    By.XPATH,
                    "//button[.//span[normalize-space()='Change picture']] | //button[.//input[@type='file' and @accept]]",
                )
                if pic_btns:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", pic_btns[0])
                    driver.execute_script("arguments[0].click();", pic_btns[0])
                    _log(logger, "[PROFILE] Change picture clicked")
                    if not _select_file_in_dialog(avatar_path, logger):
                        try:
                            file_inputs = driver.find_elements(By.XPATH, "//input[@type='file' and @accept]")
                            if file_inputs:
                                file_inputs[0].send_keys(avatar_path)
                        except Exception:
                            pass
                    time.sleep(0.8)
                    _log(logger, "[PROFILE] Avatar uploaded")
            except Exception as e:
                _log(logger, f"[PROFILE] Upload avatar err: {e}")

        return True, ""
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def update_profile_from_youtube(
    driver_path: str,
    remote_debugging_address: str,
    youtube_url: str,
    logger: Logger | None = None,
) -> Tuple[bool, str]:
    name, bio, avatar_path = fetch_youtube_profile_assets(youtube_url, logger)
    return update_profile_from_assets(driver_path, remote_debugging_address, name, bio, avatar_path, logger)
