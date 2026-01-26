# -*- coding: utf-8 -*-

import time
import os
import threading
import re
from typing import Tuple

from config import SCOOPZ_UPLOAD_URL, SCOOPZ_URL

from selenium import webdriver as _webdriver
from selenium.webdriver.chrome.service import Service as _ChromeService
from selenium.webdriver.common.by import By as _By
from selenium.webdriver.common.keys import Keys as _Keys
from selenium.webdriver.support.ui import WebDriverWait as _WebDriverWait
from selenium.webdriver.support import expected_conditions as _EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException

from operation_orchestrator import get_orchestrator
from scoopz_uploader import _select_file_in_dialog, _set_clipboard


def _set_input_js(driver, element, value: str, char_delay: float = 0.0) -> None:
    """
    Input value using send_keys (simulates user typing/pasting).
    This properly triggers all form validation events.
    """
    element.clear()
    
    if char_delay > 0:
        # Character by character with delay
        for char in value:
            element.send_keys(char)
            time.sleep(char_delay)
    else:
        # Fast paste
        element.send_keys(value)



def _is_logged_in(driver) -> bool:
    try:
        if driver.find_elements(_By.CSS_SELECTOR, "a[href='/upload']"):
            return True
        if driver.find_elements(_By.CSS_SELECTOR, "a[href^='/@']"):
            return True
        if driver.find_elements(_By.XPATH, "//*[normalize-space()='Upload' or contains(., 'Upload')]"):
            return True
    except Exception:
        pass
    return False


def _sanitize_nickname(value: str) -> str:
    val = (value or "").strip()
    if len(val) > 20:
        val = val[:20].rstrip()
    if len(val) < 3:
        val = (val + "user")[:3]
    return val


def _sanitize_username(value: str) -> str:
    val = (value or "").strip().lower()
    val = re.sub(r"[^a-z0-9_]", "", val)
    if len(val) > 20:
        val = val[:20]
    if len(val) < 3:
        val = (val + "user")[:3]
    return val


def login_scoopz(
    driver_path: str,
    remote_debugging_address: str,
    email: str,
    password: str,
    upload_url: str = SCOOPZ_UPLOAD_URL,
    max_retries: int = 3,
    keep_browser: bool = True,
    logger=None,
) -> Tuple[bool, str]:
    last_err = ""
    for _ in range(max_retries):
        try:
            def _log(msg: str) -> None:
                try:
                    if logger:
                        logger(msg)
                    else:
                        print(msg)
                except Exception:
                    pass
            options = _webdriver.ChromeOptions()
            options.add_experimental_option("debuggerAddress", remote_debugging_address.strip())
            service = _ChromeService(driver_path)
            driver = _webdriver.Chrome(service=service, options=options)
        except Exception as e:
            last_err = f"attach error: {e}"
            time.sleep(1.0)
            continue

        try:
            try:
                original_handles = list(driver.window_handles)
                original = driver.current_window_handle if original_handles else None
            except Exception:
                original_handles = []
                original = None

            try:
                driver.execute_script("window.open(arguments[0], '_blank');", SCOOPZ_URL)
                time.sleep(1.2)
                all_handles = driver.window_handles
                new_handles = [h for h in all_handles if h not in original_handles]
                scoopz_handle = new_handles[0] if new_handles else all_handles[-1]
                driver.switch_to.window(scoopz_handle)
                for h in list(driver.window_handles):
                    if h != scoopz_handle:
                        try:
                            driver.switch_to.window(h)
                            driver.close()
                        except Exception:
                            pass
                try:
                    driver.switch_to.window(scoopz_handle)
                except Exception:
                    pass
                _log("[LOGIN] Opened Scoopz in new tab")
            except Exception as e:
                _log(f"[LOGIN] window.open failed, fallback to driver.get: {e}")
                try:
                    if driver.window_handles:
                        driver.switch_to.window(driver.window_handles[0])
                except Exception:
                    pass
                try:
                    driver.get(SCOOPZ_URL)
                except Exception:
                    pass

            wait = _WebDriverWait(driver, 30)
            try:
                wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            except Exception:
                pass

            # Open sidebar menu
            try:
                menu_btn = wait.until(
                    _EC.element_to_be_clickable((_By.CSS_SELECTOR, "label[for='webapp-drawer-toggle']"))
                )
                time.sleep(0.6)
                try:
                    menu_btn.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", menu_btn)
                _log("[LOGIN] Menu button clicked")
            except TimeoutException:
                _log("[LOGIN] Menu button not found")

            # Click Sign in in sidebar
            try:
                sign_in_btn = wait.until(
                    _EC.element_to_be_clickable((_By.XPATH, "//button[normalize-space()='Sign in' or contains(., 'Sign in')]"))
                )
                time.sleep(0.4)
                try:
                    sign_in_btn.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click();", sign_in_btn)
                _log("[LOGIN] Sign in clicked")
            except TimeoutException:
                _log("[LOGIN] Sign in not found")

            # Switch to latest tab if modal opened a new one
            try:
                _WebDriverWait(driver, 5).until(lambda d: len(d.window_handles) >= 1)
                driver.switch_to.window(driver.window_handles[-1])
            except Exception:
                pass

            try:
                email_input = wait.until(_EC.element_to_be_clickable((_By.CSS_SELECTOR, "input[name='email']")))
                pass_input = wait.until(_EC.element_to_be_clickable((_By.CSS_SELECTOR, "input[name='password']")))
            except TimeoutException:
                if _is_logged_in(driver):
                    return True, ""
                try:
                    driver.refresh()
                except Exception:
                    pass
                email_input = wait.until(_EC.element_to_be_clickable((_By.CSS_SELECTOR, "input[name='email']")))
                pass_input = wait.until(_EC.element_to_be_clickable((_By.CSS_SELECTOR, "input[name='password']")))
            _log("[LOGIN] Email/Password inputs found")
            
            # Get orchestrator for coordinated input
            orchestrator = get_orchestrator()

            # Email input with delays
            try:
                orchestrator.wait_before_email_input(email)
                email_input.click()
            except Exception:
                pass
            _set_input_js(driver, email_input, email, char_delay=orchestrator.get_char_delay_for_email())
            orchestrator.wait_after_email_input()

            # Password input with delays
            try:
                orchestrator.wait_before_password_input(email)
                pass_input.click()
            except Exception:
                pass
            _set_input_js(driver, pass_input, password, char_delay=orchestrator.get_char_delay_for_password())
            orchestrator.wait_after_password_input()
            
            # Wait before continue button
            orchestrator.wait_before_continue_click(email)

            def _btn_enabled(drv):
                btn = drv.find_element(_By.CSS_SELECTOR, "button[type='submit']")
                disabled = btn.get_attribute("disabled")
                return btn if not disabled else False

            btn = wait.until(_btn_enabled)
            try:
                btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", btn)
            _log("[LOGIN] Continue clicked")

            time.sleep(1.2)

            # Check invalid credentials message
            try:
                err_el = driver.find_element(_By.CSS_SELECTOR, "p.text-error")
                err_text = (err_el.text or "").strip().lower()
                if "invalid email" in err_text or "invalid" in err_text:
                    return False, f"invalid credentials: {err_el.text.strip()}"
            except Exception:
                pass
            
            # Click Upload link or navigate only when upload_url is set
            if upload_url:
                try:
                    upload_link = driver.find_element(_By.CSS_SELECTOR, "a[href='/upload']")
                    if upload_link:
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", upload_link)
                        time.sleep(0.2)
                        upload_link.click()
                        _log("[LOGIN] Clicked Upload link")
                        time.sleep(0.8)
                    else:
                        # Fallback: try by text content
                        upload_link = driver.find_element(_By.XPATH, "//a[.//span[contains(., 'Upload')]]")
                        if upload_link:
                            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", upload_link)
                            time.sleep(0.2)
                            upload_link.click()
                            _log("[LOGIN] Clicked Upload link (via text)")
                            time.sleep(0.8)
                except Exception as e:
                    _log(f"[LOGIN] Click Upload link failed: {e}, fallback to navigate")
                    try:
                        driver.get(upload_url)
                        _log(f"[LOGIN] Navigated to upload page: {upload_url}")
                        time.sleep(0.8)
                    except Exception as e2:
                        _log(f"[LOGIN] Navigation to upload page failed: {e2}")
            
            return True, ""
        except Exception as e:
            try:
                url_now = driver.current_url
                snippet = driver.execute_script(
                    "return (document.body && document.body.innerText) ? document.body.innerText.slice(0,400) : ''"
                ) or ""
                last_err = f"{e} | url={url_now} | snippet={snippet}"
            except Exception:
                last_err = str(e)
            time.sleep(1.0)
        finally:
            if not keep_browser:
                try:
                    driver.quit()
                except Exception:
                    pass

    return False, last_err


