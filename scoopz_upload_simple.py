# -*- coding: utf-8 -*-

import os
import time
import threading
from typing import Callable, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException

from pywinauto import Application
from pywinauto.keyboard import send_keys

from config import SCOOPZ_URL

Logger = Callable[[str], None]

file_dialog_lock = threading.Lock()


def _attach_driver(driver_path: str, remote_debugging_address: str):
    options = webdriver.ChromeOptions()
    options.add_experimental_option("debuggerAddress", remote_debugging_address.strip())
    service = Service(driver_path)
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def _select_file_in_dialog(video_path: str, logger: Logger, timeout: int = 12) -> bool:
    video_path = os.path.abspath(video_path)
    safe_path = video_path.replace("{", "{{").replace("}", "}}")

    def _try_backend(backend: str) -> bool:
        dlg = None
        start = time.time()
        while time.time() - start < timeout:
            try:
                app = Application(backend=backend).connect(title_re="Open|M?", timeout=2)
                dlg = app.window(title_re="Open|M?")
                break
            except Exception:
                time.sleep(0.3)

        if dlg is None:
            return False

        try:
            dlg.set_focus()
            time.sleep(0.2)
            try:
                edit = dlg.child_window(auto_id="1148")
                edit.set_edit_text(video_path)
            except Exception:
                try:
                    edit = dlg.child_window(class_name="Edit")
                    edit.set_edit_text(video_path)
                except Exception:
                    send_keys("%n")
                    time.sleep(0.1)
                    send_keys(safe_path, with_spaces=True, pause=0.02)
            time.sleep(0.2)
            send_keys("{ENTER}")
            return True
        except Exception as e:
            if logger:
                logger(f"[UPLOAD] Dialog input error ({backend}): {e}")
            return False

    # Try UIA first, then win32. No blind typing to avoid typing into other apps.
    if _try_backend("uia"):
        return True
    if _try_backend("win32"):
        return True

    if logger:
        logger("[UPLOAD] Dialog focus failed, not typing to avoid wrong target")
    return False


def upload_select_only(
    driver_path: str,
    remote_debugging_address: str,
    video_path: str,
    logger: Logger,
) -> Tuple[bool, str]:
    video_path = os.path.abspath(video_path)
    if not os.path.exists(video_path):
        return False, f"File not found: {video_path}"
    if not driver_path or not remote_debugging_address:
        return False, "Missing driver_path / remote_debugging_address"

    driver = None
    try:
        driver = _attach_driver(driver_path, remote_debugging_address)
        wait = WebDriverWait(driver, 30)

        upload_url = SCOOPZ_URL.rstrip("/") + "/upload"
        driver.get(upload_url)
        time.sleep(1.0)

        with file_dialog_lock:
            try:
                select_btn = wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//div[normalize-space()='Select video']"))
                )
            except TimeoutException:
                return False, "Select video not found"

            try:
                try:
                    select_btn.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click();", select_btn)
            except Exception as e:
                return False, f"Click Select video error: {e}"

            time.sleep(0.8)
            ok = _select_file_in_dialog(video_path, logger)
            if not ok:
                return False, "Open dialog failed"

        return True, ""
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass


def upload_video_full(
    driver_path: str,
    remote_debugging_address: str,
    video_path: str,
    caption: str,
    logger: Logger,
) -> Tuple[bool, str]:
    video_path = os.path.abspath(video_path)
    if not os.path.exists(video_path):
        return False, f"File not found: {video_path}"
    if not driver_path or not remote_debugging_address:
        return False, "Missing driver_path / remote_debugging_address"

    driver = None
    try:
        driver = _attach_driver(driver_path, remote_debugging_address)
        wait = WebDriverWait(driver, 40)

        upload_url = SCOOPZ_URL.rstrip("/") + "/upload"
        driver.get(upload_url)
        time.sleep(1.0)

        with file_dialog_lock:
            try:
                select_btn = wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//div[normalize-space()='Select video']"))
                )
            except TimeoutException:
                return False, "Select video not found"

            try:
                try:
                    select_btn.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click();", select_btn)
            except Exception as e:
                return False, f"Click Select video error: {e}"

            time.sleep(0.8)
            ok = _select_file_in_dialog(video_path, logger)
            if not ok:
                return False, "Open dialog failed"

        try:
            wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, "//div[contains(@class,'font-bold') and normalize-space()='Caption']")
                )
            )
        except TimeoutException:
            return False, "Caption not found after selecting video"

        try:
            editor = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "div.tiptap.ProseMirror[contenteditable='true']"))
            )
            editor.click()
            time.sleep(0.2)
            editor.send_keys(caption or "")
        except Exception as e:
            return False, f"Caption input error: {e}"

        def _find_post_btn():
            candidates = [
                (By.XPATH, "//button[normalize-space()='Post']"),
                (By.XPATH, "//div[normalize-space()='Post']"),
                (By.XPATH, "//*[@role='button' and normalize-space()='Post']"),
            ]
            for how, sel in candidates:
                try:
                    els = driver.find_elements(how, sel)
                    for el in els:
                        if el.is_displayed():
                            return el
                except Exception:
                    continue
            return None

        post_btn = _find_post_btn()
        if post_btn is None:
            return False, "Post button not found"

        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", post_btn)
        except Exception:
            pass

        try:
            post_btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", post_btn)

        try:
            WebDriverWait(driver, 120).until(
                EC.visibility_of_element_located((By.XPATH, "//*[contains(., 'Successfully posted')]"))
            )
            return True, ""
        except TimeoutException:
            return False, "Post timeout"
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass
