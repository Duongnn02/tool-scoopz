# -*- coding: utf-8 -*-

import queue
import re
import threading
import time
import os
import ctypes
from pathlib import Path
from typing import Callable, Dict, List, Tuple
from urllib.parse import urljoin

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from shorts_csv_store import load_shorts, prepend_new_shorts

Logger = Callable[[str], None]
StopChecker = Callable[[], bool]
StatusCallback = Callable[[str, str], None]

CHROMEDRIVER_PATH = None
MAX_SCROLL = 80
MAX_IDLE_ROUNDS = 12
SCROLL_DELAY_SECONDS = 3.0
CHECKPOINT_WAIT_SECONDS = 1800
CHECKPOINT_POLL_SECONDS = 3
SCAN_MULTI_PROFILE_DIRS = [
    str((Path.cwd() / "chrome_automation_user_data").resolve()),
    str((Path.cwd() / "chrome_automation_user_data_2").resolve()),
    str((Path.cwd() / "chrome_automation_user_data_3").resolve()),
    str((Path.cwd() / "chrome_automation_user_data_4").resolve()),
]
ENV_FILE = Path.cwd() / ".env"


def _build_options(
    user_data_dir: str,
    profile_dir: str = "Default",
    debug_port: int | None = None,
    window_rect: tuple[int, int, int, int] | None = None,
) -> Options:
    opts = Options()
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument(f"--user-data-dir={user_data_dir}")
    if window_rect:
        x, y, w, h = window_rect
        opts.add_argument(f"--window-position={x},{y}")
        opts.add_argument(f"--window-size={w},{h}")
    else:
        opts.add_argument("--start-maximized")
    if profile_dir:
        opts.add_argument(f"--profile-directory={profile_dir}")
    if debug_port is not None:
        opts.add_argument(f"--remote-debugging-port={debug_port}")
    return opts


def _create_driver(options: Options):
    if CHROMEDRIVER_PATH:
        service = Service(CHROMEDRIVER_PATH)
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    driver.set_script_timeout(120)
    return driver


def _parse_netscape_cookies(cookie_file: Path) -> list[dict]:
    if not cookie_file.exists():
        return []
    cookies: list[dict] = []
    for raw in cookie_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _, path, secure, expiry, name, value = parts[:7]
        cookie: dict = {
            "domain": domain,
            "path": path or "/",
            "name": name,
            "value": value,
            "secure": secure.upper() == "TRUE",
        }
        if expiry.isdigit() and int(expiry) > 0:
            cookie["expiry"] = int(expiry)
        cookies.append(cookie)
    return cookies


def _load_env_file(path: Path) -> dict:
    data = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            data[key] = value
    return data


def _get_fb_credentials() -> Tuple[str, str]:
    email = (os.getenv("FB_EMAIL") or "").strip()
    password = (os.getenv("FB_PASSWORD") or "").strip()
    if email and password:
        return email, password
    env_data = _load_env_file(ENV_FILE)
    email = (env_data.get("FB_EMAIL") or email).strip()
    password = (env_data.get("FB_PASSWORD") or password).strip()
    if email:
        os.environ["FB_EMAIL"] = email
    if password:
        os.environ["FB_PASSWORD"] = password
    return email, password


def _add_cookies(driver: webdriver.Chrome, cookies: list[dict]) -> None:
    if not cookies:
        return
    driver.get("https://www.facebook.com/")
    time.sleep(2)
    for cookie in cookies:
        to_add = cookie.copy()
        try:
            driver.add_cookie(to_add)
        except Exception:
            to_add.pop("expiry", None)
            try:
                driver.add_cookie(to_add)
            except Exception:
                continue


def _is_login_or_checkpoint(driver: webdriver.Chrome) -> bool:
    url = (driver.current_url or "").lower()
    if "/checkpoint" in url:
        return True
    try:
        names = {c.get("name", "") for c in driver.get_cookies()}
        has_session = "c_user" in names and "xs" in names
    except Exception:
        has_session = False
    if "/login" in url and not has_session:
        return True
    try:
        has_form = driver.execute_script(
            """
            return Boolean(
              document.querySelector('form[data-testid="royal_login_form"]') &&
              document.querySelector('input[name="email"]') &&
              document.querySelector('input[name="pass"]')
            );
            """
        )
    except Exception:
        has_form = False
    if has_form and not has_session:
        return True
    return False


def _has_fb_session_cookie(driver: webdriver.Chrome) -> bool:
    try:
        names = {c.get("name", "") for c in driver.get_cookies()}
        return "c_user" in names and "xs" in names
    except Exception:
        return False


def _has_royal_login_form(driver: webdriver.Chrome) -> bool:
    try:
        return bool(
            driver.execute_script(
                """
                return Boolean(
                  document.querySelector('form[data-testid="royal_login_form"]') &&
                  document.querySelector('input[name="email"]') &&
                  document.querySelector('input[name="pass"]')
                );
                """
            )
        )
    except Exception:
        return False


def _login_with_env_account(driver: webdriver.Chrome, logger: Logger | None = None, email_label: str = "") -> bool:
    fb_email, fb_password = _get_fb_credentials()
    if not fb_email or not fb_password:
        if logger:
            logger(f"[{email_label}] FB LOGIN ERR: missing FB_EMAIL/FB_PASSWORD in .env")
        return False
    try:
        email_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[name="email"]')
        pass_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[name="pass"]')
        if not email_inputs or not pass_inputs:
            return not _has_royal_login_form(driver)
        email_input = email_inputs[0]
        pass_input = pass_inputs[0]
        email_input.clear()
        time.sleep(0.3)
        email_input.send_keys(fb_email)
        time.sleep(0.4)
        pass_input.clear()
        time.sleep(0.3)
        pass_input.send_keys(fb_password)
        time.sleep(0.5)

        submit = None
        for sel in ['button[name="login"]', 'button[data-testid="royal-login-button"]', 'button[type="submit"]']:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            if elems:
                submit = elems[0]
                break
        if submit is not None:
            try:
                submit.click()
            except Exception:
                driver.execute_script("arguments[0].click();", submit)
        else:
            pass_input.submit()
        time.sleep(6)
        return not _has_royal_login_form(driver) and not _is_login_or_checkpoint(driver)
    except Exception:
        return False


def _prepare_authenticated_session(
    driver: webdriver.Chrome,
    target_url: str,
    cookies: list[dict],
    logger: Logger | None = None,
    email_label: str = "",
) -> bool:
    driver.get("https://www.facebook.com/")
    time.sleep(2)

    # If profile already has FB session cookies, skip auto-login entirely.
    if _has_fb_session_cookie(driver):
        if logger:
            logger(f"[{email_label}] FB LOGIN: session cookie found (c_user/xs), skip auto-login")
        time.sleep(1)
        return not _is_login_or_checkpoint(driver)

    if _has_royal_login_form(driver):
        if logger:
            logger(f"[{email_label}] FB LOGIN: form detected, trying .env account")
        if not _login_with_env_account(driver, logger=logger, email_label=email_label):
            if logger:
                logger(f"[{email_label}] FB LOGIN: .env login failed, trying cookie fallback")
            if cookies:
                _add_cookies(driver, cookies)
                driver.get("https://www.facebook.com/")
                time.sleep(3)
                if _has_royal_login_form(driver):
                    if not _login_with_env_account(driver, logger=logger, email_label=email_label):
                        return False
            else:
                return False
    else:
        if logger:
            logger(f"[{email_label}] FB LOGIN: no login form, session already active")

    # After login, stay on home and pause briefly before opening reel link.
    time.sleep(1)
    return not _is_login_or_checkpoint(driver)


def _wait_for_manual_checkpoint(
    driver: webdriver.Chrome,
    stop_check: StopChecker,
    logger: Logger | None,
    email_label: str = "",
) -> bool:
    _show_window_for_manual_check(driver)
    start = time.time()
    while not stop_check():
        if not _is_login_or_checkpoint(driver):
            if logger:
                logger(f"[{email_label}] CHECKPOINT resolved, continue.")
            return True
        if logger:
            logger(f"[{email_label}] CHECKPOINT/login detected. Please handle manually in browser...")
        if time.time() - start > CHECKPOINT_WAIT_SECONDS:
            if logger:
                logger(f"[{email_label}] CHECKPOINT wait timeout.")
            return False
        time.sleep(CHECKPOINT_POLL_SECONDS)
    return False


def _open_target_in_new_tab(driver: webdriver.Chrome, target_url: str) -> bool:
    try:
        original = driver.current_window_handle
        before = set(driver.window_handles)
        driver.execute_script("window.open('about:blank', '_blank');")
        time.sleep(0.5)
        after = driver.window_handles
        new_handles = [h for h in after if h not in before]
        if new_handles:
            driver.switch_to.window(new_handles[-1])
        else:
            driver.switch_to.window(after[-1])
        driver.get(target_url)
        time.sleep(2)
        return True
    except Exception:
        return False


def _close_current_tab_return(driver: webdriver.Chrome) -> None:
    try:
        handles = driver.window_handles
        if len(handles) <= 1:
            return
        driver.close()
        remaining = driver.window_handles
        if remaining:
            driver.switch_to.window(remaining[0])
    except Exception:
        pass


def _get_screen_rects_2x2() -> list[tuple[int, int, int, int]]:
    try:
        user32 = ctypes.windll.user32
        sw = int(user32.GetSystemMetrics(0))
        sh = int(user32.GetSystemMetrics(1))
        if sw <= 0 or sh <= 0:
            raise RuntimeError("invalid screen metrics")
    except Exception:
        sw, sh = 1920, 1080
    half_w = max(640, sw // 2)
    half_h = max(400, sh // 2)
    return [
        (0, 0, half_w, half_h),              # top-left
        (half_w, 0, half_w, half_h),         # top-right
        (0, half_h, half_w, half_h),         # bottom-left
        (half_w, half_h, half_w, half_h),    # bottom-right
    ]


def _set_background_window(driver: webdriver.Chrome) -> None:
    try:
        driver.minimize_window()
    except Exception:
        pass


def _show_window_for_manual_check(driver: webdriver.Chrome) -> None:
    try:
        driver.maximize_window()
    except Exception:
        pass


def _ensure_authenticated(driver: webdriver.Chrome, reels_url: str, cookies: list[dict]) -> bool:
    if not _is_login_or_checkpoint(driver):
        return True
    if cookies:
        _add_cookies(driver, cookies)
        driver.get(reels_url)
        time.sleep(3)
        if not _is_login_or_checkpoint(driver):
            return True
    return not _is_login_or_checkpoint(driver)


def _extract_reel_id(url: str) -> str:
    m = re.search(r"/reel/(\d+)", url or "")
    return m.group(1) if m else ""


def _collect_visible_reels(driver: webdriver.Chrome) -> list[dict]:
    return driver.execute_script(
        """
        const anchors = document.querySelectorAll('a[href*="/reel/"]');
        const out = [];
        anchors.forEach(a => out.push({ href: a.getAttribute('href') || a.href || '' }));
        return out;
        """
    )


def _prepare_target_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("/"):
        return f"https://www.facebook.com{value}"
    return f"https://www.facebook.com/{value.lstrip('/')}"


def _scrape_reels(
    driver: webdriver.Chrome,
    reels_url: str,
    stop_check: StopChecker,
    logger: Logger,
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen_ids = set()
    idle_rounds = 0
    last_count = 0

    for _ in range(MAX_SCROLL):
        if stop_check():
            break
        if _is_login_or_checkpoint(driver):
            if logger:
                logger("[FB SCAN] Stop: login/checkpoint.")
            break
        for item in _collect_visible_reels(driver):
            href = (item.get("href") or "").strip()
            full_url = urljoin("https://www.facebook.com", href)
            reel_id = _extract_reel_id(full_url)
            if not reel_id or reel_id in seen_ids:
                continue
            seen_ids.add(reel_id)
            canonical = f"https://www.facebook.com/reel/{reel_id}"
            rows.append({"video_id": reel_id, "title": "", "url": canonical})

        if len(rows) == last_count:
            idle_rounds += 1
        else:
            idle_rounds = 0
            last_count = len(rows)
        if idle_rounds >= MAX_IDLE_ROUNDS:
            break

        try:
            driver.execute_script("window.scrollBy(0, Math.max(window.innerHeight * 0.9, 700));")
            time.sleep(0.6)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        except Exception:
            pass
        time.sleep(SCROLL_DELAY_SECONDS)

    return rows


def scan_facebook_reels_for_email(
    email: str,
    reels_url: str,
    stop_check: StopChecker,
    logger: Logger,
    cookie_file: str = "cookiefb.txt",
    user_data_dir: str = "",
    profile_dir: str = "Default",
    debug_port: int | None = None,
) -> Tuple[int, int]:
    url = _prepare_target_url(reels_url)
    if not url:
        return 0, 0

    if not user_data_dir:
        user_data_dir = SCAN_MULTI_PROFILE_DIRS[0]
    Path(user_data_dir).mkdir(parents=True, exist_ok=True)
    options = _build_options(user_data_dir=user_data_dir, profile_dir=profile_dir, debug_port=debug_port)
    driver = _create_driver(options)
    try:
        cookies = _parse_netscape_cookies(Path(cookie_file))
        if not _prepare_authenticated_session(driver, url, cookies, logger=logger, email_label=email):
            if logger:
                logger(f"[{email}] FB SCAN ERR: login/checkpoint")
            return 0, 0
        if not _open_target_in_new_tab(driver, url):
            if logger:
                logger(f"[{email}] FB SCAN ERR: cannot open reel tab")
            return 0, 0
        if _is_login_or_checkpoint(driver):
            if logger:
                logger(f"[{email}] FB SCAN ERR: redirected to login")
            _close_current_tab_return(driver)
            return 0, 0
        videos = _scrape_reels(driver, url, stop_check, logger)
        existing = load_shorts(email)
        existing_ids = {row.get("video_id") for row in existing if row.get("video_id")}

        new_videos: List[Dict[str, str]] = []
        for video in videos:
            if stop_check():
                break
            vid = (video.get("video_id") or "").strip()
            if not vid:
                continue
            if vid in existing_ids:
                break
            new_videos.append(video)

        total, added = prepend_new_shorts(email, new_videos)
        if logger:
            logger(f"[{email}] FB SCAN OK: added {added}, total {total}")
        return total, added
    finally:
        _close_current_tab_return(driver)
        try:
            driver.quit()
        except Exception:
            pass


def scan_facebook_reels_multi(
    accounts: List[dict],
    stop_check: StopChecker,
    logger: Logger,
    cookie_file: str = "cookiefb.txt",
    profile_dirs: List[str] | None = None,
    max_workers: int = 4,
    on_status: StatusCallback | None = None,
    background_mode: bool = True,
) -> Dict[str, Tuple[int, int]]:
    if not accounts:
        return {}

    profile_dirs = profile_dirs or SCAN_MULTI_PROFILE_DIRS
    profile_dirs = [p for p in profile_dirs if p]
    if not profile_dirs:
        profile_dirs = SCAN_MULTI_PROFILE_DIRS[:1]

    for p in profile_dirs:
        Path(p).mkdir(parents=True, exist_ok=True)

    q: queue.Queue = queue.Queue()
    for acc in accounts:
        q.put(acc)

    results: Dict[str, Tuple[int, int]] = {}
    results_lock = threading.Lock()
    workers = min(max(1, max_workers), len(profile_dirs), q.qsize())
    screen_rects = _get_screen_rects_2x2()

    def _worker(worker_id: int, user_data_dir: str) -> None:
        if stop_check():
            return
        driver = None
        options = _build_options(
            user_data_dir=user_data_dir,
            profile_dir="Default",
            debug_port=9400 + worker_id,
            window_rect=screen_rects[(worker_id - 1) % len(screen_rects)],
        )
        cookies = _parse_netscape_cookies(Path(cookie_file))
        try:
            driver = _create_driver(options)
            if logger:
                logger(f"[FB SCAN W{worker_id}] Started profile: {user_data_dir}")
            if not _prepare_authenticated_session(
                driver,
                "https://www.facebook.com/",
                cookies,
                logger=logger,
                email_label=f"W{worker_id}",
            ):
                if logger:
                    logger(f"[FB SCAN W{worker_id}] LOGIN ERR: cannot authenticate")
                return
            if logger:
                logger(f"[FB SCAN W{worker_id}] LOGIN OK")
            if background_mode:
                _set_background_window(driver)
            while not stop_check():
                try:
                    acc = q.get_nowait()
                except queue.Empty:
                    break
                email = (acc.get("uid") or "").strip()
                reels_url = _prepare_target_url((acc.get("facebook") or "").strip())
                try:
                    if not email or not reels_url:
                        if on_status and email:
                            on_status(email, "SCAN SKIP: No link")
                        continue
                    if on_status:
                        on_status(email, "SCAN...")
                    if not _open_target_in_new_tab(driver, reels_url):
                        if on_status:
                            on_status(email, "SCAN ERR: OPEN TAB")
                        if logger:
                            logger(f"[{email}] FB SCAN ERR: cannot open reel tab")
                        continue
                    if _is_login_or_checkpoint(driver):
                        if on_status:
                            on_status(email, "CHECKPOINT - CHO XU LY")
                        if not _wait_for_manual_checkpoint(driver, stop_check, logger, email):
                            if on_status:
                                on_status(email, "SCAN ERR: LOGIN/CHECKPOINT")
                            continue
                        if background_mode:
                            _set_background_window(driver)

                    videos = _scrape_reels(driver, reels_url, stop_check, logger)
                    existing = load_shorts(email)
                    existing_ids = {row.get("video_id") for row in existing if row.get("video_id")}
                    new_videos: List[Dict[str, str]] = []
                    for video in videos:
                        if stop_check():
                            break
                        vid = (video.get("video_id") or "").strip()
                        if not vid:
                            continue
                        if vid in existing_ids:
                            break
                        new_videos.append(video)
                    total, added = prepend_new_shorts(email, new_videos)
                    with results_lock:
                        results[email] = (total, added)
                    if on_status:
                        on_status(email, f"SCAN OK ({added})")
                    if logger:
                        logger(f"[{email}] FB SCAN OK: added {added}, total {total}")
                except Exception as e:
                    with results_lock:
                        results[email] = (0, 0)
                    if on_status and email:
                        on_status(email, f"SCAN ERR: {e}")
                    if logger and email:
                        logger(f"[{email}] FB SCAN ERR: {e}")
                finally:
                    _close_current_tab_return(driver)
                    q.task_done()
        finally:
            try:
                if driver is not None:
                    driver.quit()
            except Exception:
                pass

    threads: List[threading.Thread] = []
    for i in range(workers):
        t = threading.Thread(
            target=_worker,
            args=(i + 1, profile_dirs[i]),
            daemon=True,
        )
        threads.append(t)
        t.start()
        time.sleep(1.2)
    for t in threads:
        t.join()
    return results
