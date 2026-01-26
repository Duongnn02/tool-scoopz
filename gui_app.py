# -*- coding: utf-8 -*-

import os
import sys
import threading
import json
import csv
import subprocess
import time
import math
import re
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_THIS_DIR)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
if _BASE_DIR not in sys.path:
    sys.path.insert(1, _BASE_DIR)

from gpm_client import create_profile, start_profile, close_profile, delete_profile, extract_driver_info
from login_scoopz import login_scoopz, login_scoopz_profile, open_profile_in_scoopz
from config import SCOOPZ_URL, SCOOPZ_UPLOAD_URL, COOKIES_FILE
from yt_simple_download import download_one
from shorts_csv_store import get_next_unuploaded, mark_uploaded, update_title_if_empty
from scoopz_uploader import upload_prepare, upload_post_async
from followers_fetcher import fetch_followers
from profile_updater import fetch_youtube_profile_assets_local, update_profile_from_assets
from shorts_scanner import scan_shorts_for_email
from threading_utils import ResourcePool, RetryHelper, ThreadSafeCounter
from logging_config import initialize_logger
from rate_limiter import initialize_rate_limiting, get_operation_delayer
from operation_orchestrator import initialize_orchestrator


ACCOUNTS = []


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("GPM Multi-Profile Test")
        self.root.geometry("1100x520")
        self._accounts_file = os.path.join(_THIS_DIR, "accounts_cache.json")
        self._profile_accounts_file = os.path.join(_THIS_DIR, "profile_accounts_cache.json")
        
        # Initialize logger
        log_dir = os.path.join(_THIS_DIR, "logs")
        self.error_logger = initialize_logger(log_dir)
        self.error_logger.log_info("SYSTEM", "START", "Application started")
        
        # Initialize orchestrator with BALANCED mode
        # This coordinates all operations: login delays, sequential downloads, serial uploads
        self.orchestrator = initialize_orchestrator("balanced", logger=self.error_logger.main_logger.info)
        
        # Initialize rate limiter with balanced strategy
        initialize_rate_limiting("balanced")
        self.operation_delayer = get_operation_delayer()

        self.stop_event = threading.Event()
        self.executor = None
        self.executor_lock = threading.Lock()  # Lock for executor access
        self.active_profiles = {}
        self.active_lock = threading.Lock()
        self.created_profiles = set()
        self.create_lock = threading.Lock()
        # Resource management
        self.dialog_lock_pool = ResourcePool()  # Per-driver file dialog locks
        self.file_dialog_semaphore = threading.BoundedSemaphore(1)  # ⭐ CRITICAL: Only 1 dialog at a time!
        self.post_button_semaphore = threading.BoundedSemaphore(1)  # ⭐ CRITICAL: Only 1 POST button click at a time!
        self.upload_retry_semaphore = threading.BoundedSemaphore(2)  # Max 2 concurrent uploads
        self.login_semaphore = threading.BoundedSemaphore(2)  # Max 2 concurrent logins
        self.active_drivers = {}  # Track active drivers per thread
        self.active_drivers_lock = threading.Lock()
        self.profile_active_drivers = {}
        self.profile_active_drivers_lock = threading.Lock()
        self.profile_created_profiles = set()
        self.profile_semaphore = None
        self.profile_update_lock = threading.Lock()
        self.csv_lock = threading.Lock()  # CSV atomic operations
        
        # Track failed accounts for retry after completion
        self.failed_accounts = []
        self.failed_accounts_lock = threading.Lock()
        self.profile_failed_accounts = []
        self.profile_failed_lock = threading.Lock()
        
        self._log_lock = threading.Lock()
        self._dragging = False
        self._drag_start = None
        self._context_item = None
        self._profile_dragging = False
        self._profile_drag_start = None
        self._profile_context_item = None
        self._cell_editor = None
        self.repeat_var = tk.BooleanVar(value=False)
        self._repeat_after_id = None
        self._repeat_enabled = False
        self._repeat_delay_sec = 0
        self._retry_round = 0
        self._profile_retry_round = 0

        self._build_ui()
        self.accounts = self._load_accounts_cache() or ACCOUNTS
        self._load_rows()
        self.profile_accounts = self._load_profile_accounts_cache()
        self._load_profile_rows()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=8, pady=8)

        ttk.Label(top, text="Số luồng:").pack(side="left")
        self.entry_threads = ttk.Entry(top, width=5)
        self.entry_threads.insert(0, "5")
        self.entry_threads.pack(side="left", padx=(5, 15))

        ttk.Label(top, text="Videos:").pack(side="left")
        self.entry_videos = ttk.Entry(top, width=5)
        self.entry_videos.insert(0, "1")
        self.entry_videos.pack(side="left", padx=(5, 15))

        self.chk_repeat = ttk.Checkbutton(top, text="Repeat", variable=self.repeat_var)
        self.chk_repeat.pack(side="left", padx=(0, 6))
        ttk.Label(top, text="Delay (min):").pack(side="left")
        self.entry_repeat_delay = ttk.Entry(top, width=6)
        self.entry_repeat_delay.insert(0, "5")
        self.entry_repeat_delay.pack(side="left", padx=(5, 15))

        self.btn_start = ttk.Button(top, text="START", command=self.start_jobs)
        self.btn_start.pack(side="left", padx=(0, 8))

        self.btn_stop = ttk.Button(top, text="STOP", command=self.stop_jobs)
        self.btn_stop.pack(side="left")
        self.btn_reload = ttk.Button(top, text="RELOAD", command=self.reload_app)
        self.btn_reload.pack(side="left", padx=(8, 0))
        self.btn_import = ttk.Button(top, text="IMPORT", command=self.import_accounts)
        self.btn_import.pack(side="left", padx=(8, 0))
        self.btn_scan = ttk.Button(top, text="SCAN", command=self.start_scan)
        self.btn_scan.pack(side="left", padx=(8, 0))
        self.btn_clear_videos = ttk.Button(top, text="CLEAR VIDEOS", command=self.clear_all_email_videos)
        self.btn_clear_videos.pack(side="left", padx=(8, 0))

        self.notebook = ttk.Notebook(self.root)
        self.tab_upload = ttk.Frame(self.notebook)
        self.tab_profile = ttk.Frame(self.notebook)
        self.tab_interact = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_upload, text="UPLOAD")
        self.notebook.add(self.tab_profile, text="PROFILE")
        self.notebook.add(self.tab_interact, text="INTERACT")
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        # Add Select All / Deselect All buttons for tab_upload
        btn_frame_upload = ttk.Frame(self.tab_upload)
        btn_frame_upload.pack(fill="x", padx=8, pady=(8, 4))

        ttk.Button(btn_frame_upload, text="Select All", command=self._select_all_accounts).pack(side="left", padx=(0, 4))
        ttk.Button(btn_frame_upload, text="Deselect All", command=self._deselect_all_accounts).pack(side="left")

        self.tree = ttk.Treeview(
            self.tab_upload,
            columns=("chk", "stt", "email", "pass", "proxy", "status", "followers", "profile_url", "profile_id"),
            show="headings",
            selectmode="extended",
        )
        self.tree.heading("chk", text="v")
        self.tree.column("chk", width=40, anchor="center")
        self.tree.heading("stt", text="STT")
        self.tree.column("stt", width=50, anchor="center")
        self.tree.heading("email", text="EMAIL")
        self.tree.column("email", width=240)
        self.tree.heading("pass", text="PASS")
        self.tree.column("pass", width=130)
        self.tree.heading("proxy", text="PROXY")
        self.tree.column("proxy", width=260)
        self.tree.heading("status", text="TRẠNG THÁI")
        self.tree.column("status", width=200)
        self.tree.heading("followers", text="FOLLOWERS", command=self._sort_followers_desc)
        self.tree.column("followers", width=90, anchor="center")
        self.tree.heading("profile_url", text="PROFILE URL")
        self.tree.column("profile_url", width=260)
        self.tree.heading("profile_id", text="PROFILE ID")
        self.tree.column("profile_id", width=240)

        self.tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.tree.tag_configure("status_ok", foreground="green")
        self.tree.tag_configure("status_err", foreground="red")

        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<B1-Motion>", self._on_tree_drag)
        self.tree.bind("<ButtonRelease-1>", self._on_tree_release)
        self.tree.bind("<Button-3>", self._on_tree_right_click)

        self.profile_tree = ttk.Treeview(
            self.tab_profile,
            columns=("chk", "stt", "email", "pass", "proxy", "youtube", "status"),
            show="headings",
            selectmode="extended",
        )
        self.profile_tree.heading("chk", text="v")
        self.profile_tree.column("chk", width=40, anchor="center")
        self.profile_tree.heading("stt", text="STT")
        self.profile_tree.column("stt", width=50, anchor="center")
        self.profile_tree.heading("email", text="EMAIL")
        self.profile_tree.column("email", width=240)
        self.profile_tree.heading("pass", text="PASS")
        self.profile_tree.column("pass", width=130)
        self.profile_tree.heading("proxy", text="PROXY")
        self.profile_tree.column("proxy", width=260)
        self.profile_tree.heading("youtube", text="YOUTUBE")
        self.profile_tree.column("youtube", width=280)
        self.profile_tree.heading("status", text="TRẠNG THÁI")
        self.profile_tree.column("status", width=200)

        self.profile_tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.profile_tree.tag_configure("status_ok", foreground="green")
        self.profile_tree.tag_configure("status_err", foreground="red")

        profile_top = ttk.Frame(self.tab_profile)
        profile_top.pack(fill="x", padx=8, pady=(8, 0))
        self.btn_import_profile = ttk.Button(
            profile_top, text="IMPORT PROFILE", command=self.import_profile_accounts
        )
        self.btn_import_profile.pack(side="left")

        self.profile_tree.bind("<Button-1>", self._on_profile_tree_click)
        self.profile_tree.bind("<B1-Motion>", self._on_profile_tree_drag)
        self.profile_tree.bind("<ButtonRelease-1>", self._on_profile_tree_release)
        self.profile_tree.bind("<Button-3>", self._on_profile_tree_right_click)

        interact_top = ttk.Frame(self.tab_interact)
        interact_top.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(interact_top, text="Like comments:").pack(side="left")
        self.entry_like_min = ttk.Entry(interact_top, width=4)
        self.entry_like_min.insert(0, "1")
        self.entry_like_min.pack(side="left", padx=(5, 5))
        ttk.Label(interact_top, text="to").pack(side="left")
        self.entry_like_max = ttk.Entry(interact_top, width=4)
        self.entry_like_max.insert(0, "10")
        self.entry_like_max.pack(side="left", padx=(5, 15))
        self.chk_reply = ttk.Checkbutton(interact_top, text="Reply", variable=tk.BooleanVar(value=True))
        self.chk_reply.pack(side="left", padx=(0, 10))
        ttk.Label(interact_top, text="Watch videos:").pack(side="left")
        self.entry_watch_min = ttk.Entry(interact_top, width=4)
        self.entry_watch_min.insert(0, "1")
        self.entry_watch_min.pack(side="left", padx=(5, 5))
        ttk.Label(interact_top, text="to").pack(side="left")
        self.entry_watch_max = ttk.Entry(interact_top, width=4)
        self.entry_watch_max.insert(0, "3")
        self.entry_watch_max.pack(side="left", padx=(5, 15))
        ttk.Label(interact_top, text="Join circles max:").pack(side="left")
        self.entry_join_max = ttk.Entry(interact_top, width=4)
        self.entry_join_max.insert(0, "10")
        self.entry_join_max.pack(side="left", padx=(5, 15))
        self.btn_start_interact = ttk.Button(interact_top, text="START INTERACT", command=self._interact_not_ready)
        self.btn_start_interact.pack(side="left")
        self.btn_start_join = ttk.Button(interact_top, text="START JOIN", command=self.start_join_circles)
        self.btn_start_join.pack(side="left", padx=(8, 0))

        interact_body = ttk.Frame(self.tab_interact)
        interact_body.pack(fill="both", expand=True, padx=8, pady=8)
        ttk.Label(interact_body, text="Paste URLs (one per line):").pack(anchor="w")
        self.interact_urls = tk.Text(interact_body, height=12)
        self.interact_urls.pack(fill="both", expand=True)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Tick selected", command=lambda: self._set_checked_selected(True))
        self.menu.add_command(label="Untick selected", command=lambda: self._set_checked_selected(False))
        self.menu.add_separator()
        self.menu.add_command(label="Login selected", command=self.menu_login_selected)
        self.menu.add_command(label="Upload selected", command=self.menu_upload_selected)
        self.menu.add_command(label="Get followers", command=self.menu_follow_selected)

        self.profile_menu = tk.Menu(self.root, tearoff=0)
        self.profile_menu.add_command(label="Tick selected", command=lambda: self._set_checked_selected_profile(True))
        self.profile_menu.add_command(label="Untick selected", command=lambda: self._set_checked_selected_profile(False))
        self.profile_menu.add_separator()
        self.profile_menu.add_command(label="Open YouTube", command=self.menu_profile_selected)

        self.log_box = tk.Text(self.root, height=6, state="disabled")
        self.log_box.pack(fill="both", expand=False, padx=8, pady=(0, 8))

    def _interact_not_ready(self) -> None:
        self._log("[INTERACT] UI ready. Logic will be added next step.")

    def _get_join_max(self) -> int:
        try:
            val = int(self.entry_join_max.get())
            if val > 0:
                return val
        except Exception:
            pass
        return 10

    def start_join_circles(self) -> None:
        if self.executor is not None:
            return
        try:
            max_threads = int(self.entry_threads.get())
            if max_threads <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Loi", "So luong phai > 0")
            return

        self.stop_event.clear()
        self.executor = ThreadPoolExecutor(max_workers=max_threads)
        self.login_semaphore = threading.BoundedSemaphore(max_threads)
        checked_items = [iid for iid in self.tree.get_children() if self.tree.set(iid, "chk") == "v"]
        if not checked_items:
            messagebox.showinfo("Thong bao", "Khong co profile nao duoc tick.")
            self.executor = None
            return

        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
        except Exception:
            screen_w, screen_h = 1920, 1080
        gap = 6
        taskbar_h = 40
        usable_w = screen_w - (gap * 2)
        usable_h = (screen_h - taskbar_h) - (gap * 2)
        active_count = len(checked_items)
        cols = min(5, active_count)
        rows_layout = min(2, max(1, math.ceil(active_count / cols)))
        win_w = int((usable_w - gap * (cols - 1)) / cols)
        win_h = int((usable_h - gap * (rows_layout - 1)) / rows_layout)
        win_w = max(150, min(280, win_w))
        win_h = max(420, min(600, win_h))

        join_max = self._get_join_max()
        slot_idx = 0
        max_slots = cols * rows_layout
        for item_id in checked_items:
            try:
                idx = int(item_id) - 1
            except Exception:
                continue
            if 0 <= idx < len(self.accounts):
                acc = self.accounts[idx]
                pos = slot_idx % max_slots
                col = pos % cols
                row = pos // cols
                x = gap + col * (win_w + gap)
                y = gap + row * (win_h + gap)
                win_pos = f"{x},{y}"
                win_size = f"{win_w},{win_h}"
                self.executor.submit(self._join_circles_worker, item_id, acc, win_pos, win_size, join_max)
                slot_idx += 1

        def _waiter():
            try:
                self.executor.shutdown(wait=True)
            except Exception:
                pass
            self.executor = None

        threading.Thread(target=_waiter, daemon=True).start()

    def _join_circles_worker(self, item_id: str, acc: dict, win_pos: str, win_size: str, join_max: int) -> None:
        if self.stop_event.is_set():
            return
        profile_id = None
        try:
            self._set_status(item_id, "CREATE...")
            ok_c = False
            data_c = {}
            msg_c = ""
            with self.create_lock:
                for attempt in range(3):
                    ok_c, data_c, msg_c = create_profile(acc["uid"], acc["proxy"], SCOOPZ_URL)
                    if ok_c:
                        break
                    wait_s = 5 + attempt * 3
                    self._set_status(item_id, f"CREATE RETRY {attempt+1}/3")
                    self._log(f"[{acc['uid']}] CREATE ERR: {msg_c} | retry in {wait_s}s")
                    time.sleep(wait_s)
            if not ok_c:
                self._set_status(item_id, f"CREATE ERR: {msg_c}")
                self._log(f"[{acc['uid']}] CREATE ERR: {msg_c}")
                self._record_failed(item_id, acc, f"CREATE ERR: {msg_c}")
                return

            if isinstance(data_c, dict):
                profile_id = (data_c.get("data") or {}).get("id") or data_c.get("id") or data_c.get("profile_id")
            if not profile_id:
                self._set_status(item_id, "NO PROFILE ID")
                self._record_failed(item_id, acc, "NO PROFILE ID")
                return
            self.created_profiles.add(profile_id)

            self._set_status(item_id, "START...", profile_id=profile_id)
            ok_s, data_s, msg_s = start_profile(profile_id, win_pos=win_pos, win_size=win_size)
            if not ok_s:
                self._set_status(item_id, f"START ERR: {msg_s}")
                self._log(f"[{acc['uid']}] START ERR: {msg_s}")
                self._record_failed(item_id, acc, f"START ERR: {msg_s}")
                return

            with self.active_lock:
                self.active_profiles[item_id] = profile_id
            driver_path, remote = extract_driver_info(data_s)
            status = "STARTED" if driver_path and remote else "STARTED (no debug)"
            self._set_status(item_id, status, profile_id=profile_id)
            self._log(f"[{acc['uid']}] START OK")

            if not driver_path or not remote:
                self._record_failed(item_id, acc, "STARTED (no debug)")
                return

            self._set_status(item_id, "LOGIN...")
            self._log(f"[{acc['uid']}] LOGIN START")
            ok_login, err_login = login_scoopz(
                driver_path,
                remote,
                acc["uid"],
                acc["pass"],
                "",
                max_retries=3,
                keep_browser=True,
            )
            if not ok_login:
                status = self._format_login_error(err_login)
                self._set_status(item_id, status)
                self._log(f"[{acc['uid']}] {status}")
                self._record_failed(item_id, acc, status)
                return

            if self.stop_event.is_set():
                return

            self._set_status(item_id, "JOIN CIRCLES...")
            self._log(f"[{acc['uid']}] JOIN START")

            try:
                from selenium import webdriver
                from selenium.webdriver.chrome.service import Service as ChromeService
                from selenium.webdriver.common.by import By
                from selenium.webdriver.support.ui import WebDriverWait
            except Exception as e:
                self._set_status(item_id, f"JOIN ERR: {e}")
                self._record_failed(item_id, acc, f"JOIN ERR: {e}")
                return

            options = webdriver.ChromeOptions()
            options.add_experimental_option("debuggerAddress", remote.strip())
            driver = webdriver.Chrome(service=ChromeService(driver_path), options=options)
            wait = WebDriverWait(driver, 15)
            base_url = "https://thescoopz.com"
            driver.get(f"{base_url}/circles")

            try:
                wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, "a.card[href^='/c/']"))
            except Exception:
                self._set_status(item_id, "JOIN ERR: no circles found")
                self._log(f"[{acc['uid']}] JOIN ERR: no circles found on /circles page")
                self._record_failed(item_id, acc, "JOIN ERR: no circles found")
                driver.quit()
                return

            # Scroll to load more circles before collecting
            max_scroll = 6
            for scroll_attempt in range(max_scroll):
                if self.stop_event.is_set():
                    break
                try:
                    driver.execute_script("window.scrollBy(0, document.body.scrollHeight);")
                    time.sleep(0.6)
                except Exception as e:
                    self._log(f"[{acc['uid']}] JOIN: scroll error - {e}")
                    break

            # Collect circle links
            try:
                cards = driver.find_elements(By.CSS_SELECTOR, "a.card[href^='/c/']")
                if not cards:
                    self._set_status(item_id, "JOIN ERR: no circles to join")
                    self._log(f"[{acc['uid']}] JOIN ERR: cards empty after scroll")
                    self._record_failed(item_id, acc, "JOIN ERR: no circles to join")
                    driver.quit()
                    return
                    
                hrefs = []
                for el in cards:
                    try:
                        href = (el.get_attribute("href") or "").strip()
                        if not href:
                            continue
                        if href.startswith("/"):
                            href = f"{base_url}{href}"
                        if href not in hrefs:
                            hrefs.append(href)
                    except Exception as e:
                        self._log(f"[{acc['uid']}] JOIN: error extracting href - {e}")
                        continue
                
                if not hrefs:
                    self._set_status(item_id, "JOIN ERR: no valid hrefs")
                    self._log(f"[{acc['uid']}] JOIN ERR: extracted hrefs list is empty")
                    self._record_failed(item_id, acc, "JOIN ERR: no valid hrefs")
                    driver.quit()
                    return
                    
                # Randomize the order
                try:
                    random.shuffle(hrefs)
                    self._log(f"[{acc['uid']}] Found {len(hrefs)} circles, shuffled & starting join...")
                except Exception as e:
                    self._log(f"[{acc['uid']}] JOIN: shuffle error - {e}, using original order")
                    # Continue anyway with original order if shuffle fails
                    
            except Exception as e:
                self._set_status(item_id, f"JOIN ERR: collect circles failed")
                self._log(f"[{acc['uid']}] JOIN ERR: failed to collect circles - {e}")
                self._record_failed(item_id, acc, f"JOIN ERR: {e}")
                driver.quit()
                return

            joined = 0
            for idx, href in enumerate(hrefs, 1):
                if self.stop_event.is_set() or joined >= join_max:
                    break
                try:
                    driver.get(href)
                    time.sleep(0.4)
                    already = driver.find_elements(By.XPATH, "//button[normalize-space()='Joined' or normalize-space()='Leave']")
                    if already:
                        self._log(f"[{acc['uid']}] Circle {idx}/{len(hrefs)}: already joined")
                        continue
                    join_btn = None
                    btns = driver.find_elements(By.XPATH, "//button[normalize-space()='Join' or .//*[normalize-space()='Join']]")
                    if btns:
                        join_btn = btns[0]
                    if not join_btn:
                        self._log(f"[{acc['uid']}] Circle {idx}/{len(hrefs)}: join button not found")
                        continue
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", join_btn)
                    time.sleep(0.2)
                    driver.execute_script("arguments[0].click();", join_btn)
                    joined += 1
                    self._log(f"[{acc['uid']}] JOINED {joined}/{join_max}: circle #{idx} - {href}")
                    time.sleep(0.5)
                except Exception as e:
                    self._log(f"[{acc['uid']}] Circle {idx}/{len(hrefs)}: error - {e}")
                    continue

            self._set_status(item_id, f"JOIN OK ({joined})")
            self._log(f"[{acc['uid']}] JOIN OK: {joined}")
        finally:
            try:
                if profile_id:
                    close_profile(profile_id, 3)
                    delete_profile(profile_id, 10)
            except Exception:
                pass
            try:
                with self.active_lock:
                    self.active_profiles.pop(item_id, None)
            except Exception:
                pass
    def _load_rows(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for idx, row in enumerate(self.accounts, start=1):
            followers = row.get("followers", "")
            profile_url = row.get("profile_url", "")
            self.tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    "v",
                    idx,
                    row.get("uid", ""),
                    row.get("pass", ""),
                    row.get("proxy", ""),
                    "READY",
                    "" if followers is None else str(followers),
                    profile_url,
                    row.get("profile_id", ""),
                ),
            )

    def _load_profile_rows(self) -> None:
        self.profile_tree.delete(*self.profile_tree.get_children())
        for idx, row in enumerate(self.profile_accounts, start=1):
            self.profile_tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    "v",
                    idx,
                    row.get("uid", ""),
                    row.get("pass", ""),
                    row.get("proxy", ""),
                    row.get("youtube", ""),
                    row.get("status", "READY"),
                ),
            )

    def _set_status(self, item_id: str, status: str, profile_id: str = "") -> None:
        def _update():
            if profile_id:
                self.tree.set(item_id, "profile_id", profile_id)
            self.tree.set(item_id, "status", status)
            self._apply_status_tag(item_id, status)

        self.root.after(0, _update)

    def _set_profile_status(self, item_id: str, status: str) -> None:
        def _update():
            self.profile_tree.set(item_id, "status", status)
            self._apply_profile_status_tag(item_id, status)

        self.root.after(0, _update)

    def _record_failed(self, item_id: str, acc: dict, reason: str) -> None:
        with self.failed_accounts_lock:
            for iid, _acc in self.failed_accounts:
                if iid == item_id:
                    return
            self.failed_accounts.append((item_id, acc))
        try:
            log_path = os.path.join(_THIS_DIR, "logs", "failed_accounts.log")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{acc.get('uid','')} | {reason}\n")
        except Exception:
            pass
        try:
            self._move_account_to_bottom(acc.get("uid", ""))
        except Exception:
            pass

    def _record_profile_failed(self, item_id: str, acc: dict, reason: str) -> None:
        with self.profile_failed_lock:
            for iid, _acc in self.profile_failed_accounts:
                if iid == item_id:
                    return
            self.profile_failed_accounts.append((item_id, acc))
        try:
            log_path = os.path.join(_THIS_DIR, "logs", "failed_profile_accounts.log")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{acc.get('uid','')} | {reason}\n")
        except Exception:
            pass

    def _clear_failed_log(self) -> None:
        try:
            log_path = os.path.join(_THIS_DIR, "logs", "failed_accounts.log")
            if os.path.exists(log_path):
                os.remove(log_path)
        except Exception:
            pass

    def _clear_profile_failed_log(self) -> None:
        try:
            log_path = os.path.join(_THIS_DIR, "logs", "failed_profile_accounts.log")
            if os.path.exists(log_path):
                os.remove(log_path)
        except Exception:
            pass

    def _move_account_to_bottom(self, uid: str) -> None:
        if not uid:
            return
        try:
            idx = next((i for i, a in enumerate(self.accounts) if a.get("uid") == uid), None)
        except Exception:
            idx = None
        if idx is None:
            return
        acc = self.accounts.pop(idx)
        self.accounts.append(acc)
        self._rebuild_tree_from_accounts()

    def _rebuild_tree_from_accounts(self) -> None:
        state = {}
        for iid in self.tree.get_children():
            email = self.tree.set(iid, "email")
            state[email] = {
                "chk": self.tree.set(iid, "chk"),
                "status": self.tree.set(iid, "status"),
                "followers": self.tree.set(iid, "followers"),
                "profile_url": self.tree.set(iid, "profile_url"),
                "profile_id": self.tree.set(iid, "profile_id"),
                "tags": self.tree.item(iid, "tags"),
            }
        self.tree.delete(*self.tree.get_children())
        for idx, row in enumerate(self.accounts, start=1):
            email = row.get("uid", "")
            cached = state.get(email, {})
            followers = cached.get("followers", row.get("followers", ""))
            profile_url = cached.get("profile_url", row.get("profile_url", ""))
            status = cached.get("status", "READY")
            chk = cached.get("chk", "v")
            tags = cached.get("tags", ())
            self.tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    chk,
                    idx,
                    email,
                    row.get("pass", ""),
                    row.get("proxy", ""),
                    status,
                    "" if followers is None else str(followers),
                    profile_url,
                    cached.get("profile_id", row.get("profile_id", "")),
                ),
                tags=tags,
            )

    def _sort_followers_desc(self) -> None:
        follower_map = {}
        for iid in self.tree.get_children():
            email = self.tree.set(iid, "email")
            followers = self.tree.set(iid, "followers")
            if email:
                follower_map[email] = followers

        def _to_num(val) -> int:
            if val is None or val == "":
                return -1
            text = str(val).strip()
            if not text:
                return -1
            digits = re.sub(r"[^0-9]", "", text)
            if not digits:
                return -1
            try:
                return int(digits)
            except Exception:
                return -1

        self.accounts.sort(
            key=lambda acc: _to_num(
                # Check followers field first, then fallback to tree map using email
                acc.get("followers")
                if acc.get("followers") is not None
                else follower_map.get(acc.get("email", ""), "")
            ),
            reverse=True,
        )
        self._rebuild_tree_from_accounts()

    def _apply_status_tag(self, item_id: str, status: str) -> None:
        status_upper = (status or "").upper()
        if any(key in status_upper for key in ["ERR", "ERROR", "FAIL", "BLOCKED", "LOI"]):
            self.tree.item(item_id, tags=("status_err",))
        elif any(key in status_upper for key in ["OK", "SUCCESS", "DONE"]):
            self.tree.item(item_id, tags=("status_ok",))
        else:
            self.tree.item(item_id, tags=())

    def _apply_profile_status_tag(self, item_id: str, status: str) -> None:
        status_upper = (status or "").upper()
        if any(key in status_upper for key in ["ERR", "ERROR", "FAIL", "BLOCKED", "LOI"]):
            self.profile_tree.item(item_id, tags=("status_err",))
        elif any(key in status_upper for key in ["OK", "SUCCESS", "DONE", "UPDATED"]):
            self.profile_tree.item(item_id, tags=("status_ok",))
        else:
            self.profile_tree.item(item_id, tags=())

    def _log(self, msg: str) -> None:
        def _append():
            self.log_box.configure(state="normal")
            self.log_box.insert(tk.END, msg + "\n")
            self.log_box.see(tk.END)
            self.log_box.configure(state="disabled")
        self.root.after(0, _append)

    def _format_login_error(self, err: str) -> str:
        text = (err or "").strip().lower()
        if "invalid credentials" in text or "invalid email" in text:
            return "SAI PASS"
        return f"LOGIN ERR: {err}"

    def clear_all_email_videos(self) -> None:
        if self.executor is not None:
            self._log("[CLEAR] Dang chay job, hay STOP truoc.")
            return
        ok = messagebox.askyesno("Confirm", "Xoa tat ca video trong folder email?")
        if not ok:
            return
        base = os.path.join(_THIS_DIR, "video")
        if not os.path.isdir(base):
            self._log("[CLEAR] Folder video khong ton tai.")
            return
        exts = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
        deleted = 0
        for root, _dirs, files in os.walk(base):
            for name in files:
                ext = os.path.splitext(name)[1].lower()
                if ext not in exts:
                    continue
                path = os.path.join(root, name)
                try:
                    os.remove(path)
                    deleted += 1
                except Exception as e:
                    self._log(f"[CLEAR] DEL ERR: {path} | {e}")
        self._log(f"[CLEAR] Deleted {deleted} video files.")

    def _set_profile_info(self, item_id: str, profile_url: str, followers) -> None:
        def _update():
            if profile_url:
                self.tree.set(item_id, "profile_url", profile_url)
            if followers is not None:
                self.tree.set(item_id, "followers", str(followers))
        self.root.after(0, _update)
        try:
            idx = int(item_id) - 1
            if 0 <= idx < len(self.accounts):
                if profile_url:
                    self.accounts[idx]["profile_url"] = profile_url
                if followers is not None:
                    self.accounts[idx]["followers"] = followers
                self._save_accounts_cache()
        except Exception:
            pass

    def _delete_uploaded_video(self, path: str, email: str) -> None:
        if not path:
            return
        try:
            if os.path.exists(path):
                os.remove(path)
                self._log(f"[{email}] DELETE OK: {os.path.basename(path)}")
        except Exception as e:
            self._log(f"[{email}] DELETE ERR: {e}")

    def _ensure_video_folder(self, email: str) -> None:
        if not email:
            return
        safe = email.strip().lower().replace("@", "_at_").replace(".", "_")
        try:
            base = os.path.join(_THIS_DIR, "video", safe)
            os.makedirs(base, exist_ok=True)
        except Exception:
            pass

    def _save_profile_assets(self, email: str, name: str, username: str, avatar_path: str) -> None:
        if not email:
            return
        safe = email.strip().lower().replace("@", "_at_").replace(".", "_")
        out_dir = os.path.join(_THIS_DIR, "video", safe)
        try:
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, "profile_assets.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"email": email, "name": name, "username": username, "avatar_path": avatar_path},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception:
            pass

    def _load_profile_assets(self, email: str) -> dict:
        if not email:
            return {}
        safe = email.strip().lower().replace("@", "_at_").replace(".", "_")
        path = os.path.join(_THIS_DIR, "video", safe, "profile_assets.json")
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _log_progress(self, msg: str) -> None:
        def _append():
            self.log_box.configure(state="normal")
            # Replace last line for progress logs
            if msg.startswith("[DL]"):
                try:
                    content = self.log_box.get("1.0", tk.END)
                    lines = content.rstrip("\n").split("\n")
                    if lines and lines[-1].startswith("[DL]"):
                        self.log_box.delete("1.0", tk.END)
                        self.log_box.insert(tk.END, "\n".join(lines[:-1]) + ("\n" if lines[:-1] else ""))
                except Exception:
                    pass
            self.log_box.insert(tk.END, msg + "\n")
            self.log_box.see(tk.END)
            self.log_box.configure(state="disabled")
        with self._log_lock:
            self.root.after(0, _append)

    def _toggle_checked(self, item_id: str) -> None:
        cur = self.tree.set(item_id, "chk")
        self.tree.set(item_id, "chk", "" if cur == "v" else "v")

    def _select_all_accounts(self) -> None:
        """Select all accounts (mark all as checked)"""
        for item_id in self.tree.get_children():
            self.tree.set(item_id, "chk", "v")

    def _deselect_all_accounts(self) -> None:
        """Deselect all accounts (unmark all)"""
        for item_id in self.tree.get_children():
            self.tree.set(item_id, "chk", "")

    def _set_checked_selected(self, checked: bool) -> None:
        mark = "v" if checked else ""
        for item_id in self.tree.selection():
            self.tree.set(item_id, "chk", mark)

    def _close_cell_editor(self, save: bool) -> None:
        editor = self._cell_editor
        if not editor:
            return
        entry = editor.get("entry")
        if save and entry:
            try:
                self._apply_cell_edit(editor, entry.get())
            except Exception:
                pass
        try:
            if entry:
                entry.destroy()
        except Exception:
            pass
        self._cell_editor = None

    def _apply_cell_edit(self, editor: dict, new_value: str) -> None:
        tree = editor.get("tree")
        item_id = editor.get("item_id")
        col_name = editor.get("col_name")
        if not tree or not item_id or not col_name:
            return
        tree.set(item_id, col_name, new_value)
        try:
            idx = int(item_id) - 1
        except Exception:
            idx = None
        if tree == self.tree:
            if idx is None or idx >= len(self.accounts):
                return
            if col_name == "email":
                self.accounts[idx]["uid"] = new_value
            elif col_name in ("pass", "proxy"):
                self.accounts[idx][col_name] = new_value
            self._save_accounts_cache()
        elif tree == self.profile_tree:
            if idx is None or idx >= len(self.profile_accounts):
                return
            if col_name == "email":
                self.profile_accounts[idx]["uid"] = new_value
            elif col_name in ("pass", "proxy", "youtube"):
                self.profile_accounts[idx][col_name] = new_value
            self._save_profile_accounts_cache()

    def _begin_cell_edit(self, tree: ttk.Treeview, item_id: str, col_name: str) -> None:
        self._close_cell_editor(save=True)
        bbox = tree.bbox(item_id, col_name)
        if not bbox:
            return
        x, y, w, h = bbox
        entry = tk.Entry(tree)
        entry.insert(0, tree.set(item_id, col_name))
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        entry.selection_range(0, tk.END)
        self._cell_editor = {"tree": tree, "item_id": item_id, "col_name": col_name, "entry": entry}

        def _save(_evt=None):
            self._close_cell_editor(save=True)

        def _cancel(_evt=None):
            self._close_cell_editor(save=False)

        entry.bind("<Return>", _save)
        entry.bind("<Escape>", _cancel)
        entry.bind("<FocusOut>", _save)

    def _on_tree_click(self, event) -> None:
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        column = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if row:
            try:
                col_idx = int(column[1:]) - 1
                col_name = self.tree["columns"][col_idx]
            except Exception:
                col_name = ""
            if col_name in {"email", "pass", "proxy"}:
                self._begin_cell_edit(self.tree, row, col_name)
                return "break"
        if column == "#1":
            if row:
                self._toggle_checked(row)
                return "break"
        if row:
            self._dragging = True
            self._drag_start = row

    def _on_tree_drag(self, event) -> None:
        if not self._dragging or not self._drag_start:
            return
        row = self.tree.identify_row(event.y)
        if not row:
            return
        children = list(self.tree.get_children())
        try:
            start_idx = children.index(self._drag_start)
            cur_idx = children.index(row)
        except ValueError:
            return
        lo = min(start_idx, cur_idx)
        hi = max(start_idx, cur_idx)
        self.tree.selection_set(children[lo : hi + 1])

    def _on_tree_release(self, event) -> None:
        self._dragging = False
        self._drag_start = None

    def _on_tree_right_click(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
            self._context_item = row
            self.menu.tk_popup(event.x_root, event.y_root)

    def _toggle_checked_profile(self, item_id: str) -> None:
        cur = self.profile_tree.set(item_id, "chk")
        self.profile_tree.set(item_id, "chk", "" if cur == "v" else "v")

    def _set_checked_selected_profile(self, checked: bool) -> None:
        mark = "v" if checked else ""
        for item_id in self.profile_tree.selection():
            self.profile_tree.set(item_id, "chk", mark)

    def _on_profile_tree_click(self, event) -> None:
        region = self.profile_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        column = self.profile_tree.identify_column(event.x)
        row = self.profile_tree.identify_row(event.y)
        if row:
            try:
                col_idx = int(column[1:]) - 1
                col_name = self.profile_tree["columns"][col_idx]
            except Exception:
                col_name = ""
            if col_name in {"email", "pass", "proxy", "youtube"}:
                self._begin_cell_edit(self.profile_tree, row, col_name)
                return "break"
        if column == "#1":
            if row:
                self._toggle_checked_profile(row)
                return "break"
        if row:
            self._profile_dragging = True
            self._profile_drag_start = row

    def _on_profile_tree_drag(self, event) -> None:
        if not self._profile_dragging or not self._profile_drag_start:
            return
        row = self.profile_tree.identify_row(event.y)
        if not row:
            return
        children = list(self.profile_tree.get_children())
        try:
            start_idx = children.index(self._profile_drag_start)
            cur_idx = children.index(row)
        except ValueError:
            return
        lo = min(start_idx, cur_idx)
        hi = max(start_idx, cur_idx)
        self.profile_tree.selection_set(children[lo : hi + 1])

    def _on_profile_tree_release(self, event) -> None:
        self._profile_dragging = False
        self._profile_drag_start = None

    def _on_profile_tree_right_click(self, event) -> None:
        row = self.profile_tree.identify_row(event.y)
        if row:
            if row not in self.profile_tree.selection():
                self.profile_tree.selection_set(row)
            self._profile_context_item = row
            self.profile_menu.tk_popup(event.x_root, event.y_root)

    def _get_selected_accounts(self):
        items = []
        for iid in self.tree.selection():
            try:
                idx = int(iid) - 1
            except Exception:
                continue
            if 0 <= idx < len(self.accounts):
                items.append((iid, self.accounts[idx]))
        return items

    def _get_selected_profile_accounts(self):
        items = []
        for iid in self.profile_tree.selection():
            try:
                idx = int(iid) - 1
            except Exception:
                continue
            if 0 <= idx < len(self.profile_accounts):
                items.append((iid, self.profile_accounts[idx]))
        return items

    def _get_checked_accounts(self):
        items = []
        for iid in self.tree.get_children():
            if self.tree.set(iid, "chk") != "v":
                continue
            try:
                idx = int(iid) - 1
            except Exception:
                continue
            if 0 <= idx < len(self.accounts):
                items.append((iid, self.accounts[idx]))
        return items

    def _get_checked_profile_accounts(self):
        items = []
        for iid in self.profile_tree.get_children():
            if self.profile_tree.set(iid, "chk") != "v":
                continue
            try:
                idx = int(iid) - 1
            except Exception:
                continue
            if 0 <= idx < len(self.profile_accounts):
                items.append((iid, self.profile_accounts[idx]))
        return items

    def _get_context_accounts(self):
        if self._context_item:
            try:
                idx = int(self._context_item) - 1
            except Exception:
                return []
            if 0 <= idx < len(self.accounts):
                return [(self._context_item, self.accounts[idx])]
        return []

    def _get_context_profile_accounts(self):
        if self._profile_context_item:
            try:
                idx = int(self._profile_context_item) - 1
            except Exception:
                return []
            if 0 <= idx < len(self.profile_accounts):
                return [(self._profile_context_item, self.profile_accounts[idx])]
        return []

    def menu_login_selected(self) -> None:
        if self.executor is not None:
            self._log("[MENU] Dang chay job, hay STOP truoc.")
            return
        selected = self._get_context_accounts() or self._get_selected_accounts() or self._get_checked_accounts()
        if not selected:
            return
        max_threads = max(1, int(self.entry_threads.get() or 1))
        pool = ThreadPoolExecutor(max_workers=max_threads)
        for item_id, acc in selected:
            pool.submit(self._login_only_worker, item_id, acc)

    def menu_upload_selected(self) -> None:
        if self.executor is not None:
            self._log("[MENU] Dang chay job, hay STOP truoc.")
            return
        selected = self._get_context_accounts() or self._get_selected_accounts() or self._get_checked_accounts()
        if not selected:
            return
        max_threads = max(1, int(self.entry_threads.get() or 1))
        pool = ThreadPoolExecutor(max_workers=max_threads)
        for item_id, acc in selected:
            pool.submit(self._upload_only_worker, item_id, acc)

    def menu_follow_selected(self) -> None:
        if self.executor is not None:
            self._log("[MENU] Dang chay job, hay STOP truoc.")
            return
        selected = self._get_context_accounts() or self._get_selected_accounts() or self._get_checked_accounts()
        if not selected:
            return
        max_threads = max(1, int(self.entry_threads.get() or 1))
        pool = ThreadPoolExecutor(max_workers=max_threads)
        for item_id, acc in selected:
            pool.submit(self._follow_only_worker, item_id, acc)

    def menu_profile_selected(self) -> None:
        if self.executor is not None:
            self._log("[MENU] Dang chay job, hay STOP truoc.")
            return
        if not self._is_profile_tab():
            self._log("[MENU] Vao tab PROFILE de chay.")
            return
        selected = (
            self._get_context_profile_accounts()
            or self._get_selected_profile_accounts()
            or self._get_checked_profile_accounts()
        )
        if not selected:
            return
        max_threads = max(1, int(self.entry_threads.get() or 1))
        pool = ThreadPoolExecutor(max_workers=max_threads)
        self.profile_semaphore = threading.BoundedSemaphore(max_threads)
        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
        except Exception:
            screen_w, screen_h = 1920, 1080
        gap = 6  # Tight spacing between windows
        taskbar_h = 40  # Reserve space for taskbar
        usable_w = screen_w - (gap * 2)
        usable_h = (screen_h - taskbar_h) - (gap * 2)
        active_count = len(selected)
        cols = min(5, active_count)
        rows_layout = min(2, max(1, math.ceil(active_count / cols)))
        win_w = int((usable_w - gap * (cols - 1)) / cols)
        win_h = int((usable_h - gap * (rows_layout - 1)) / rows_layout)
        win_w = max(150, min(280, win_w))
        win_h = max(420, min(600, win_h))
        slot_idx = 0
        max_slots = cols * rows_layout
        for idx_item, (item_id, acc) in enumerate(selected):
            pos = slot_idx % max_slots
            col = pos % cols
            row = pos // cols
            x = gap + col * (win_w + gap)
            y = gap + row * (win_h + gap)
            win_pos = f"{x},{y}"
            win_size = f"{win_w},{win_h}"
            pool.submit(self._profile_open_worker, item_id, acc, win_pos, win_size)
            slot_idx += 1

    def _load_accounts_cache(self) -> list:
        if not os.path.exists(self._accounts_file):
            return []
        try:
            with open(self._accounts_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            return []
        return []

    def _save_accounts_cache(self) -> None:
        try:
            with open(self._accounts_file, "w", encoding="utf-8") as f:
                json.dump(self.accounts, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_profile_accounts_cache(self) -> list:
        if not os.path.exists(self._profile_accounts_file):
            return []
        try:
            with open(self._profile_accounts_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            return []
        return []

    def _save_profile_accounts_cache(self) -> None:
        try:
            with open(self._profile_accounts_file, "w", encoding="utf-8") as f:
                json.dump(self.profile_accounts, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _on_close(self) -> None:
        self._save_accounts_cache()
        self._save_profile_accounts_cache()
        # Print error summary before closing
        self.error_logger.print_error_summary()
        try:
            self.root.destroy()
        except Exception:
            pass

    def import_accounts(self) -> None:
        path = filedialog.askopenfilename(
            title="Import accounts",
            filetypes=[
                ("Excel", "*.xlsx"),
                ("Text/CSV", "*.txt;*.csv;*.tsv"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        rows = []
        try:
            if ext == ".xlsx":
                try:
                    import openpyxl  # type: ignore
                except Exception:
                    messagebox.showerror("Import", "Can phai cai dat openpyxl de doc file .xlsx")
                    return
                wb = openpyxl.load_workbook(path, read_only=True)
                ws = wb.active
                for row in ws.iter_rows(values_only=True):
                    if not row:
                        continue
                    rows.append([str(c).strip() if c is not None else "" for c in row])
            else:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                delimiter = "\t" if "\t" in content else ","
                reader = csv.reader(content.splitlines(), delimiter=delimiter)
                rows = [r for r in reader if r]
        except Exception as e:
            messagebox.showerror("Import", f"Loi doc file: {e}")
            return

        new_accounts = []
        for row in rows:
            if len(row) < 4:
                continue
            uid = (row[0] or "").strip()
            pwd = (row[1] or "").strip()
            proxy = (row[2] or "").strip()
            yt = (row[3] or "").strip()
            if uid.lower() in ("email", "uid") and pwd.lower() in ("pass", "password") and proxy.lower() in ("proxy", "raw_proxy"):
                continue
            if not uid:
                continue
            new_accounts.append({"uid": uid, "pass": pwd, "proxy": proxy, "youtube": yt})

        if not new_accounts:
            messagebox.showinfo("Import", "Khong tim thay dong du lieu hop le.")
            return

        self.accounts = new_accounts
        self._load_rows()
        self._save_accounts_cache()
        self._log(f"[IMPORT] Loaded {len(new_accounts)} accounts")

    def import_profile_accounts(self) -> None:
        path = filedialog.askopenfilename(
            title="Import profile accounts",
            filetypes=[
                ("Excel", "*.xlsx"),
                ("Text/CSV", "*.txt;*.csv;*.tsv"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        rows = []
        try:
            if ext == ".xlsx":
                try:
                    import openpyxl  # type: ignore
                except Exception:
                    messagebox.showerror("Import", "Can phai cai dat openpyxl de doc file .xlsx")
                    return
                wb = openpyxl.load_workbook(path, read_only=True)
                ws = wb.active
                for row in ws.iter_rows(values_only=True):
                    if not row:
                        continue
                    rows.append([str(c).strip() if c is not None else "" for c in row])
            else:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                delimiter = "\t" if "\t" in content else ","
                reader = csv.reader(content.splitlines(), delimiter=delimiter)
                rows = [r for r in reader if r]
        except Exception as e:
            messagebox.showerror("Import", f"Loi doc file: {e}")
            return

        new_accounts = []
        for row in rows:
            if len(row) < 4:
                continue
            uid = (row[0] or "").strip()
            pwd = (row[1] or "").strip()
            proxy = (row[2] or "").strip()
            yt = (row[3] or "").strip()
            if uid.lower() in ("email", "uid") and pwd.lower() in ("pass", "password") and proxy.lower() in ("proxy", "raw_proxy"):
                continue
            if not uid:
                continue
            new_accounts.append({"uid": uid, "pass": pwd, "proxy": proxy, "youtube": yt})

        if not new_accounts:
            messagebox.showinfo("Import", "Khong tim thay dong du lieu hop le.")
            return

        self.profile_accounts = new_accounts
        self._load_profile_rows()
        self._save_profile_accounts_cache()
        self._log(f"[IMPORT PROFILE] Loaded {len(new_accounts)} accounts")

    def _is_profile_tab(self) -> bool:
        try:
            return self.notebook.nametowidget(self.notebook.select()) == self.tab_profile
        except Exception:
            return False

    def start_profile_jobs(self) -> None:
        if self.executor is not None:
            return
        if self._repeat_after_id:
            try:
                self.root.after_cancel(self._repeat_after_id)
            except Exception:
                pass
            self._repeat_after_id = None
        try:
            max_threads = int(self.entry_threads.get())
            if max_threads <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Lỗi", "Số luồng phải > 0")
            return

        self.stop_event.clear()
        self._profile_retry_round = 0
        with self.profile_failed_lock:
            self.profile_failed_accounts = []
        self.executor = ThreadPoolExecutor(max_workers=max_threads)
        self.profile_semaphore = threading.BoundedSemaphore(max_threads)
        checked_items = [iid for iid in self.profile_tree.get_children() if self.profile_tree.set(iid, "chk") == "v"]
        if not checked_items:
            messagebox.showinfo("Thong bao", "Khong co profile nao duoc tick.")
            self.executor = None
            return

        # Same layout as upload: 5 columns, max 2 rows
        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
        except Exception:
            screen_w, screen_h = 1920, 1080
        gap = 6  # Tight spacing between windows
        taskbar_h = 40  # Reserve space for taskbar
        usable_w = screen_w - (gap * 2)
        usable_h = (screen_h - taskbar_h) - (gap * 2)
        active_count = len(checked_items)
        cols = min(5, active_count)
        rows_layout = min(2, max(1, math.ceil(active_count / cols)))
        win_w = int((usable_w - gap * (cols - 1)) / cols)
        win_h = int((usable_h - gap * (rows_layout - 1)) / rows_layout)
        win_w = max(150, min(280, win_w))
        win_h = max(420, min(600, win_h))

        slot_idx = 0
        max_slots = cols * rows_layout
        for idx_item, item_id in enumerate(checked_items):
            try:
                idx = int(item_id) - 1
            except Exception:
                continue
            if 0 <= idx < len(self.profile_accounts):
                acc = self.profile_accounts[idx]
                pos = slot_idx % max_slots
                col = pos % cols
                row = pos // cols
                x = gap + col * (win_w + gap)
                y = gap + row * (win_h + gap)
                win_pos = f"{x},{y}"
                win_size = f"{win_w},{win_h}"
                self.executor.submit(self._profile_open_worker, item_id, acc, win_pos, win_size)
                slot_idx += 1

        def _waiter():
            try:
                self.executor.shutdown(wait=True)
            except Exception:
                pass
            self.executor = None
            with self.profile_failed_lock:
                failed_list = self.profile_failed_accounts.copy()
                self.profile_failed_accounts = []
            if failed_list and not self.stop_event.is_set():
                if self._profile_retry_round < 3:
                    self._profile_retry_round += 1
                    self._log(f"[PROFILE RETRY] Retrying {len(failed_list)} failed accounts (round {self._profile_retry_round}/3)...")
                    self.root.after(1000, lambda fl=failed_list: self._retry_failed_profile_accounts(fl, max_threads))
                    return
            self._clear_profile_failed_log()

        threading.Thread(target=_waiter, daemon=True).start()


    def start_jobs(self) -> None:
        if self._is_profile_tab():
            self.start_profile_jobs()
            return
        if self.executor is not None:
            return
        if self._repeat_after_id:
            try:
                self.root.after_cancel(self._repeat_after_id)
            except Exception:
                pass
            self._repeat_after_id = None
        try:
            max_threads = int(self.entry_threads.get())
            if max_threads <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Lỗi", "Số luồng phải > 0")
            return

        self.stop_event.clear()
        self._retry_round = 0
        # Clear failed accounts list at start of new cycle
        with self.failed_accounts_lock:
            self.failed_accounts = []
        
        # Use exact number of threads (no extra retry threads)
        self.executor = ThreadPoolExecutor(max_workers=max_threads)
        self.login_semaphore = threading.BoundedSemaphore(max_threads)
        self.upload_retry_semaphore = threading.BoundedSemaphore(max_threads)

        checked_items = [iid for iid in self.tree.get_children() if self.tree.set(iid, "chk") == "v"]
        if not checked_items:
            messagebox.showinfo("Thong bao", "Khong co profile nao duoc tick.")
            return

        # Optimized layout: 5 profiles per row, full screen width - COMPACT MODE
        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
        except Exception:
            screen_w, screen_h = 1920, 1080
        
        gap = 6  # Tight spacing between windows
        taskbar_h = 40  # Reserve space for taskbar
        usable_w = screen_w - (gap * 2)
        usable_h = (screen_h - taskbar_h) - (gap * 2)
        active_count = len(checked_items)
        
        # Fixed layout: 5 columns, max 2 rows (overflow cycles back to row 1)
        cols = min(5, active_count)  # Max 5 per row
        rows_layout = min(2, max(1, math.ceil(active_count / cols)))
        
        # Calculate window sizes
        win_w = int((usable_w - gap * (cols - 1)) / cols)
        win_h = int((usable_h - gap * (rows_layout - 1)) / rows_layout)
        
        # Compact windows: narrow width, optimal height
        win_w = max(150, min(280, win_w))  # Even more compact: 150-280px
        win_h = max(420, min(600, win_h))  # Height range: 420-600px

        futures = []

        try:
            max_videos = int(self.entry_videos.get())
            if max_videos <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Loi", "Videos phai > 0")
            return

        self._repeat_enabled = bool(self.repeat_var.get())
        try:
            delay_min = float(self.entry_repeat_delay.get())
            if delay_min < 0:
                delay_min = 0
        except Exception:
            delay_min = 0
        self._repeat_delay_sec = delay_min * 60.0

        slot_idx = 0
        max_slots = cols * rows_layout
        for idx, acc in enumerate(self.accounts, start=1):
            item_id = str(idx)
            if item_id not in checked_items:
                continue
            pos = slot_idx % max_slots
            col = pos % cols
            row = pos // cols
            x = gap + col * (win_w + gap)
            y = gap + row * (win_h + gap)
            win_pos = f"{x},{y}"
            win_size = f"{win_w},{win_h}"
            futures.append(self.executor.submit(self._worker_one, item_id, acc, win_pos, win_size, max_videos))
            slot_idx += 1

        def _waiter():
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception:
                    pass
            
            # Check if there are failed accounts to retry
            with self.failed_accounts_lock:
                failed_list = self.failed_accounts.copy()
                self.failed_accounts = []
            
            self.executor = None
            
            # If failed accounts exist, retry them immediately (only during run)
            if failed_list and not self.stop_event.is_set():
                if self._retry_round < 3:
                    self._retry_round += 1
                self._log(f"[RETRY] Retrying {len(failed_list)} failed accounts (round {self._retry_round}/3)...")
                # Don't use the last loop's win_pos/win_size; let _retry_failed_accounts calculate its own layout
                self.root.after(1000, lambda fl=failed_list: self._retry_failed_accounts(fl, max_threads, max_videos))
                return
            self._clear_failed_log()
            
            if self._repeat_enabled and not self.stop_event.is_set():
                delay_ms = int(self._repeat_delay_sec * 1000)
                if delay_ms < 0:
                    delay_ms = 0

                def _repeat_start():
                    if self.stop_event.is_set():
                        return
                    self._repeat_after_id = None
                    # Use repeat cycle instead of full restart for smoother operation
                    self._do_repeat_cycle()

                self._repeat_after_id = self.root.after(delay_ms, _repeat_start)

        threading.Thread(target=_waiter, daemon=True).start()

    def _do_repeat_cycle(self) -> None:
        """Repeat cycle for smooth continuous upload without recalculating layout"""
        if self.executor is not None:
            return
        
        try:
            max_threads = int(self.entry_threads.get())
            if max_threads <= 0:
                raise ValueError
        except Exception:
            return

        # Get checked items (should still be checked from previous run)
        checked_items = [iid for iid in self.tree.get_children() if self.tree.set(iid, "chk") == "v"]
        if not checked_items:
            return

        # Clear executor state
        self.stop_event.clear()
        self._retry_round = 0
        with self.failed_accounts_lock:
            self.failed_accounts = []

        # Use same thread count
        self.executor = ThreadPoolExecutor(max_workers=max_threads)
        self.login_semaphore = threading.BoundedSemaphore(max_threads)
        self.upload_retry_semaphore = threading.BoundedSemaphore(max_threads)

        # Get max videos
        try:
            max_videos = int(self.entry_videos.get())
            if max_videos <= 0:
                raise ValueError
        except Exception:
            max_videos = 1

        # Reuse layout from previous run (or recalculate if needed)
        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
        except Exception:
            screen_w, screen_h = 1920, 1080

        gap = 6
        taskbar_h = 40
        usable_w = screen_w - (gap * 2)
        usable_h = (screen_h - taskbar_h) - (gap * 2)
        active_count = len(checked_items)

        cols = min(5, active_count)
        rows_layout = min(2, max(1, math.ceil(active_count / cols)))

        win_w = int((usable_w - gap * (cols - 1)) / cols)
        win_h = int((usable_h - gap * (rows_layout - 1)) / rows_layout)

        win_w = max(150, min(280, win_w))
        win_h = max(420, min(600, win_h))

        futures = []
        slot_idx = 0
        max_slots = cols * rows_layout

        self._log(f"\n[REPEAT] Starting repeat cycle... (checked: {len(checked_items)} accounts)")

        for idx, acc in enumerate(self.accounts, start=1):
            item_id = str(idx)
            if item_id not in checked_items:
                continue
            
            # Reset status to prepare for new cycle
            self.tree.set(item_id, "status", "WAIT")
            
            pos = slot_idx % max_slots
            col = pos % cols
            row = pos // cols
            x = gap + col * (win_w + gap)
            y = gap + row * (win_h + gap)
            win_pos = f"{x},{y}"
            win_size = f"{win_w},{win_h}"
            futures.append(self.executor.submit(self._worker_one, item_id, acc, win_pos, win_size, max_videos))
            slot_idx += 1

        def _repeat_waiter():
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception:
                    pass

            with self.failed_accounts_lock:
                failed_list = self.failed_accounts.copy()
                self.failed_accounts = []

            self.executor = None

            # Retry failed accounts
            if failed_list and not self.stop_event.is_set():
                if self._retry_round < 3:
                    self._retry_round += 1
                self._log(f"[RETRY] Retrying {len(failed_list)} failed accounts (round {self._retry_round}/3)...")
                self.root.after(1000, lambda fl=failed_list: self._retry_failed_accounts(fl, max_threads, max_videos))
                return

            self._clear_failed_log()

            # Schedule next repeat cycle
            if self._repeat_enabled and not self.stop_event.is_set():
                delay_ms = int(self._repeat_delay_sec * 1000)
                if delay_ms < 0:
                    delay_ms = 0

                def _repeat_again():
                    if self.stop_event.is_set():
                        return
                    self._repeat_after_id = None
                    self._do_repeat_cycle()

                self._repeat_after_id = self.root.after(delay_ms, _repeat_again)
                self._log(f"[REPEAT] Next cycle in {self._repeat_delay_sec:.0f} seconds...")

        threading.Thread(target=_repeat_waiter, daemon=True).start()

    def start_scan(self) -> None:
        if self.executor is not None:
            return

        try:
            max_threads = int(self.entry_threads.get())
            if max_threads <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Loi", "So luong phai > 0")
            return

        checked_items = [iid for iid in self.tree.get_children() if self.tree.set(iid, "chk") == "v"]
        if not checked_items:
            messagebox.showinfo("Thong bao", "Khong co profile nao duoc tick.")
            return

        self.stop_event.clear()
        self.executor = ThreadPoolExecutor(max_workers=max_threads)

        futures = []
        for idx, acc in enumerate(self.accounts, start=1):
            item_id = str(idx)
            if item_id not in checked_items:
                continue
            futures.append(self.executor.submit(self._scan_worker, item_id, acc))

        def _waiter():
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception:
                    pass
            self.executor = None

        threading.Thread(target=_waiter, daemon=True).start()

    def _scan_worker(self, item_id: str, acc: dict) -> None:
        if self.stop_event.is_set():
            return
        shorts_url = (acc.get("youtube") or "").strip()
        if not shorts_url:
            self._log(f"[{acc['uid']}] SCAN SKIP: No shorts URL")
            return
        self._set_status(item_id, "SCAN...")
        self._log(f"[{acc['uid']}] SCAN START")
        total, added = scan_shorts_for_email(
            acc["uid"],
            shorts_url,
            lambda: self.stop_event.is_set(),
            self._log,
        )
        self._set_status(item_id, f"SCAN OK ({added})")
        self._log(f"[{acc['uid']}] SCAN OK: added {added}, total {total}")

    def _retry_failed_accounts(self, failed_accounts: list, max_threads: int, max_videos: int) -> None:
        """Retry failed accounts with new threads"""
        if self.stop_event.is_set():
            return
        
        self._log(f"[RETRY] Retrying {len(failed_accounts)} failed accounts (max {max_threads} threads)...")
        
        self.executor = ThreadPoolExecutor(max_workers=max_threads)
        futures = []
        
        # Re-calculate layout for failed accounts
        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
        except Exception:
            screen_w, screen_h = 1920, 1080
        
        gap = 6  # Tight spacing between windows
        taskbar_h = 40  # Reserve space for taskbar
        usable_w = screen_w - (gap * 2)
        usable_h = (screen_h - taskbar_h) - (gap * 2)
        active_count = len(failed_accounts)
        
        # Fixed: 5 columns per row (5 profiles = 1 row, 10 profiles = 2 rows)
        cols = min(5, active_count)  # Max 5 per row
        rows_layout = max(1, (active_count + cols - 1) // cols)
        
        # Calculate window sizes
        win_w = int((usable_w - gap * (cols - 1)) / cols)
        win_h = int((usable_h - gap * (rows_layout - 1)) / rows_layout)
        
        # Compact windows: narrow width, optimal height
        win_w = max(150, min(280, win_w))  # Compact: 150-280px
        win_h = max(420, min(600, win_h))  # Height range: 420-600px
        
        for idx, (item_id, acc) in enumerate(failed_accounts):
            if self.stop_event.is_set():
                break
            pos = idx % (cols * rows_layout)
            col = pos % cols
            row = pos // cols
            x = gap + col * (win_w + gap)
            y = gap + row * (win_h + gap)
            retry_win_pos = f"{x},{y}"
            retry_win_size = f"{win_w},{win_h}"
            self._log(f"[RETRY] Submitting {acc.get('uid', '')} (item_id={item_id}) at position {retry_win_pos}")
            futures.append(self.executor.submit(self._worker_one, item_id, acc, retry_win_pos, retry_win_size, max_videos))
        
        def _retry_waiter():
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception:
                    pass
            self.executor = None
            with self.failed_accounts_lock:
                failed_list = self.failed_accounts.copy()
                self.failed_accounts = []
            if failed_list and not self.stop_event.is_set():
                if self._retry_round < 3:
                    self._retry_round += 1
                if self._retry_round <= 3:
                    self._log(f"[RETRY] Retrying {len(failed_list)} failed accounts (round {self._retry_round}/3)...")
                    self.root.after(1000, lambda fl=failed_list: self._retry_failed_accounts(fl, max_threads, max_videos))
                    return
            self._clear_failed_log()
            if self._repeat_enabled and not self.stop_event.is_set():
                delay_ms = int(self._repeat_delay_sec * 1000)
                if delay_ms < 0:
                    delay_ms = 0

                def _repeat_start():
                    if self.stop_event.is_set():
                        return
                    self._repeat_after_id = None
                    self.start_jobs()

                self._repeat_after_id = self.root.after(delay_ms, _repeat_start)
        
        threading.Thread(target=_retry_waiter, daemon=True).start()

    def _retry_failed_profile_accounts(self, failed_accounts: list, max_threads: int) -> None:
        if self.stop_event.is_set():
            return

        self._log(f"[PROFILE RETRY] Retrying {len(failed_accounts)} failed accounts (max {max_threads} threads)...")
        self.executor = ThreadPoolExecutor(max_workers=max_threads)
        futures = []

        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
        except Exception:
            screen_w, screen_h = 1920, 1080

        gap = 6
        taskbar_h = 40
        usable_w = screen_w - (gap * 2)
        usable_h = (screen_h - taskbar_h) - (gap * 2)
        active_count = len(failed_accounts)
        cols = min(5, active_count)
        rows_layout = max(1, (active_count + cols - 1) // cols)
        win_w = int((usable_w - gap * (cols - 1)) / cols)
        win_h = int((usable_h - gap * (rows_layout - 1)) / rows_layout)
        win_w = max(150, min(280, win_w))
        win_h = max(420, min(600, win_h))

        for idx, (item_id, acc) in enumerate(failed_accounts):
            if self.stop_event.is_set():
                break
            pos = idx % (cols * rows_layout)
            col = pos % cols
            row = pos // cols
            x = gap + col * (win_w + gap)
            y = gap + row * (win_h + gap)
            retry_win_pos = f"{x},{y}"
            retry_win_size = f"{win_w},{win_h}"
            self._log(f"[PROFILE RETRY] Submitting {acc.get('uid', '')} (item_id={item_id}) at position {retry_win_pos}")
            futures.append(self.executor.submit(self._profile_open_worker, item_id, acc, retry_win_pos, retry_win_size))

        def _retry_waiter():
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception:
                    pass
            self.executor = None
            with self.profile_failed_lock:
                failed_list = self.profile_failed_accounts.copy()
                self.profile_failed_accounts = []
            if failed_list and not self.stop_event.is_set():
                if self._profile_retry_round < 3:
                    self._profile_retry_round += 1
                    self._log(
                        f"[PROFILE RETRY] Retrying {len(failed_list)} failed accounts (round {self._profile_retry_round}/3)..."
                    )
                    self.root.after(1000, lambda fl=failed_list: self._retry_failed_profile_accounts(fl, max_threads))
                    return
            self._clear_profile_failed_log()

        threading.Thread(target=_retry_waiter, daemon=True).start()


    def _ensure_logged_in(self, item_id: str, acc: dict):
        with self.active_drivers_lock:
            info = self.active_drivers.get(item_id)
        if info and info.get("driver_path") and info.get("remote"):
            return info.get("driver_path"), info.get("remote"), info.get("profile_id")

        self._set_status(item_id, "CREATE...")
        ok_c = False
        data_c = {}
        msg_c = ""
        with self.create_lock:
            for attempt in range(3):
                ok_c, data_c, msg_c = create_profile(acc["uid"], acc["proxy"], SCOOPZ_URL)
                if ok_c:
                    break
                wait_s = 5 + attempt * 3
                self._set_status(item_id, f"CREATE RETRY {attempt+1}/3")
                self._log(f"[{acc['uid']}] CREATE ERR: {msg_c} | retry in {wait_s}s")
                time.sleep(wait_s)
        if not ok_c:
            self._set_status(item_id, f"CREATE ERR: {msg_c}")
            self._log(f"[{acc['uid']}] CREATE ERR: {msg_c}")
            self._record_failed(item_id, acc, f"CREATE ERR: {msg_c}")
            return None, None, None

        profile_id = None
        if isinstance(data_c, dict):
            profile_id = (data_c.get("data") or {}).get("id") or data_c.get("id") or data_c.get("profile_id")
        if not profile_id:
            self._set_status(item_id, "NO PROFILE ID")
            return None, None, None
        self.created_profiles.add(profile_id)

        self._set_status(item_id, "START...", profile_id=profile_id)
        ok_s, data_s, msg_s = start_profile(profile_id)
        if not ok_s:
            self._set_status(item_id, f"START ERR: {msg_s}")
            self._log(f"[{acc['uid']}] START ERR: {msg_s}")
            self._record_failed(item_id, acc, f"START ERR: {msg_s}")
            return None, None, None

        driver_path, remote = extract_driver_info(data_s)
        if not driver_path or not remote:
            self._set_status(item_id, "STARTED (no debug)")
            return None, None, None

        self._set_status(item_id, "LOGIN...")
        ok_login, err_login = login_scoopz(
            driver_path,
            remote,
            acc["uid"],
            acc["pass"],
            "",
            max_retries=3,
            keep_browser=True,
        )
        if not ok_login:
            status = self._format_login_error(err_login)
            self._set_status(item_id, status)
            self._log(f"[{acc['uid']}] {status}")
            self._record_failed(item_id, acc, status)
            return None, None, None

        self._set_status(item_id, "LOGIN OK")
        self._log(f"[{acc['uid']}] LOGIN OK")
        with self.active_drivers_lock:
            self.active_drivers[item_id] = {
                "profile_id": profile_id,
                "driver_path": driver_path,
                "remote": remote,
                "close_func": lambda: (close_profile(profile_id, 3), delete_profile(profile_id, 10)),
            }
        return driver_path, remote, profile_id

    def _login_only_worker(self, item_id: str, acc: dict) -> None:
        if self.stop_event.is_set():
            return
        self._ensure_logged_in(item_id, acc)

    def _upload_only_worker(self, item_id: str, acc: dict) -> None:
        if self.stop_event.is_set():
            return
        driver_path, remote, _ = self._ensure_logged_in(item_id, acc)
        if not driver_path or not remote:
            return
        download_started = threading.Event()
        def _idle_watchdog():
            if download_started.wait(timeout=30):
                return
            if self.stop_event.is_set():
                return
            self._set_status(item_id, "LOGIN OK (IDLE)")
            self._log(f"[{acc['uid']}] LOGIN OK (IDLE) - no download started")
            self._record_failed(item_id, acc, "LOGIN OK (IDLE)")
        threading.Thread(target=_idle_watchdog, daemon=True).start()
        success_count = 0
        safety_guard = 0
        max_videos = 1
        while success_count < max_videos:
            if self.stop_event.is_set():
                return
            safety_guard += 1
            if safety_guard > max_videos * 5:
                self._log(f"[{acc['uid']}] Too many skips, stop loop")
                return

            ok_next, row = get_next_unuploaded(acc["uid"])
            if not ok_next:
                self._log(f"[{acc['uid']}] {row.get('msg', 'No URL in CSV')}")
                return
            row_url = (row.get("url") or "").strip()
            row_id = (row.get("video_id") or "").strip()
            if not row_url:
                if row_id.startswith("http"):
                    row_url = row_id
                elif row_id:
                    row_url = f"https://www.youtube.com/shorts/{row_id}"
            if not row_url:
                self._log(f"[{acc['uid']}] No URL in CSV row")
                return

            self._set_status(item_id, "DOWNLOAD...")
            download_started.set()
            self._log(f"[{acc['uid']}] NEXT VIDEO: {row_id} | {row_url}")
            ok_dl, path_or_err, vid_id, title = download_one(
                acc["uid"],
                row_url,
                self._log_progress,
                cookie_path=COOKIES_FILE,
                timeout_s=300,
            )
            mark_id = vid_id or row_id
            if not ok_dl:
                err_text = str(path_or_err)
                lower = err_text.lower()
                is_skipped = (
                    "video skipped" in lower
                    or "private video" in lower
                    or "sign in if you've been granted access" in lower
                    or "sign in to confirm your age" in lower
                    or "age-restricted" in lower
                    or "age restricted" in lower
                )
                if is_skipped:
                    self._log(f"[{acc['uid']}] VIDEO UNAVAILABLE - AUTO SKIP")
                    try:
                        mark_uploaded(acc["uid"], mark_id)
                    except Exception:
                        pass
                    continue
                self._log(f"[{acc['uid']}] DOWNLOAD ERR: {err_text}")
                if "timeout" in lower or "timed out" in lower:
                    self._record_failed(item_id, acc, f"DOWNLOAD ERR: {err_text}")
                return

            caption = title or ""
            ok_p, drv, up_status, up_msg = upload_prepare(
                driver_path,
                remote,
                path_or_err,
                caption,
                lambda: self.stop_event.is_set(),
                self._log,
                acc.get("uid", ""),
                max_total_s=360,
                file_dialog_semaphore=self.file_dialog_semaphore,
            )
            if not ok_p:
                status_text = f"UPLOAD LOI: {up_status}" if up_status in ("select_not_found", "select_click_error") else f"UPLOAD ERR: {up_msg or up_status}"
                self._set_status(item_id, status_text)
                self._log(f"[{acc['uid']}] {status_text}")
                if up_status in ("select_not_found", "select_click_error"):
                    self._record_failed(item_id, acc, f"UPLOAD {up_status}")
                elif up_status == "timeout":
                    self._record_failed(item_id, acc, f"UPLOAD ERR: {up_msg or up_status}")
                return

            self._set_status(item_id, "POSTING...")
            st, msg, purl, foll = upload_post_async(drv, self._log, max_total_s=180, post_button_semaphore=self.post_button_semaphore)
            if st == "success":
                try:
                    mark_uploaded(acc["uid"], mark_id)
                except Exception:
                    pass
                self._set_profile_info(item_id, purl, foll)
                self._set_status(item_id, "UPLOAD OK")
                self._log(f"[{acc['uid']}] UPLOAD OK")
                self._delete_uploaded_video(path_or_err, acc["uid"])
                success_count += 1
            else:
                err_text = msg or st
                status_text = "UPLOAD LOI" if "Select video not found" in (err_text or "") else f"UPLOAD ERR: {err_text}"
                self._set_status(item_id, status_text)
                self._log(f"[{acc['uid']}] UPLOAD ERR: {err_text}")
                if st == "timeout":
                    self._record_failed(item_id, acc, f"POST ERR: {err_text}")
                return

    def _follow_only_worker(self, item_id: str, acc: dict) -> None:
        if self.stop_event.is_set():
            return
        driver_path, remote, _ = self._ensure_logged_in(item_id, acc)
        if not driver_path or not remote:
            return
        followers, profile_url = fetch_followers(driver_path, remote, self._log)
        if followers is not None:
            self._log(f"[{acc['uid']}] FOLLOWERS: {followers}")
            self._set_profile_info(item_id, profile_url, followers)
            self._set_status(item_id, "FOLLOW OK")
        else:
            self._set_status(item_id, "FOLLOW ERR")
            self._log(f"[{acc['uid']}] FOLLOW ERR")

    def _profile_open_worker(self, item_id: str, acc: dict, win_pos: str, win_size: str) -> None:
        sem = self.profile_semaphore
        if sem:
            sem.acquire()
        profile_id = None
        try:
            if self.stop_event.is_set():
                return
            yt_url = (acc.get("youtube") or "").strip()
            if not yt_url:
                self._set_profile_status(item_id, "YTB ERR: Thieu link")
                self._log(f"[{acc.get('uid','')}] YTB ERR: Thieu link YouTube")
                self._record_profile_failed(item_id, acc, "YTB ERR: Thieu link")
                return
            self._ensure_video_folder(acc.get("uid", ""))
            cached = self._load_profile_assets(acc.get("uid", ""))
            name = (cached.get("name") or "").strip()
            username = (cached.get("username") or "").strip()
            avatar_path = (cached.get("avatar_path") or "").strip()
            if name and username and avatar_path and os.path.exists(avatar_path):
                self._set_profile_status(item_id, "YTB CACHED")
                self._log(f"[{acc['uid']}] YTB CACHED")
            else:
                self._set_profile_status(item_id, "YTB FETCH...")
                self._log(f"[{acc['uid']}] YTB FETCH START: {yt_url}")
                fetched_name, fetched_username, avatar_path = fetch_youtube_profile_assets_local(yt_url, self._log)
                if not avatar_path:
                    self._set_profile_status(item_id, "YTB ERR: Empty")
                    self._log(f"[{acc['uid']}] YTB ERR: Empty")
                    self._record_profile_failed(item_id, acc, "YTB ERR: Empty")
                    return
                name = fetched_name
                username = fetched_username
                self._save_profile_assets(acc["uid"], fetched_name, fetched_username, avatar_path)
                self._set_profile_status(item_id, "YTB OK")
                self._log(f"[{acc['uid']}] YTB OK")
            self._log(f"[{acc['uid']}] START PROFILE")
            self._set_profile_status(item_id, "CREATE...")
            ok_c = False
            data_c = {}
            msg_c = ""
            with self.create_lock:
                for attempt in range(3):
                    ok_c, data_c, msg_c = create_profile(acc["uid"], acc["proxy"], SCOOPZ_URL)
                    if ok_c:
                        break
                    wait_s = 5 + attempt * 3
                    self._set_profile_status(item_id, f"CREATE RETRY {attempt+1}/3")
                    self._log(f"[{acc['uid']}] CREATE ERR: {msg_c} | retry in {wait_s}s")
                    time.sleep(wait_s)
            if not ok_c:
                self._set_profile_status(item_id, f"CREATE ERR: {msg_c}")
                self._log(f"[{acc['uid']}] CREATE ERR: {msg_c}")
                self._record_profile_failed(item_id, acc, f"CREATE ERR: {msg_c}")
                return

            if isinstance(data_c, dict):
                profile_id = (data_c.get("data") or {}).get("id") or data_c.get("id") or data_c.get("profile_id")
            if not profile_id:
                self._set_profile_status(item_id, "NO PROFILE ID")
                self._log(f"[{acc['uid']}] NO PROFILE ID")
                self._record_profile_failed(item_id, acc, "NO PROFILE ID")
                return
            self.profile_created_profiles.add(profile_id)

            self._set_profile_status(item_id, "START...")
            ok_s, data_s, msg_s = start_profile(profile_id, win_pos=win_pos, win_size=win_size)
            if not ok_s:
                self._set_profile_status(item_id, f"START ERR: {msg_s}")
                self._log(f"[{acc['uid']}] START ERR: {msg_s}")
                self._record_profile_failed(item_id, acc, f"START ERR: {msg_s}")
                return

            driver_path, remote = extract_driver_info(data_s)
            status = "STARTED" if driver_path and remote else "STARTED (no debug)"
            self._set_profile_status(item_id, status)
            self._log(f"[{acc['uid']}] START OK")

            if not driver_path or not remote:
                self._record_profile_failed(item_id, acc, "STARTED (no debug)")
                return

            self._set_profile_status(item_id, "LOGIN...")
            self._log(f"[{acc['uid']}] LOGIN START")
            ok_login, err_login = login_scoopz(
                driver_path,
                remote,
                acc["uid"],
                acc["pass"],
                "",
                max_retries=3,
                keep_browser=True,
            )
            if not ok_login:
                status = self._format_login_error(err_login)
                self._set_profile_status(item_id, status)
                self._log(f"[{acc['uid']}] {status}")
                self._record_profile_failed(item_id, acc, status)
                return

            if self.stop_event.is_set():
                return

            self._set_profile_status(item_id, "LOGIN OK")
            self._log(f"[{acc['uid']}] LOGIN OK (PROFILE)")

            self._set_profile_status(item_id, "OPEN PROFILE...")
            self._set_profile_status(item_id, "WAIT UPDATE...")
            ok_p = False
            err_p = ""
            with self.profile_update_lock:
                for attempt in range(1, 4):
                    if self.stop_event.is_set():
                        return
                    self._set_profile_status(item_id, f"OPEN PROFILE... ({attempt}/3)")
                    ok_p, err_p = open_profile_in_scoopz(
                        driver_path,
                        remote,
                        avatar_path,
                        name,
                        username,
                        logger=self._log,
                        max_retries=3,
                    )
                    if ok_p:
                        break
                    retryable = (
                        "cannot connect to chrome" in (err_p or "").lower()
                        or "profile link not found" in (err_p or "").lower()
                        or "profile page load timeout" in (err_p or "").lower()
                    )
                    if not retryable:
                        break
                    wait_s = 2 + attempt * 2
                    self._log(f"[{acc['uid']}] PROFILE RETRY {attempt}/3 in {wait_s}s: {err_p}")
                    time.sleep(wait_s)
            if not ok_p:
                self._set_profile_status(item_id, f"PROFILE ERR: {err_p}")
                self._log(f"[{acc['uid']}] PROFILE ERR: {err_p}")
                self._record_profile_failed(item_id, acc, f"PROFILE ERR: {err_p}")
                return
            self._set_profile_status(item_id, "PROFILE OPENED")
            self._log(f"[{acc['uid']}] PROFILE OPENED")

            yt_url = (acc.get("youtube") or "").strip()
            if not yt_url:
                self._set_profile_status(item_id, "YTB ERR: Thieu link")
                self._log(f"[{acc.get('uid','')}] YTB ERR: Thieu link YouTube")
                self._record_profile_failed(item_id, acc, "YTB ERR: Thieu link")
                return
            self._ensure_video_folder(acc.get("uid", ""))
            cached = self._load_profile_assets(acc.get("uid", ""))
            name = (cached.get("name") or "").strip()
            username = (cached.get("username") or "").strip()
            avatar_path = (cached.get("avatar_path") or "").strip()
            if name and username and avatar_path and os.path.exists(avatar_path):
                self._set_profile_status(item_id, "YTB CACHED")
                self._log(f"[{acc['uid']}] YTB CACHED")
            else:
                self._set_profile_status(item_id, "YTB FETCH...")
                self._log(f"[{acc['uid']}] YTB FETCH START: {yt_url}")
                fetched_name, fetched_username, avatar_path = fetch_youtube_profile_assets_local(yt_url, self._log)
                if not avatar_path:
                    self._set_profile_status(item_id, "YTB ERR: Empty")
                    self._log(f"[{acc['uid']}] YTB ERR: Empty")
                    self._record_profile_failed(item_id, acc, "YTB ERR: Empty")
                    return
                name = fetched_name
                username = fetched_username
                self._save_profile_assets(acc["uid"], fetched_name, fetched_username, avatar_path)
                self._set_profile_status(item_id, "YTB OK")
                self._log(f"[{acc['uid']}] YTB OK")

            with self.profile_active_drivers_lock:
                self.profile_active_drivers[item_id] = {
                    "profile_id": profile_id,
                    "driver_path": driver_path,
                    "remote": remote,
                    "close_func": lambda: (close_profile(profile_id, 3), delete_profile(profile_id, 10)),
                }
            self._set_profile_status(item_id, "DONE")
            self._log(f"[{acc['uid']}] PROFILE DONE")
        finally:
            if profile_id:
                try:
                    close_profile(profile_id, 3)
                except Exception:
                    pass
                try:
                    delete_profile(profile_id, 10)
                except Exception:
                    pass
                with self.profile_active_drivers_lock:
                    self.profile_active_drivers.pop(item_id, None)
                try:
                    self.profile_created_profiles.discard(profile_id)
                except Exception:
                    pass
            if sem:
                sem.release()

    def stop_jobs(self) -> None:
        self.stop_event.set()
        if self._repeat_after_id:
            try:
                self.root.after_cancel(self._repeat_after_id)
            except Exception:
                pass
            self._repeat_after_id = None
        with self.failed_accounts_lock:
            self.failed_accounts = []
        self._clear_failed_log()
        with self.profile_failed_lock:
            self.profile_failed_accounts = []
        self._clear_profile_failed_log()
        if self.executor is not None:
            try:
                self.executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            self.executor = None
        
        # Clean up active drivers
        with self.active_drivers_lock:
            for driver_info in self.active_drivers.values():
                try:
                    if driver_info and "close_func" in driver_info:
                        driver_info["close_func"]()
                except Exception:
                    pass
            self.active_drivers.clear()
        with self.profile_active_drivers_lock:
            for driver_info in self.profile_active_drivers.values():
                try:
                    if driver_info and "close_func" in driver_info:
                        driver_info["close_func"]()
                except Exception:
                    pass
            self.profile_active_drivers.clear()
        
        with self.active_lock:
            ids = list(self.active_profiles.values())
            self.active_profiles.clear()
        ids.extend(list(self.created_profiles))
        self.created_profiles.clear()
        ids.extend(list(self.profile_created_profiles))
        self.profile_created_profiles.clear()
        ids = list({pid for pid in ids if pid})
        for pid in ids:
            threading.Thread(
                target=lambda p=pid: (close_profile(p, 3), delete_profile(p, 10)),
                daemon=True,
            ).start()

    def reload_app(self) -> None:
        self.stop_jobs()
        exe = sys.executable
        script = os.path.abspath(__file__)
        try:
            subprocess.Popen([exe, script], close_fds=True)
        except Exception as e:
            try:
                self._log(f"[RELOAD] ERR: {e}")
            except Exception:
                pass
        try:
            self.root.after(200, self.root.destroy)
        except Exception:
            pass

    def _worker_one(self, item_id: str, acc: dict, win_pos: str, win_size: str, max_videos: int) -> None:
        if self.stop_event.is_set():
            return

        def _restart_profile() -> tuple:
            try:
                self._set_status(item_id, "RESTART...")
                close_profile(profile_id, 3)
                ok_s, data_s, msg_s = start_profile(profile_id, win_pos=win_pos, win_size=win_size)
                if not ok_s:
                    self._set_status(item_id, f"RESTART ERR: {msg_s}")
                    self._log(f"[{acc['uid']}] RESTART ERR: {msg_s}")
                    return None, None
                drv_path, dbg_addr = extract_driver_info(data_s)
                if not drv_path or not dbg_addr:
                    self._set_status(item_id, "RESTART NO DEBUG", profile_id=profile_id)
                    return None, None
                self._set_status(item_id, "RELOGIN...")
                ok_login, err_login = login_scoopz(
                    drv_path,
                    dbg_addr,
                    acc["uid"],
                    acc["pass"],
                    "",
                    max_retries=2,
                    keep_browser=True,
                )
                if not ok_login:
                    status = self._format_login_error(err_login)
                    if status == "SAI PASS":
                        self._set_status(item_id, status)
                        self._log(f"[{acc['uid']}] {status}")
                    else:
                        self._set_status(item_id, f"RELOGIN ERR: {err_login}")
                        self._log(f"[{acc['uid']}] RELOGIN ERR: {err_login}")
                    return None, None
                self._set_status(item_id, "RESTART OK", profile_id=profile_id)
                return drv_path, dbg_addr
            except Exception as e:
                self._set_status(item_id, f"RESTART ERR: {e}")
                self._log(f"[{acc['uid']}] RESTART ERR: {e}")
                return None, None

        def _extract_video_id(text: str) -> str:
            val = (text or "").strip()
            if not val:
                return ""
            if "shorts/" in val:
                return val.split("shorts/", 1)[1].split("?", 1)[0].strip("/")
            if "watch?v=" in val:
                return val.split("watch?v=", 1)[1].split("&", 1)[0]
            return ""

        self._log(f"[{acc['uid']}] START")
        self._set_status(item_id, "CREATE...")
        ok_c = False
        data_c = {}
        msg_c = ""
        with self.create_lock:
            for attempt in range(3):
                ok_c, data_c, msg_c = create_profile(acc["uid"], acc["proxy"], SCOOPZ_URL)
                if ok_c:
                    break
                wait_s = 5 + attempt * 3
                self._set_status(item_id, f"CREATE RETRY {attempt+1}/3")
                self._log(f"[{acc['uid']}] CREATE ERR: {msg_c} | retry in {wait_s}s")
                time.sleep(wait_s)
        if not ok_c:
            self._set_status(item_id, f"CREATE ERR: {msg_c}")
            self._log(f"[{acc['uid']}] CREATE ERR: {msg_c}")
            self._record_failed(item_id, acc, f"CREATE ERR: {msg_c}")
            return

        profile_id = None
        if isinstance(data_c, dict):
            profile_id = (data_c.get("data") or {}).get("id") or data_c.get("id") or data_c.get("profile_id")
        if not profile_id:
            self._set_status(item_id, "NO PROFILE ID")
            self._log(f"[{acc['uid']}] NO PROFILE ID")
            self._record_failed(item_id, acc, "NO PROFILE ID")
            return
        self.created_profiles.add(profile_id)

        self._set_status(item_id, "START...", profile_id=profile_id)
        ok_s, data_s, msg_s = start_profile(profile_id, win_pos=win_pos, win_size=win_size)
        if not ok_s:
            self._set_status(item_id, f"START ERR: {msg_s}")
            self._log(f"[{acc['uid']}] START ERR: {msg_s}")
            self._record_failed(item_id, acc, f"START ERR: {msg_s}")
            return

        with self.active_lock:
            self.active_profiles[item_id] = profile_id
        driver_path, remote = extract_driver_info(data_s)
        status = "STARTED" if driver_path and remote else "STARTED (no debug)"
        self._set_status(item_id, status, profile_id=profile_id)
        self._log(f"[{acc['uid']}] START OK")

        if driver_path and remote:
            self._set_status(item_id, "LOGIN...")
            self._log(f"[{acc['uid']}] LOGIN START")
            ok_login, err_login = login_scoopz(
                driver_path,
                remote,
                acc["uid"],
                acc["pass"],
                "",
                max_retries=3,
                keep_browser=True,
            )
            if ok_login:
                self._set_status(item_id, "LOGIN OK")
                self._log(f"[{acc['uid']}] LOGIN OK")
                download_started = threading.Event()
                def _idle_watchdog():
                    if download_started.wait(timeout=30):
                        return
                    if self.stop_event.is_set():
                        return
                    self._set_status(item_id, "LOGIN OK (IDLE)")
                    self._log(f"[{acc['uid']}] LOGIN OK (IDLE) - no download started")
                    self._record_failed(item_id, acc, "LOGIN OK (IDLE)")
                threading.Thread(target=_idle_watchdog, daemon=True).start()
                success_count = 0
                safety_guard = 0
                restart_attempts = 0
                while success_count < max_videos:
                    if self.stop_event.is_set():
                        break
                    safety_guard += 1
                    if safety_guard > max_videos * 5:
                        self._log(f"[{acc['uid']}] Too many skips, stop loop")
                        break
                    
                    # Smart delay before next video
                    self.operation_delayer.delay_before_download(acc["uid"], self._log_progress)
                    
                    ok_next, row = get_next_unuploaded(acc["uid"])
                    if not ok_next:
                        self._log(f"[{acc['uid']}] {row.get('msg', 'No URL in CSV')}")
                        break
                    row_url = (row.get("url") or "").strip()
                    row_id = (row.get("video_id") or "").strip()
                    if not row_url:
                        if row_id.startswith("http"):
                            row_url = row_id
                        elif row_id:
                            row_url = f"https://www.youtube.com/shorts/{row_id}"
                    if not row_url:
                        self._log(f"[{acc['uid']}] No URL in CSV row")
                        break
                    download_started.set()
                    self._log(f"[{acc['uid']}] NEXT VIDEO: {row_id} | {row_url}")
                    self._set_status(item_id, f"DOWNLOAD {success_count+1}/{max_videos}...")
                    self._log(f"[{acc['uid']}] DOWNLOAD START: {row_url}")
                    retry_dl = 0
                    path_or_err = ""
                    vid_id = ""
                    title = ""
                    ok_dl = False
                    skip_current = False
                    while True:
                        ok_dl, path_or_err, vid_id, title = download_one(
                            acc["uid"],
                            row_url,
                            self._log_progress,
                            cookie_path=COOKIES_FILE,
                            timeout_s=300,
                        )
                        if ok_dl:
                            break
                        err_text = str(path_or_err)
                        lower = err_text.lower()
                        is_restricted = (
                            "video restricted" in lower
                            or "members-only" in lower
                            or "members only" in lower
                            or "join this channel" in lower
                            or "premium only" in lower
                            or "membership required" in lower
                        )
                        is_skipped = (
                            "video skipped" in lower
                            or "private video" in lower
                            or "sign in if you've been granted access" in lower
                            or "sign in to confirm your age" in lower
                            or "age-restricted" in lower
                            or "age restricted" in lower
                        )
                        
                        if is_skipped:
                            self._log(f"[{acc['uid']}] VIDEO UNAVAILABLE - AUTO SKIP")
                            # Mark as uploaded so it's skipped in future runs
                            mark_id = vid_id or row_id or _extract_video_id(row_url)
                            try:
                                mark_uploaded(acc["uid"], mark_id)
                            except Exception as e:
                                self._log(f"[{acc['uid']}] Could not mark video: {e}")
                            skip_current = True
                            break
                        if "timeout" in lower or "timed out" in lower:
                            self._set_status(item_id, f"DOWNLOAD ERR: {err_text}")
                            self._log(f"[{acc['uid']}] DOWNLOAD ERR: {err_text}")
                            self._record_failed(item_id, acc, f"DOWNLOAD ERR: {err_text}")
                            return
                        
                        if is_restricted and retry_dl < 1:
                            retry_dl += 1
                            self._log(f"[{acc['uid']}] DOWNLOAD RETRY (restricted): {row_url}")
                            self.operation_delayer.delay_on_error(acc['uid'], "restricted_video", self._log_progress)
                            continue
                        if is_restricted and retry_dl == 1:
                            # Relogin disabled - skip to next video
                            self._log(f"[{acc['uid']}] VIDEO RESTRICTED - SKIP (no relogin): {err_text}")
                            self.error_logger.log_download_error(acc['uid'], row_url, f"Video restricted - {err_text}")
                            break
                        if is_restricted and retry_dl >= 2:
                            self._log(f"[{acc['uid']}] VIDEO RESTRICTED - SKIP: {err_text}")
                            self.error_logger.log_download_error(acc['uid'], row_url, f"Video restricted - {err_text}")
                            break
                        break

                    mark_id = vid_id or row_id or _extract_video_id(row_url)
                    if skip_current:
                        continue
                    if ok_dl:
                        if vid_id and title:
                            try:
                                update_title_if_empty(acc["uid"], vid_id, title)
                            except Exception:
                                pass
                        self._set_status(item_id, f"DOWNLOAD OK {success_count+1}/{max_videos}")
                        self._log(f"[{acc['uid']}] DOWNLOAD OK")
                        caption = title or ""
                        
                        # Smart delay before upload
                        self.operation_delayer.delay_before_upload(acc["uid"], self._log_progress)
                        
                        # Use semaphore to limit concurrent uploads
                        with self.upload_retry_semaphore:
                            ok_p = False
                            drv = None
                            up_status = ""
                            up_msg = ""
                            
                            # Retry with exponential backoff
                            for attempt in range(3):
                                if self.stop_event.is_set():
                                    break
                                    
                                # Use per-driver lock to prevent file dialog conflicts
                                driver_key = f"{acc['uid']}_upload"
                                try:
                                    with self.dialog_lock_pool.acquire(driver_key, timeout=60):
                                        ok_p, drv, up_status, up_msg = upload_prepare(
                                            driver_path,
                                            remote,
                                            path_or_err,
                                            caption,
                                            lambda: self.stop_event.is_set(),
                                            self._log,
                                            acc.get("uid", ""),
                                            max_total_s=360,
                                            file_dialog_semaphore=self.file_dialog_semaphore,
                                        )
                                except Exception as e:
                                    up_msg = f"Lock timeout: {e}"
                                    self._log(f"[{acc['uid']}] Upload lock error: {e}")
                                
                                if ok_p:
                                    break
                                
                                # Retry on dialog lock timeout
                                if up_status == "dialog_lock_timeout":
                                    if attempt < 2:
                                        wait_time = 5  # Wait 5s before retrying dialog lock
                                        self._log(f"[{acc['uid']}] Dialog lock timeout, retry in {wait_time}s...")
                                        time.sleep(wait_time)
                                        continue
                                    else:
                                        break
                                
                                # Don't retry certain errors
                                if up_status not in ("select_not_found", "select_click_error"):
                                    break
                                
                                # Backoff before retry
                                if attempt < 2:
                                    wait_time = min(2 ** attempt, 10)  # 2s, 4s
                                    self._log(f"[{acc['uid']}] Upload retry in {wait_time}s...")
                                    time.sleep(wait_time)
                            
                            if not ok_p and up_status in ("select_not_found", "select_click_error"):
                                # Upload select not found - add to retry queue and break
                                self._set_status(item_id, f"UPLOAD LOI: {up_status}")
                                self._log(f"[{acc['uid']}] Upload {up_status} - retry this account")
                                self._record_failed(item_id, acc, f"UPLOAD {up_status}")
                                break

                        if not ok_p:
                            if up_status == "account_blocked" or "Kh?ng th?y tr?ng th?i Uploading/Uploaded" in (up_msg or ""):
                                self._set_status(item_id, "ACCOUNT BLOCKED")
                                self._log(f"[{acc['uid']}] ACCOUNT BLOCKED - retry this account")
                                self.error_logger.log_upload_error(acc['uid'], path_or_err, "Account blocked")
                                self._record_failed(item_id, acc, "ACCOUNT BLOCKED")
                                break
                            else:
                                self._set_status(item_id, f"UPLOAD ERR: {up_msg or up_status}")
                                self._log(f"[{acc['uid']}] UPLOAD ERR: {up_msg or up_status}")
                                self.error_logger.log_upload_error(acc['uid'], path_or_err, up_msg or up_status)
                                self._record_failed(item_id, acc, f"UPLOAD ERR: {up_msg or up_status}")
                                # Other upload errors - skip without retry
                                break
                        else:
                            self._set_status(item_id, f"POSTING {success_count+1}/{max_videos}...")
                            st, msg, purl, foll = upload_post_async(drv, self._log, max_total_s=180, post_button_semaphore=self.post_button_semaphore)
                            if st == "success":
                                try:
                                    mark_uploaded(acc["uid"], mark_id)
                                except Exception:
                                    pass
                                self._set_profile_info(item_id, purl, foll)
                                self._set_status(item_id, "UPLOAD OK")
                                self._log(f"[{acc['uid']}] UPLOAD OK")
                                self._delete_uploaded_video(path_or_err, acc["uid"])
                                self.error_logger.log_success(
                                    acc['uid'],
                                    "UPLOAD",
                                    f"Video {success_count+1}/{max_videos} posted successfully",
                                )
                                success_count += 1
                            else:
                                err_text = msg or st
                                status_text = "UPLOAD LOI" if "Select video not found" in (err_text or "") else f"UPLOAD ERR: {err_text}"
                                self._set_status(item_id, status_text)
                                self._log(f"[{acc['uid']}] UPLOAD ERR: {err_text}")
                                self.error_logger.log_upload_error(acc['uid'], path_or_err, err_text)
                                self._record_failed(item_id, acc, f"UPLOAD ERR: {err_text}")
                                break
                    else:
                        err_text = str(path_or_err)
                        self._set_status(item_id, f"DOWNLOAD ERR: {err_text}")
                        self._log(f"[{acc['uid']}] DOWNLOAD ERR: {err_text}")
                        self.error_logger.log_download_error(acc['uid'], row_url, err_text)
                        lower = err_text.lower()
                        if (
                            "video unavailable" in lower
                            or "removed by the uploader" in lower
                            or "members-only" in lower
                            or "members only" in lower
                            or "join this channel" in lower
                            or "video skipped" in lower
                            or "private video" in lower
                            or "sign in if you've been granted access" in lower
                        ):
                            try:
                                mark_uploaded(acc["uid"], mark_id)
                            except Exception:
                                pass
                            continue
                        # Relogin disabled - skip video
                        break
            else:
                status = self._format_login_error(err_login)
                self._set_status(item_id, status)
                self._log(f"[{acc['uid']}] {status}")
                # Track failed account for retry
                self._record_failed(item_id, acc, status)
            try:
                if profile_id:
                    close_profile(profile_id, 3)
                    delete_profile(profile_id, 10)
            except Exception:
                pass
        try:
            with self.active_lock:
                self.active_profiles.pop(item_id, None)
        except Exception:
            pass


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