def open_profile_in_scoopz(
    driver_path: str,
    remote_debugging_address: str,
    avatar_path: str,
    nickname: str,
    username: str,
    logger=None,
    max_retries: int = 2,
) -> Tuple[bool, str]:
    last_err = ""
    for _ in range(max_retries):
        try:
            def _log(msg: str) -> None:
                try:
                    if logger:
                        logger(msg)
                    else:
                        print(msg)
                except Exception:
                    pass
            options = _webdriver.ChromeOptions()
            options.add_experimental_option("debuggerAddress", remote_debugging_address.strip())
            service = _ChromeService(driver_path)
            driver = _webdriver.Chrome(service=service, options=options)
        except Exception as e:
            last_err = f"attach error: {e}"
            time.sleep(1.0)
            continue

        try:
            wait = _WebDriverWait(driver, 15)
            try:
                wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            except Exception:
                pass

            time.sleep(0.5)
            _log("[PROFILE] Looking for profile link...")

            def _open_menu() -> None:
                try:
                    menu_btn = wait.until(
                        _EC.element_to_be_clickable((_By.CSS_SELECTOR, "label[for='webapp-drawer-toggle']"))
                    )
                    try:
                        menu_btn.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", menu_btn)
                    time.sleep(0.4)
                except Exception:
                    pass

            def _find_profile_link():
                try:
                    return driver.find_element(_By.CSS_SELECTOR, "a[href^='/@']")
                except Exception:
                    pass
                try:
                    return driver.find_element(_By.XPATH, "//a[starts-with(@href, '/@')]")
                except Exception:
                    return None

            def _click_profile_link(plink) -> bool:
                if not plink:
                    return False
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", plink)
                except Exception:
                    pass
                try:
                    plink.click()
                except Exception:
                    try:
                        driver.execute_script("arguments[0].click();", plink)
                    except Exception:
                        return False
                return True

            profile_clicked = False
            for attempt in range(1, 7):
                try:
                    cur_url = driver.current_url or ""
                except Exception:
                    cur_url = ""
                if "/@" in cur_url:
                    _log(f"[PROFILE] Already on profile page (attempt {attempt})")
                    profile_clicked = True
                    break
                _open_menu()
                plink = _find_profile_link()
                if _click_profile_link(plink):
                    _log(f"[PROFILE] Profile clicked (attempt {attempt})")
                    time.sleep(0.8)
                    profile_clicked = True
                    break
                _log(f"[PROFILE] Profile link not found (attempt {attempt})")
                try:
                    driver.refresh()
                except Exception:
                    pass
                time.sleep(1.0)

            if not profile_clicked:
                return False, "Profile link not found"

            # Wait for profile page to load (Edit Profile visible)
            _log("[PROFILE] Waiting for profile page to load...")
            try:
                _WebDriverWait(driver, 25).until(
                    _EC.element_to_be_clickable((_By.XPATH, "//button[normalize-space()='Edit Profile']"))
                )
            except TimeoutException:
                _log("[PROFILE] Edit Profile not visible yet, retrying profile link...")
                profile_clicked = False
                for attempt in range(1, 4):
                    _open_menu()
                    plink = _find_profile_link()
                    if _click_profile_link(plink):
                        _log(f"[PROFILE] Profile re-clicked (attempt {attempt})")
                        time.sleep(1.0)
                        try:
                            _WebDriverWait(driver, 20).until(
                                _EC.element_to_be_clickable((_By.XPATH, "//button[normalize-space()='Edit Profile']"))
                            )
                            profile_clicked = True
                            break
                        except TimeoutException:
                            pass
                    time.sleep(1.0)
                if not profile_clicked:
                    return False, "Profile page load timeout"

            edit_btn = None
            try:
                edit_btn = wait.until(
                    _EC.element_to_be_clickable((_By.XPATH, "//button[normalize-space()='Edit Profile']"))
                )
            except TimeoutException:
                try:
                    edit_btn = driver.find_element(
                        _By.XPATH, "//button[contains(normalize-space(.), 'Edit Profile')]"
                    )
                except Exception:
                    edit_btn = None

            if not edit_btn:
                return False, "Edit Profile button not found"

            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", edit_btn)
            except Exception:
                pass
            try:
                edit_btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", edit_btn)
            _log("[PROFILE] Edit Profile clicked")
            time.sleep(0.5)

            pic_btn = None
            try:
                pic_btn = wait.until(
                    _EC.element_to_be_clickable(
                        (_By.XPATH, "//button[.//span[normalize-space()='Change picture']]")
                    )
                )
            except TimeoutException:
                try:
                    pic_btn = driver.find_element(
                        _By.XPATH, "//button[.//input[@type='file' and contains(@accept,'image')]]"
                    )
                except Exception:
                    pic_btn = None

            if not pic_btn:
                return False, "Change picture button not found"

            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", pic_btn)
            except Exception:
                pass
            if not avatar_path:
                return False, "Avatar path missing"
            if not os.path.exists(avatar_path):
                return False, f"Avatar file not found: {avatar_path}"

            acquired = _dialog_lock.acquire(timeout=15)
            if not acquired:
                return False, "Dialog busy"
            try:
                try:
                    pic_btn.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", pic_btn)
                _log("[PROFILE] Change picture clicked")
                time.sleep(0.15)
                if not _select_file_in_dialog(avatar_path, logger, timeout=15):
                    if _set_clipboard(avatar_path):
                        try:
                            driver.switch_to.active_element.send_keys(_Keys.CONTROL, "v")
                            driver.switch_to.active_element.send_keys(_Keys.ENTER)
                        except Exception:
                            pass
                    else:
                        try:
                            driver.switch_to.active_element.send_keys(avatar_path)
                            driver.switch_to.active_element.send_keys(_Keys.ENTER)
                        except Exception:
                            pass
            finally:
                _dialog_lock.release()

            time.sleep(0.5)
            _log("[PROFILE] Avatar uploaded, waiting for Edit Profile button...")
            try:
                _log(f"[PROFILE] URL after upload: {driver.current_url}")
            except Exception:
                pass
            time.sleep(1.0)
            _log("[PROFILE] Waiting for avatar modal to close...")
            try:
                _WebDriverWait(driver, 15).until(
                    _EC.invisibility_of_element_located(
                        (_By.XPATH, "//div[@data-testid='modal']")
                    )
                )
                _log("[PROFILE] Avatar modal closed")
            except TimeoutException:
                _log("[PROFILE] Avatar modal still visible, continuing")

            def _return_to_profile() -> None:
                _log("[PROFILE] Trying to return to profile page...")
                try:
                    menu_btn = wait.until(
                        _EC.element_to_be_clickable((_By.CSS_SELECTOR, "label[for='webapp-drawer-toggle']"))
                    )
                    try:
                        menu_btn.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", menu_btn)
                    _log("[PROFILE] Menu button clicked (return)")
                    time.sleep(0.4)
                except Exception as e:
                    _log(f"[PROFILE] Menu open failed (return): {e}")
                try:
                    prof_link = wait.until(
                        _EC.element_to_be_clickable((_By.CSS_SELECTOR, "a[href^='/@']"))
                    )
                    try:
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", prof_link)
                    except Exception:
                        pass
                    try:
                        prof_link.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", prof_link)
                    _log("[PROFILE] Profile link clicked (return)")
                    time.sleep(0.8)
                except Exception as e:
                    _log(f"[PROFILE] Profile link not found (return): {e}")

            # Step 1: Wait for Edit Profile button to appear again, then click
            _log("[PROFILE] Step 1: Waiting for Edit Profile button...")
            edit_btn2 = None
            try:
                edit_btn2 = _WebDriverWait(driver, 15).until(
                    _EC.element_to_be_clickable((_By.XPATH, "//button[normalize-space()='Edit Profile']"))
                )
            except TimeoutException:
                _log("[PROFILE] Edit Profile not found, attempting to return to profile page...")
                _return_to_profile()
                try:
                    edit_btn2 = _WebDriverWait(driver, 15).until(
                        _EC.element_to_be_clickable((_By.XPATH, "//button[normalize-space()='Edit Profile']"))
                    )
                except TimeoutException:
                    try:
                        edit_btn2 = driver.find_element(
                            _By.XPATH, "//button[contains(normalize-space(.), 'Edit Profile')]"
                        )
                    except Exception:
                        edit_btn2 = None
            if not edit_btn2:
                return False, "Edit Profile button not found after avatar upload"
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", edit_btn2)
            except Exception:
                pass
            try:
                edit_btn2.click()
            except Exception:
                driver.execute_script("arguments[0].click();", edit_btn2)
            _log("[PROFILE] Step 1: Edit Profile clicked")
            time.sleep(1.2)

            # Step 2: Click Nickname button
            _log("[PROFILE] Step 2: Looking for Nickname button...")
            nickname_btn = None
            try:
                nickname_btn = wait.until(
                    _EC.element_to_be_clickable(
                        (_By.XPATH, "//button[.//div[normalize-space()='Nickname']]")
                    )
                )
            except TimeoutException:
                try:
                    nickname_btn = driver.find_element(
                        _By.XPATH, "//button[contains(., 'Nickname')]"
                    )
                except Exception:
                    nickname_btn = None

            if not nickname_btn:
                return False, "Nickname button not found"

            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", nickname_btn)
            except Exception:
                pass
            try:
                nickname_btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", nickname_btn)
            _log("[PROFILE] Step 2: Nickname button clicked")
            time.sleep(1.0)

            # Wait for modal input to appear
            _log("[PROFILE] Step 3: Waiting for Nickname modal input...")
            try:
                modal_input = wait.until(
                    _EC.visibility_of_element_located(
                        (_By.XPATH, "//div[@data-testid='modal']//input[not(@type='file')]")
                    )
                )
            except TimeoutException:
                return False, "Nickname modal input not found"

            _log("[PROFILE] Step 4: Clearing Nickname input...")
            try:
                modal_input.click()
            except Exception:
                pass
            try:
                modal_input.send_keys(_Keys.CONTROL, "a")
                modal_input.send_keys(_Keys.DELETE)
            except Exception:
                try:
                    modal_input.clear()
                except Exception:
                    pass

            nick_value = _sanitize_nickname(nickname)
            _log(f"[PROFILE] Step 5: Pasting Nickname: {nick_value}")
            try:
                modal_input.send_keys(nick_value)
            except Exception:
                try:
                    _set_input_js(driver, modal_input, nick_value)
                except Exception:
                    pass

            time.sleep(0.3)
            _log("[PROFILE] Step 6: Clicking Save button...")
            save_btn = None
            try:
                save_btn = wait.until(
                    _EC.element_to_be_clickable(
                        (_By.XPATH, "//div[@data-testid='modal']//button[normalize-space()='Save']")
                    )
                )
            except TimeoutException:
                try:
                    save_btn = driver.find_element(
                        _By.XPATH, "//button[normalize-space()='Save']"
                    )
                except Exception:
                    save_btn = None
            if not save_btn:
                return False, "Save button not found"
            try:
                save_btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", save_btn)
            _log("[PROFILE] Step 6: Save clicked")

            _log("[PROFILE] Step 7: Waiting for Nickname modal to close...")
            try:
                _WebDriverWait(driver, 15).until(
                    _EC.invisibility_of_element_located(
                        (_By.XPATH, "//div[@data-testid='modal']")
                    )
                )
                _log("[PROFILE] Step 7: Nickname modal closed")
            except TimeoutException:
                _log("[PROFILE] Step 7: Nickname modal still visible, continuing")

            _log("[PROFILE] Step 8: Waiting for Edit Profile button (after nickname)...")
            edit_btn3 = None
            try:
                edit_btn3 = _WebDriverWait(driver, 15).until(
                    _EC.element_to_be_clickable((_By.XPATH, "//button[normalize-space()='Edit Profile']"))
                )
            except TimeoutException:
                try:
                    edit_btn3 = driver.find_element(
                        _By.XPATH, "//button[contains(normalize-space(.), 'Edit Profile')]"
                    )
                except Exception:
                    edit_btn3 = None
            if not edit_btn3:
                return False, "Edit Profile button not found after nickname save"
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", edit_btn3)
            except Exception:
                pass
            try:
                edit_btn3.click()
            except Exception:
                driver.execute_script("arguments[0].click();", edit_btn3)
            _log("[PROFILE] Step 8: Edit Profile clicked (after nickname)")
            time.sleep(1.0)

            _log("[PROFILE] Step 9: Looking for Username button...")
            username_btn = None
            try:
                username_btn = wait.until(
                    _EC.element_to_be_clickable(
                        (_By.XPATH, "//button[.//div[normalize-space()='Username']]")
                    )
                )
            except TimeoutException:
                try:
                    username_btn = driver.find_element(
                        _By.XPATH, "//button[contains(., 'Username')]"
                    )
                except Exception:
                    username_btn = None
            if not username_btn:
                return False, "Username button not found"
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", username_btn)
            except Exception:
                pass
            try:
                username_btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", username_btn)
            _log("[PROFILE] Step 9: Username button clicked")
            time.sleep(1.0)

            _log("[PROFILE] Step 10: Waiting for Username modal input...")
            try:
                username_input = wait.until(
                    _EC.visibility_of_element_located(
                        (_By.XPATH, "//div[@data-testid='modal']//input[not(@type='file')]")
                    )
                )
            except TimeoutException:
                return False, "Username modal input not found"

            user_base = _sanitize_username(username)
            candidates = []
            def _add_candidate(value: str) -> None:
                if value and value not in candidates:
                    candidates.append(value)

            _add_candidate(user_base)
            _add_candidate(user_base.replace("_", ""))
            if len(user_base) > 12:
                _add_candidate(user_base[:12])
            if len(user_base) > 10:
                _add_candidate((user_base[:10] + "01")[:20])
            if len(user_base) > 8:
                _add_candidate((user_base[:8] + "2025")[:20])

            def _clear_username_input() -> None:
                try:
                    username_input.click()
                except Exception:
                    pass
                try:
                    username_input.send_keys(_Keys.CONTROL, "a")
                    username_input.send_keys(_Keys.DELETE)
                except Exception:
                    try:
                        username_input.clear()
                    except Exception:
                        pass

            _log(f"[PROFILE] Step 11: Username candidates: {len(candidates)}")
            saved_ok = False
            for idx, cand in enumerate(candidates, start=1):
                _log(f"[PROFILE] Step 12.{idx}: Trying Username: {cand}")
                _clear_username_input()
                try:
                    username_input.send_keys(cand)
                except Exception:
                    try:
                        _set_input_js(driver, username_input, cand)
                    except Exception:
                        pass

                time.sleep(0.3)
                _log(f"[PROFILE] Step 13.{idx}: Clicking Save button (username)...")
                save_btn2 = None
                try:
                    save_btn2 = wait.until(
                        _EC.element_to_be_clickable(
                            (_By.XPATH, "//div[@data-testid='modal']//button[normalize-space()='Save']")
                        )
                    )
                except TimeoutException:
                    try:
                        save_btn2 = driver.find_element(
                            _By.XPATH, "//button[normalize-space()='Save']"
                        )
                    except Exception:
                        save_btn2 = None
                if not save_btn2:
                    return False, "Save button not found (username)"
                try:
                    save_btn2.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", save_btn2)
                _log(f"[PROFILE] Step 13.{idx}: Save clicked (username)")

                _log(f"[PROFILE] Step 14.{idx}: Waiting for Username modal to close...")
                try:
                    _WebDriverWait(driver, 6).until(
                        _EC.invisibility_of_element_located(
                            (_By.XPATH, "//div[@data-testid='modal']")
                        )
                    )
                    _log(f"[PROFILE] Step 14.{idx}: Username modal closed")
                    saved_ok = True
                    break
                except TimeoutException:
                    _log(f"[PROFILE] Step 14.{idx}: Modal still visible, retrying")

            if not saved_ok:
                return False, "Username save failed"

            _log("[PROFILE] Avatar uploaded, done")
            return True, ""
        except Exception as e:
            last_err = str(e)
            time.sleep(1.0)

    return False, last_err or "Profile open failed"


def login_scoopz_profile(
    driver_path: str,
    remote_debugging_address: str,
    email: str,
    password: str,
    max_retries: int = 3,
    keep_browser: bool = True,
    logger=None,
) -> Tuple[bool, str]:
    return login_scoopz(
        driver_path,
        remote_debugging_address,
        email,
        password,
        SCOOPZ_URL,
        max_retries=max_retries,
        keep_browser=keep_browser,
        logger=logger,
    )
_dialog_lock = threading.Lock()
