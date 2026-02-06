# -*- coding: utf-8 -*-

import os
import sys
import threading
import json
import csv
import subprocess
import shutil
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
from config import SCOOPZ_URL, SCOOPZ_UPLOAD_URL, COOKIES_FILE, COOKIES_FILE_FALLBACK
from yt_simple_download import download_one
from fb_simple_download import download_one_facebook
from shorts_csv_store import get_next_unuploaded, mark_uploaded, update_title_if_empty
from scoopz_uploader import upload_prepare, upload_post_async
from followers_fetcher import fetch_followers
from profile_updater import fetch_youtube_profile_assets_local, fetch_facebook_profile_assets_local, update_profile_from_assets
from shorts_scanner import scan_shorts_for_email
from fb_reels_scanner import scan_facebook_reels_for_email, scan_facebook_reels_multi
from threading_utils import ResourcePool, RetryHelper, ThreadSafeCounter
from logging_config import initialize_logger
from rate_limiter import initialize_rate_limiting, get_operation_delayer
from operation_orchestrator import initialize_orchestrator


ACCOUNTS = []
PROFILE_BATCH_SIZE = 100
PROFILE_BATCH_PAUSE_SEC = 300
PROFILE_BATCH_STAGGER_SEC = 0.15
PROFILE_BATCH_PAUSE_CHECK_SEC = 2.0
FIXED_SCAN_FOLDERS = {
    "alfreorasoly26_at_hotmail_com",
    "driterlaruu_at_hotmail_com",
    "dwengahuiju_at_hotmail_com",
    "eduanyadzia_at_hotmail_com",
    "janioanshaa11_at_hotmail_com",
    "opendauria_at_hotmail_com",
    "shueybrwamo_at_hotmail_com",
    "jassornivar_at_hotmail_com",
    "navudagishan_at_hotmail_com",
    "ussmanentang_at_hotmail_com",
    "yhamirchhaya_at_hotmail_com",
    "kaisynadena_at_hotmail_com",
    "nkhusikpatsa_at_hotmail_com",
    "tybenduviol_at_hotmail_com",
    "adlaheok_at_hotmail_com",
    "norbilagami_at_hotmail_com",
    "tekanalenart_at_hotmail_com",
    "utasirme_at_hotmail_com",
    "ibadetmorsin9684_at_hotmail_com",
    "csutatabong_at_hotmail_com",
    "curagariba_at_hotmail_com",
}
FIXED_SCAN_EMAILS = {
    f.replace("_at_", "@").replace("_", ".") for f in FIXED_SCAN_FOLDERS
}


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("GPM Multi-Profile Test")
        self.root.geometry("1100x520")
        self._accounts_file = os.path.join(_THIS_DIR, "accounts_cache.json")
        self._profile_accounts_file = os.path.join(_THIS_DIR, "profile_accounts_cache.json")
        self._fb_accounts_file = os.path.join(_THIS_DIR, "fb_accounts_cache.json")
        self._fb_profile_accounts_file = os.path.join(_THIS_DIR, "fb_profile_accounts_cache.json")
        self._extra_proxy_file = os.path.join(_THIS_DIR, "extra_proxies.txt")
        
        # Initialize logger
        log_dir = os.path.join(_THIS_DIR, "logs")
        self.error_logger = initialize_logger(log_dir)
        self.error_logger.log_info("SYSTEM", "START", "Application started")
        
        # Initialize orchestrator with CONSERVATIVE mode
        # This coordinates all operations: login delays, sequential downloads, serial uploads
        self.orchestrator = initialize_orchestrator("conservative", logger=self.error_logger.main_logger.info)
        
        # Initialize rate limiter with conservative strategy
        initialize_rate_limiting("conservative")
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
        self.profile_paths = {}
        self.profile_paths_lock = threading.Lock()
        self.profile_paths_used = set()
        self._gpm_cleanup_count = 0
        self._gpm_cleanup_lock = threading.Lock()
        self._gpm_cleanup_running = False
        self.profile_created_profiles = set()
        self._upload_queue_lock = threading.Lock()
        self._upload_queue_cond = threading.Condition(self._upload_queue_lock)
        self._upload_queue = []
        self._upload_queue_seq = 0
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
        self._fb_dragging = False
        self._fb_drag_start = None
        self._fb_profile_dragging = False
        self._fb_profile_drag_start = None
        self._extra_proxies = []
        self._extra_proxy_idx = 0
        self._extra_proxy_lock = threading.Lock()
        self._cell_editor = None
        self.repeat_var = tk.BooleanVar(value=False)
        self._repeat_after_id = None
        self._repeat_enabled = False
        self._repeat_delay_sec = 0
        self._fixed_threads = None
        self._retry_round = 0
        self._profile_retry_round = 0
        self._profile_batch_running = False
        self._run_counts = {
            "upload": {"done": 0, "total": 0, "emails": set()},
            "profile": {"done": 0, "total": 0, "emails": set()},
            "fb": {"done": 0, "total": 0, "emails": set()},
            "fb_profile": {"done": 0, "total": 0, "emails": set()},
        }
        self._run_counts_lock = threading.Lock()
        self._batch_pause_lock = threading.Lock()
        self._batch_pause_state = {
            "YTB": {"started": 0, "release_at": 0.0},
            "FB": {"started": 0, "release_at": 0.0},
        }
        self._resume_pending = {
            "upload": set(),
            "profile": set(),
            "fb": set(),
            "fb_profile": set(),
        }
        self._count_var = tk.StringVar(value="Total: 0")
        self._profile_count_var = tk.StringVar(value="Total Profile: 0")
        self._fb_count_var = tk.StringVar(value="Total FB: 0")
        self._fb_profile_count_var = tk.StringVar(value="Total FB Profile: 0")
        self._follow_sort_after_id = None
        self._job_item_email_map = {}
        self._job_item_email_lock = threading.Lock()
        self._transient_statuses = {
            "START...",
            "STARTED",
            "STARTED (no debug)",
            "DOWNLOAD...",
            "DOWNLOAD OK",
            "POSTING...",
            "LOGIN...",
            "RESTART...",
        }

        self._build_ui()
        self._load_extra_proxy_list()
        self.accounts = self._load_accounts_cache() or ACCOUNTS
        self._load_rows()
        self.profile_accounts = self._load_profile_accounts_cache()
        self._load_profile_rows()
        self.fb_accounts = self._load_fb_accounts_cache()
        self._load_fb_rows()
        self.fb_profile_accounts = self._load_fb_profile_accounts_cache()
        self._load_fb_profile_rows()
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

        self.chk_repeat = ttk.Checkbutton(top, text="Lặp lại", variable=self.repeat_var)
        self.chk_repeat.pack(side="left", padx=(0, 6))
        ttk.Label(top, text="Delay (min):").pack(side="left")
        self.entry_repeat_delay = ttk.Entry(top, width=6)
        self.entry_repeat_delay.insert(0, "5")
        self.entry_repeat_delay.pack(side="left", padx=(5, 15))

        top2 = ttk.Frame(self.root)
        top2.pack(fill="x", padx=8, pady=(0, 6))

        ttk.Label(top2, text="GPM Path:").pack(side="left")
        self.entry_gpm_path = ttk.Entry(top2, width=24)
        self.entry_gpm_path.insert(0, r"C:\GPM")
        self.entry_gpm_path.pack(side="left", padx=(5, 15))

        self._search_placeholder = "Tìm email..."
        self.entry_search_email = ttk.Entry(top2, width=28)
        self.entry_search_email.insert(0, self._search_placeholder)
        self.entry_search_email.pack(side="left", padx=(0, 6))
        try:
            self.entry_search_email.configure(foreground="gray")
        except Exception:
            pass
        self.entry_search_email.bind("<FocusIn>", self._search_focus_in)
        self.entry_search_email.bind("<FocusOut>", self._search_focus_out)
        self.btn_search_email = ttk.Button(top2, text="FIND", command=self._search_email)
        self.btn_search_email.pack(side="left", padx=(0, 12))
        self._sort_state = {}
        self.btn_sort_follow_all = ttk.Button(top2, text="SORT FOLLOW ALL", command=self._toggle_followers_sort_all)
        self.btn_sort_follow_all.pack(side="left", padx=(0, 12))

        self.lbl_total = ttk.Label(top2, textvariable=self._count_var)
        self.lbl_total.pack(side="left", padx=(0, 10))
        self.lbl_profile_total = ttk.Label(top2, textvariable=self._profile_count_var)
        self.lbl_profile_total.pack(side="left", padx=(0, 10))
        self.lbl_fb_total = ttk.Label(top2, textvariable=self._fb_count_var)
        self.lbl_fb_total.pack(side="left", padx=(0, 10))
        self.lbl_fb_profile_total = ttk.Label(top2, textvariable=self._fb_profile_count_var)
        self.lbl_fb_profile_total.pack(side="left")

        self.btn_start = ttk.Button(top, text="START", command=self.start_jobs)
        self.btn_start.pack(side="left", padx=(0, 8))

        self.btn_stop = ttk.Button(top, text="STOP", command=self.stop_jobs)
        self.btn_stop.pack(side="left")
        self.btn_reload = ttk.Button(top, text="RELOAD", command=self.reload_app)
        self.btn_reload.pack(side="left", padx=(8, 0))
        self.btn_import = ttk.Button(top, text="IMPORT", command=self.import_accounts)
        self.btn_import.pack(side="left", padx=(8, 0))
        self.btn_import_proxy = ttk.Button(top, text="IMPORT PROXY", command=self.import_proxy_list)
        self.btn_import_proxy.pack(side="left", padx=(8, 0))
        self.btn_scan = ttk.Button(top, text="SCAN", command=self.start_scan)
        self.btn_scan.pack(side="left", padx=(8, 0))
        self.btn_clear_videos = ttk.Button(top, text="CLEAR VIDEOS", command=self.clear_all_email_videos)
        self.btn_clear_videos.pack(side="left", padx=(8, 0))

        self.notebook = ttk.Notebook(self.root)
        self.tab_upload = ttk.Frame(self.notebook)
        self.tab_profile = ttk.Frame(self.notebook)
        self.tab_fb = ttk.Frame(self.notebook)
        self.tab_fb_profile = ttk.Frame(self.notebook)
        self.tab_interact = ttk.Frame(self.notebook)
        self.tab_stats = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_upload, text="UPLOAD")
        self.notebook.add(self.tab_profile, text="PROFILE")
        self.notebook.add(self.tab_fb, text="FB")
        self.notebook.add(self.tab_fb_profile, text="FB PROFILE")
        self.notebook.add(self.tab_interact, text="INTERACT")
        self.notebook.add(self.tab_stats, text="THỐNG KÊ")
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        # Add Select All / Deselect All buttons for tab_upload
        btn_frame_upload = ttk.Frame(self.tab_upload)
        btn_frame_upload.pack(fill="x", padx=8, pady=(8, 4))

        ttk.Button(btn_frame_upload, text="Select All", command=self._select_all_accounts).pack(side="left", padx=(0, 4))
        ttk.Button(btn_frame_upload, text="Deselect All", command=self._deselect_all_accounts).pack(side="left")

        upload_table = ttk.Frame(self.tab_upload)
        upload_table.pack(fill="both", expand=True, padx=8, pady=8)
        self.tree = ttk.Treeview(
            upload_table,
            columns=("chk", "stt", "email", "pass", "proxy", "status", "posts", "followers", "profile_url", "profile_id"),
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
        self.tree.heading("posts", text="POSTS", command=lambda: self._toggle_upload_sort("posts"))
        self.tree.column("posts", width=70, anchor="center")
        self.tree.heading("followers", text="FOLLOWERS", command=lambda: self._toggle_upload_sort("followers"))
        self.tree.column("followers", width=90, anchor="center")
        self.tree.heading("profile_url", text="PROFILE URL")
        self.tree.column("profile_url", width=260)
        self.tree.heading("profile_id", text="PROFILE ID")
        self.tree.column("profile_id", width=240)

        upload_scroll = ttk.Scrollbar(upload_table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=upload_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        upload_scroll.grid(row=0, column=1, sticky="ns")
        upload_table.grid_rowconfigure(0, weight=1)
        upload_table.grid_columnconfigure(0, weight=1)
        self.tree.tag_configure("status_ok", foreground="green")
        self.tree.tag_configure("status_err", foreground="red")

        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<B1-Motion>", self._on_tree_drag)
        self.tree.bind("<ButtonRelease-1>", self._on_tree_release)
        self.tree.bind("<Button-3>", self._on_tree_right_click)

        profile_table = ttk.Frame(self.tab_profile)
        profile_table.pack(fill="both", expand=True, padx=8, pady=8)
        self.profile_tree = ttk.Treeview(
            profile_table,
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

        profile_scroll = ttk.Scrollbar(profile_table, orient="vertical", command=self.profile_tree.yview)
        self.profile_tree.configure(yscrollcommand=profile_scroll.set)
        self.profile_tree.grid(row=0, column=0, sticky="nsew")
        profile_scroll.grid(row=0, column=1, sticky="ns")
        profile_table.grid_rowconfigure(0, weight=1)
        profile_table.grid_columnconfigure(0, weight=1)
        self.profile_tree.tag_configure("status_ok", foreground="green")
        self.profile_tree.tag_configure("status_err", foreground="red")

        profile_top = ttk.Frame(self.tab_profile)
        profile_top.pack(fill="x", padx=8, pady=(8, 0))
        self.btn_import_profile = ttk.Button(
            profile_top, text="IMPORT PROFILE", command=self.import_profile_accounts
        )
        self.btn_import_profile.pack(side="left")
        ttk.Button(profile_top, text="Select All", command=self._select_all_profile_accounts).pack(side="left", padx=(8, 4))
        ttk.Button(profile_top, text="Deselect All", command=self._deselect_all_profile_accounts).pack(side="left")

        self.profile_tree.bind("<Button-1>", self._on_profile_tree_click)
        self.profile_tree.bind("<B1-Motion>", self._on_profile_tree_drag)
        self.profile_tree.bind("<ButtonRelease-1>", self._on_profile_tree_release)
        self.profile_tree.bind("<Button-3>", self._on_profile_tree_right_click)

        fb_table = ttk.Frame(self.tab_fb)
        fb_table.pack(fill="both", expand=True, padx=8, pady=8)
        self.fb_tree = ttk.Treeview(
            fb_table,
            columns=("chk", "stt", "email", "pass", "proxy", "facebook", "status"),
            show="headings",
            selectmode="extended",
        )
        self.fb_tree.heading("chk", text="v")
        self.fb_tree.column("chk", width=40, anchor="center")
        self.fb_tree.heading("stt", text="STT")
        self.fb_tree.column("stt", width=50, anchor="center")
        self.fb_tree.heading("email", text="EMAIL")
        self.fb_tree.column("email", width=240)
        self.fb_tree.heading("pass", text="PASS")
        self.fb_tree.column("pass", width=130)
        self.fb_tree.heading("proxy", text="PROXY")
        self.fb_tree.column("proxy", width=260)
        self.fb_tree.heading("facebook", text="FB REELS")
        self.fb_tree.column("facebook", width=320)
        self.fb_tree.heading("status", text="TRẠNG THÁI")
        self.fb_tree.column("status", width=200)

        fb_scroll = ttk.Scrollbar(fb_table, orient="vertical", command=self.fb_tree.yview)
        self.fb_tree.configure(yscrollcommand=fb_scroll.set)
        self.fb_tree.grid(row=0, column=0, sticky="nsew")
        fb_scroll.grid(row=0, column=1, sticky="ns")
        fb_table.grid_rowconfigure(0, weight=1)
        fb_table.grid_columnconfigure(0, weight=1)
        self.fb_tree.tag_configure("status_ok", foreground="green")
        self.fb_tree.tag_configure("status_err", foreground="red")

        fb_top = ttk.Frame(self.tab_fb)
        fb_top.pack(fill="x", padx=8, pady=(8, 0))
        self.btn_import_fb = ttk.Button(
            fb_top, text="IMPORT FB", command=self.import_fb_accounts
        )
        self.btn_import_fb.pack(side="left")
        ttk.Button(fb_top, text="Select All", command=self._select_all_fb_accounts).pack(side="left", padx=(8, 4))
        ttk.Button(fb_top, text="Deselect All", command=self._deselect_all_fb_accounts).pack(side="left")
        ttk.Button(fb_top, text="SORT EMAIL", command=lambda: self._sort_tree_by_column(self.fb_tree, "email")).pack(side="left", padx=(8, 4))
        ttk.Button(fb_top, text="RESET ORDER", command=lambda: self._reorder_tree_by_accounts(self.fb_tree, self.fb_accounts)).pack(side="left")

        self.fb_tree.bind("<Button-1>", self._on_fb_tree_click)
        self.fb_tree.bind("<B1-Motion>", self._on_fb_tree_drag)
        self.fb_tree.bind("<ButtonRelease-1>", self._on_fb_tree_release)
        self.fb_tree.bind("<Button-3>", self._on_fb_tree_right_click)

        fb_profile_table = ttk.Frame(self.tab_fb_profile)
        fb_profile_table.pack(fill="both", expand=True, padx=8, pady=8)
        self.fb_profile_tree = ttk.Treeview(
            fb_profile_table,
            columns=("chk", "stt", "email", "pass", "proxy", "facebook", "status"),
            show="headings",
            selectmode="extended",
        )
        self.fb_profile_tree.heading("chk", text="v")
        self.fb_profile_tree.column("chk", width=40, anchor="center")
        self.fb_profile_tree.heading("stt", text="STT")
        self.fb_profile_tree.column("stt", width=50, anchor="center")
        self.fb_profile_tree.heading("email", text="EMAIL")
        self.fb_profile_tree.column("email", width=240)
        self.fb_profile_tree.heading("pass", text="PASS")
        self.fb_profile_tree.column("pass", width=130)
        self.fb_profile_tree.heading("proxy", text="PROXY")
        self.fb_profile_tree.column("proxy", width=260)
        self.fb_profile_tree.heading("facebook", text="FB PROFILE LINK")
        self.fb_profile_tree.column("facebook", width=320)
        self.fb_profile_tree.heading("status", text="TRẠNG THÁI")
        self.fb_profile_tree.column("status", width=200)

        fb_profile_scroll = ttk.Scrollbar(fb_profile_table, orient="vertical", command=self.fb_profile_tree.yview)
        self.fb_profile_tree.configure(yscrollcommand=fb_profile_scroll.set)
        self.fb_profile_tree.grid(row=0, column=0, sticky="nsew")
        fb_profile_scroll.grid(row=0, column=1, sticky="ns")
        fb_profile_table.grid_rowconfigure(0, weight=1)
        fb_profile_table.grid_columnconfigure(0, weight=1)
        self.fb_profile_tree.tag_configure("status_ok", foreground="green")
        self.fb_profile_tree.tag_configure("status_err", foreground="red")

        fb_profile_top = ttk.Frame(self.tab_fb_profile)
        fb_profile_top.pack(fill="x", padx=8, pady=(8, 0))
        self.btn_import_fb_profile = ttk.Button(
            fb_profile_top, text="IMPORT FB PROFILE", command=self.import_fb_profile_accounts
        )
        self.btn_import_fb_profile.pack(side="left")
        ttk.Button(fb_profile_top, text="Select All", command=self._select_all_fb_profile_accounts).pack(side="left", padx=(8, 4))
        ttk.Button(fb_profile_top, text="Deselect All", command=self._deselect_all_fb_profile_accounts).pack(side="left")

        self.fb_profile_tree.bind("<Button-1>", self._on_fb_profile_tree_click)
        self.fb_profile_tree.bind("<B1-Motion>", self._on_fb_profile_tree_drag)
        self.fb_profile_tree.bind("<ButtonRelease-1>", self._on_fb_profile_tree_release)
        self.fb_profile_tree.bind("<Button-3>", self._on_fb_profile_tree_right_click)

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

        stats_top = ttk.Frame(self.tab_stats)
        stats_top.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(stats_top, text="Posts >= ").pack(side="left")
        self.entry_stats_min_posts = ttk.Entry(stats_top, width=6)
        self.entry_stats_min_posts.insert(0, "50")
        self.entry_stats_min_posts.pack(side="left", padx=(5, 10))
        ttk.Label(stats_top, text="Followers < ").pack(side="left")
        self.entry_stats_min_followers = ttk.Entry(stats_top, width=6)
        self.entry_stats_min_followers.insert(0, "100")
        self.entry_stats_min_followers.pack(side="left", padx=(5, 10))
        self.btn_stats_refresh = ttk.Button(stats_top, text="REFRESH", command=self._refresh_stats)
        self.btn_stats_refresh.pack(side="left")

        stats_table = ttk.Frame(self.tab_stats)
        stats_table.pack(fill="both", expand=True, padx=8, pady=8)
        self.stats_tree = ttk.Treeview(
            stats_table,
            columns=("stt", "source", "email", "posts", "followers"),
            show="headings",
            selectmode="browse",
        )
        self.stats_tree.heading("stt", text="STT")
        self.stats_tree.column("stt", width=50, anchor="center")
        self.stats_tree.heading("source", text="SOURCE")
        self.stats_tree.column("source", width=90, anchor="center")
        self.stats_tree.heading("email", text="EMAIL")
        self.stats_tree.column("email", width=260)
        self.stats_tree.heading("posts", text="POSTS")
        self.stats_tree.column("posts", width=90, anchor="center")
        self.stats_tree.heading("followers", text="FOLLOWERS")
        self.stats_tree.column("followers", width=100, anchor="center")
        self.stats_tree.tag_configure("low_ratio", foreground="red")
        stats_scroll = ttk.Scrollbar(stats_table, orient="vertical", command=self.stats_tree.yview)
        self.stats_tree.configure(yscrollcommand=stats_scroll.set)
        self.stats_tree.grid(row=0, column=0, sticky="nsew")
        stats_scroll.grid(row=0, column=1, sticky="ns")
        stats_table.grid_rowconfigure(0, weight=1)
        stats_table.grid_columnconfigure(0, weight=1)

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Tick selected", command=lambda: self._set_checked_selected(True))
        self.menu.add_command(label="Untick selected", command=lambda: self._set_checked_selected(False))
        self.menu.add_command(label="Tick all", command=self._select_all_accounts)
        self.menu.add_command(label="Untick all", command=self._deselect_all_accounts)
        self.menu.add_separator()
        self.menu.add_command(label="Login selected", command=self.menu_login_selected)
        self.menu.add_command(label="Upload selected", command=self.menu_upload_selected)
        self.menu.add_command(label="Get followers", command=self.menu_follow_selected)

        self.profile_menu = tk.Menu(self.root, tearoff=0)
        self.profile_menu.add_command(label="Tick selected", command=lambda: self._set_checked_selected_profile(True))
        self.profile_menu.add_command(label="Untick selected", command=lambda: self._set_checked_selected_profile(False))
        self.profile_menu.add_command(label="Tick all", command=self._select_all_profile_accounts)
        self.profile_menu.add_command(label="Untick all", command=self._deselect_all_profile_accounts)
        self.profile_menu.add_separator()
        self.profile_menu.add_command(label="Open YouTube", command=self.menu_profile_selected)

        self.fb_menu = tk.Menu(self.root, tearoff=0)
        self.fb_menu.add_command(label="Tick selected", command=lambda: self._set_checked_selected_fb(True))
        self.fb_menu.add_command(label="Untick selected", command=lambda: self._set_checked_selected_fb(False))
        self.fb_menu.add_command(label="Tick all", command=self._select_all_fb_accounts)
        self.fb_menu.add_command(label="Untick all", command=self._deselect_all_fb_accounts)

        self.fb_profile_menu = tk.Menu(self.root, tearoff=0)
        self.fb_profile_menu.add_command(label="Tick selected", command=lambda: self._set_checked_selected_fb_profile(True))
        self.fb_profile_menu.add_command(label="Untick selected", command=lambda: self._set_checked_selected_fb_profile(False))
        self.fb_profile_menu.add_command(label="Tick all", command=self._select_all_fb_profile_accounts)
        self.fb_profile_menu.add_command(label="Untick all", command=self._deselect_all_fb_profile_accounts)

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

    def _on_tab_changed(self, _evt=None) -> None:
        try:
            if self.notebook.nametowidget(self.notebook.select()) == self.tab_stats:
                self._refresh_stats()
        except Exception:
            pass

    def _refresh_stats(self) -> None:
        def _to_num(val) -> int:
            if val is None or val == "":
                return 0
            text = str(val).strip()
            if not text:
                return 0
            digits = re.sub(r"[^0-9]", "", text)
            if not digits:
                return 0
            try:
                return int(digits)
            except Exception:
                return 0

        try:
            min_posts = int(self.entry_stats_min_posts.get() or 0)
        except Exception:
            min_posts = 0
        try:
            max_followers = int(self.entry_stats_min_followers.get() or 0)
        except Exception:
            max_followers = 0

        try:
            self.stats_tree.delete(*self.stats_tree.get_children())
        except Exception:
            pass

        rows = []
        for acc in self.accounts:
            email = (acc.get("uid") or "").strip()
            posts = _to_num(acc.get("posts"))
            followers = _to_num(acc.get("followers"))
            if posts < min_posts:
                continue
            rows.append(("UPLOAD", email, posts, followers))

        for acc in self.fb_accounts:
            email = (acc.get("uid") or "").strip()
            posts = _to_num(acc.get("posts"))
            followers = _to_num(acc.get("followers"))
            if posts < min_posts:
                continue
            rows.append(("FB", email, posts, followers))

        for idx, (source, email, posts, followers) in enumerate(rows, start=1):
            tags = ("low_ratio",) if max_followers > 0 and followers < max_followers else ()
            self.stats_tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(idx, source, email, posts, followers),
                tags=tags,
            )

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
        checked_emails = self._get_checked_email_set(self.tree)
        if not checked_emails:
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
        active_count = len(checked_emails)
        cols = min(5, active_count)
        rows_layout = min(2, max(1, math.ceil(active_count / cols)))
        win_w = int((usable_w - gap * (cols - 1)) / cols)
        win_h = int((usable_h - gap * (rows_layout - 1)) / rows_layout)
        win_w = max(150, min(280, win_w))
        win_h = max(420, min(600, win_h))

        join_max = self._get_join_max()
        slot_idx = 0
        max_slots = cols * rows_layout
        email_to_iid = self._map_email_to_item_id(self.tree)
        for acc in self.accounts:
            email = (acc.get("uid") or "").strip()
            if email not in checked_emails:
                continue
            item_id = email_to_iid.get(email)
            if not item_id:
                continue
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
            self._remember_profile_path(profile_id, data_c)
            self.created_profiles.add(profile_id)

            self._set_status(item_id, "START...", profile_id=profile_id)
            ok_s, data_s, msg_s = start_profile(profile_id, win_pos=win_pos, win_size=win_size)
            if not ok_s:
                if self._is_proxy_error(msg_s):
                    try:
                        close_profile(profile_id, 3)
                        delete_profile(profile_id, 10)
                    except Exception:
                        pass
                    try:
                        self.created_profiles.discard(profile_id)
                    except Exception:
                        pass
                    self._delete_profile_path(profile_id)
                    new_id, new_data_s, _err = self._retry_start_profile_with_new_proxy(
                        acc,
                        item_id,
                        "upload",
                        self.tree,
                        lambda s: self._set_status(item_id, s),
                        win_pos=win_pos,
                        win_size=win_size,
                        created_set="created_profiles",
                    )
                    if new_id and new_data_s:
                        profile_id = new_id
                        data_s = new_data_s
                        ok_s = True
                    else:
                        self._set_status(item_id, f"START ERR: {msg_s}")
                        self._log(f"[{acc['uid']}] START ERR: {msg_s}")
                        self._record_failed(item_id, acc, f"START ERR: {msg_s}")
                        return
                else:
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
                if profile_id:
                    self.created_profiles.discard(profile_id)
            except Exception:
                pass
            if profile_id:
                self._delete_profile_path(profile_id)
                self._track_profile_cleanup()
            try:
                with self.active_lock:
                    self.active_profiles.pop(item_id, None)
            except Exception:
                pass
    def _load_rows(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for idx, row in enumerate(self.accounts, start=1):
            posts = row.get("posts", "")
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
                    "" if posts is None else str(posts),
                    "" if followers is None else str(followers),
                    profile_url,
                    row.get("profile_id", ""),
                ),
            )
        self._update_counts()

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
        self._update_counts()

    def _load_fb_rows(self) -> None:
        self.fb_tree.delete(*self.fb_tree.get_children())
        for idx, row in enumerate(self.fb_accounts, start=1):
            self.fb_tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    "v",
                    idx,
                    row.get("uid", ""),
                    row.get("pass", ""),
                    row.get("proxy", ""),
                    row.get("facebook", ""),
                    row.get("status", "READY"),
                ),
            )
        self._update_counts()

    def _load_fb_profile_rows(self) -> None:
        self.fb_profile_tree.delete(*self.fb_profile_tree.get_children())
        for idx, row in enumerate(self.fb_profile_accounts, start=1):
            self.fb_profile_tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    "v",
                    idx,
                    row.get("uid", ""),
                    row.get("pass", ""),
                    row.get("proxy", ""),
                    row.get("facebook", ""),
                    row.get("status", "READY"),
                ),
            )
        self._update_counts()

    def _update_counts(self) -> None:
        try:
            self._count_var.set(self._format_total_with_run("Total", len(self.accounts), "upload"))
        except Exception:
            pass
        try:
            self._profile_count_var.set(
                self._format_total_with_run("Total Profile", len(self.profile_accounts), "profile")
            )
        except Exception:
            pass
        try:
            self._fb_count_var.set(self._format_total_with_run("Total FB", len(self.fb_accounts), "fb"))
        except Exception:
            pass
        try:
            self._fb_profile_count_var.set(
                self._format_total_with_run("Total FB Profile", len(self.fb_profile_accounts), "fb_profile")
            )
        except Exception:
            pass

    def _format_total_with_run(self, label: str, total: int, kind: str) -> str:
        done = 0
        total_run = 0
        try:
            with self._run_counts_lock:
                rc = self._run_counts.get(kind) or {}
                done = int(rc.get("done", 0) or 0)
                total_run = int(rc.get("total", 0) or 0)
        except Exception:
            done = 0
            total_run = 0
        if total_run > 0:
            return f"{label}: {total} | Run: {done}/{total_run}"
        return f"{label}: {total}"

    def _set_run_total(self, kind: str, total: int) -> None:
        try:
            with self._run_counts_lock:
                rc = self._run_counts.get(kind)
                if rc is None:
                    return
                rc["done"] = 0
                rc["total"] = max(0, int(total or 0))
                rc["emails"] = set()
        except Exception:
            pass
        self._update_counts()

    def _reset_run(self, kind: str) -> None:
        try:
            with self._run_counts_lock:
                rc = self._run_counts.get(kind)
                if rc is None:
                    return
                rc["done"] = 0
                rc["total"] = 0
                rc["emails"] = set()
        except Exception:
            pass
        self._update_counts()

    def _mark_run_done(self, kind: str, email: str) -> None:
        if not email:
            return
        updated = False
        try:
            with self._run_counts_lock:
                rc = self._run_counts.get(kind)
                if not rc or rc.get("total", 0) <= 0:
                    return
                if email in rc.get("emails", set()):
                    return
                rc["emails"].add(email)
                rc["done"] = min(int(rc.get("total", 0)), int(rc.get("done", 0)) + 1)
                updated = True
        except Exception:
            updated = False
        if updated:
            self._update_counts()

    def _search_email(self) -> None:
        q = (self.entry_search_email.get() or "").strip()
        if not q or q == self._search_placeholder:
            return
        q = q.lower()
        if not q:
            return
        if self._is_profile_tab():
            tree = self.profile_tree
            rows = self.profile_accounts
        elif self._is_fb_tab():
            tree = self.fb_tree
            rows = self.fb_accounts
        elif self._is_fb_profile_tab():
            tree = self.fb_profile_tree
            rows = self.fb_profile_accounts
        else:
            tree = self.tree
            rows = self.accounts
        matches = []
        email_to_iid = self._map_email_to_item_id(tree)
        for row in rows:
            email = (row.get("uid") or "").strip()
            if q in email.lower():
                iid = email_to_iid.get(email)
                if iid:
                    matches.append(iid)
        if not matches:
            self._log(f"[SEARCH] No match: {q}")
            return
        try:
            tree.selection_remove(tree.selection())
        except Exception:
            pass
        for item_id in matches:
            try:
                tree.selection_add(item_id)
            except Exception:
                pass
        try:
            tree.see(matches[0])
        except Exception:
            pass
        self._log(f"[SEARCH] Found {len(matches)} match(es) for: {q}")

    def _bind_item_email(self, item_id: str, email: str) -> None:
        if not item_id or not email:
            return
        with self._job_item_email_lock:
            self._job_item_email_map[item_id] = email

    def _lookup_item_email(self, item_id: str) -> str:
        with self._job_item_email_lock:
            return self._job_item_email_map.get(item_id, "")

    def _resolve_upload_item_id(self, item_id: str) -> str:
        email = self._lookup_item_email(item_id)
        if not email:
            try:
                email = self.tree.set(item_id, "email")
            except Exception:
                email = ""
        if not email:
            return item_id
        try:
            for iid in self.tree.get_children():
                if self.tree.set(iid, "email") == email:
                    return iid
        except Exception:
            pass
        return item_id

    def _get_acc_by_email(self, email: str) -> dict | None:
        if not email:
            return None
        for acc in self.accounts:
            if acc.get("uid") == email:
                return acc
        return None

    def _collect_transient_failures(self) -> list:
        items = []
        try:
            for iid in self.tree.get_children():
                status = (self.tree.set(iid, "status") or "").strip()
                if status not in self._transient_statuses:
                    continue
                email = self.tree.set(iid, "email")
                acc = self._get_acc_by_email(email)
                if not acc:
                    continue
                self._set_status(iid, "INCOMPLETE")
                items.append((iid, acc))
        except Exception:
            pass
        return items

    def _search_focus_in(self, _evt=None) -> None:
        try:
            if self.entry_search_email.get() == self._search_placeholder:
                self.entry_search_email.delete(0, tk.END)
                self.entry_search_email.configure(foreground="black")
        except Exception:
            pass

    def _search_focus_out(self, _evt=None) -> None:
        try:
            if not self.entry_search_email.get().strip():
                self.entry_search_email.delete(0, tk.END)
                self.entry_search_email.insert(0, self._search_placeholder)
                self.entry_search_email.configure(foreground="gray")
        except Exception:
            pass

    def _set_status(self, item_id: str, status: str, profile_id: str = "") -> None:
        def _update():
            resolved_id = self._resolve_upload_item_id(item_id)
            if profile_id:
                self.tree.set(resolved_id, "profile_id", profile_id)
            self.tree.set(resolved_id, "status", status)
            self._apply_status_tag(resolved_id, status)
            self._auto_scroll_if_needed(self.tree, resolved_id, status)
            try:
                email = self.tree.set(resolved_id, "email")
                if email:
                    for acc in self.accounts:
                        if acc.get("uid") == email:
                            acc["status"] = status
                            if profile_id:
                                acc["profile_id"] = profile_id
                            break
                self._save_accounts_cache()
            except Exception:
                pass

        self.root.after(0, _update)

    def _set_profile_status(self, item_id: str, status: str) -> None:
        def _update():
            self.profile_tree.set(item_id, "status", status)
            self._apply_profile_status_tag(item_id, status)
            self._auto_scroll_if_needed(self.profile_tree, item_id, status)

        self.root.after(0, _update)

    def _set_fb_status(self, item_id: str, status: str) -> None:
        def _update():
            self.fb_tree.set(item_id, "status", status)
            self._apply_fb_status_tag(item_id, status)
            self._auto_scroll_if_needed(self.fb_tree, item_id, status)

        self.root.after(0, _update)

    def _set_fb_profile_status(self, item_id: str, status: str) -> None:
        def _update():
            self.fb_profile_tree.set(item_id, "status", status)
            self._apply_fb_profile_status_tag(item_id, status)
            self._auto_scroll_if_needed(self.fb_profile_tree, item_id, status)

        self.root.after(0, _update)

    def _auto_scroll_if_needed(self, tree: ttk.Treeview, item_id: str, status: str) -> None:
        try:
            status_upper = (status or "").upper()
            active_keys = [
                "START",
                "LOGIN",
                "SCAN",
                "POSTING",
                "DOWNLOAD",
                "JOIN",
                "RESTART",
                "RELOGIN",
            ]
            if not any(key in status_upper for key in active_keys):
                return
            if tree.bbox(item_id) is not None:
                return
            tree.see(item_id)
        except Exception:
            pass

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
                "posts": self.tree.set(iid, "posts"),
                "followers": self.tree.set(iid, "followers"),
                "profile_url": self.tree.set(iid, "profile_url"),
                "profile_id": self.tree.set(iid, "profile_id"),
                "tags": self.tree.item(iid, "tags"),
            }
        self.tree.delete(*self.tree.get_children())
        seen = set()
        out_idx = 1
        for row in self.accounts:
            email = row.get("uid", "")
            if email in seen:
                continue
            seen.add(email)
            cached = state.get(email, {})
            posts = cached.get("posts", row.get("posts", ""))
            followers = cached.get("followers", row.get("followers", ""))
            profile_url = cached.get("profile_url", row.get("profile_url", ""))
            status = row.get("status") or cached.get("status", "READY")
            chk = "v" if email in FIXED_SCAN_EMAILS else cached.get("chk", "v")
            tags = cached.get("tags", ())
            self.tree.insert(
                "",
                "end",
                iid=str(out_idx),
                values=(
                    chk,
                    out_idx,
                    email,
                    row.get("pass", ""),
                    row.get("proxy", ""),
                    status,
                    "" if posts is None else str(posts),
                    "" if followers is None else str(followers),
                    profile_url,
                    cached.get("profile_id", row.get("profile_id", "")),
                ),
                tags=tags,
            )
            out_idx += 1

    def _sort_followers_desc(self) -> None:
        return

    def _toggle_followers_sort_all(self) -> None:
        state = self._sort_state.get("followers_all")
        if state == "desc":
            self._sort_state["followers_all"] = "asc"
            self._sort_accounts_by_followers(descending=False)
            return
        self._sort_state["followers_all"] = "desc"
        self._sort_accounts_by_followers(descending=True)

    def _sort_accounts_by_followers(self, descending: bool = True) -> None:
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

        try:
            email_to_followers = {}
            for iid in self.tree.get_children():
                email = (self.tree.set(iid, "email") or "").strip()
                if not email:
                    continue
                email_to_followers[email] = _to_num(self.tree.set(iid, "followers"))

            def _followers_for(acc: dict) -> int:
                email = (acc.get("uid") or "").strip()
                if email in email_to_followers:
                    return email_to_followers[email]
                return _to_num(acc.get("followers"))

            self.accounts.sort(key=_followers_for, reverse=descending)
            self._rebuild_tree_from_accounts()
            self._save_accounts_cache()
        except Exception:
            pass

    def _enqueue_upload_turn(self) -> int:
        with self._upload_queue_cond:
            self._upload_queue_seq += 1
            token = self._upload_queue_seq
            self._upload_queue.append(token)
            self._upload_queue_cond.notify_all()
            return token

    def _wait_upload_turn(self, token: int) -> bool:
        with self._upload_queue_cond:
            while True:
                if self.stop_event.is_set():
                    if token in self._upload_queue:
                        try:
                            self._upload_queue.remove(token)
                        except Exception:
                            pass
                    self._upload_queue_cond.notify_all()
                    return False
                if self._upload_queue and self._upload_queue[0] == token:
                    return True
                self._upload_queue_cond.wait(timeout=0.5)

    def _release_upload_turn(self, token: int) -> None:
        with self._upload_queue_cond:
            if self._upload_queue and self._upload_queue[0] == token:
                self._upload_queue.pop(0)
            else:
                try:
                    self._upload_queue.remove(token)
                except Exception:
                    pass
            self._upload_queue_cond.notify_all()

    def _schedule_follow_sort(self) -> None:
        if self._follow_sort_after_id:
            try:
                self.root.after_cancel(self._follow_sort_after_id)
            except Exception:
                pass
            self._follow_sort_after_id = None

        def _run():
            self._follow_sort_after_id = None
            self._apply_follow_sort()

        self._follow_sort_after_id = self.root.after(300, _run)

    def _apply_follow_sort(self) -> None:
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

        try:
            self.accounts.sort(
                key=lambda acc: _to_num(acc.get("followers")),
                reverse=True,
            )
            self._rebuild_tree_from_accounts()
            self._save_accounts_cache()
        except Exception:
            pass

    def _sort_tree_by_column(self, tree: ttk.Treeview, col: str, descending: bool = True) -> None:
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

        try:
            items = list(tree.get_children())
            items.sort(key=lambda iid: _to_num(tree.set(iid, col)), reverse=descending)
            for idx, iid in enumerate(items):
                tree.move(iid, "", idx)
                try:
                    tree.set(iid, "stt", str(idx + 1))
                except Exception:
                    pass
        except Exception:
            pass

    def _reset_upload_tree_order(self) -> None:
        # Rebuild upload tree in original accounts order
        self._sort_state["posts"] = None
        self._sort_state["followers"] = None
        self._rebuild_tree_from_accounts()

    def _toggle_upload_sort(self, col: str) -> None:
        # Cycle: desc -> asc -> reset
        state = self._sort_state.get(col)
        if state is None:
            self._sort_state[col] = "desc"
            self._sort_tree_by_column(self.tree, col, descending=True)
            return
        if state == "desc":
            self._sort_state[col] = "asc"
            self._sort_tree_by_column(self.tree, col, descending=False)
            return
        self._sort_state[col] = None
        self._reset_upload_tree_order()

    def _get_checked_email_set(self, tree: ttk.Treeview) -> set:
        emails = set()
        try:
            for iid in tree.get_children():
                if tree.set(iid, "chk") != "v":
                    continue
                email = (tree.set(iid, "email") or "").strip()
                if email:
                    emails.add(email)
        except Exception:
            pass
        return emails

    def _map_email_to_item_id(self, tree: ttk.Treeview) -> dict:
        mapping = {}
        try:
            for iid in tree.get_children():
                email = (tree.set(iid, "email") or "").strip()
                if email:
                    mapping[email] = iid
        except Exception:
            pass
        return mapping

    def _status_is_done(self, status: str, done_keys: set) -> bool:
        text = (status or "").strip().upper()
        return any(k in text for k in done_keys)

    def _collect_pending_emails(self, tree: ttk.Treeview, done_keys: set) -> set:
        pending = set()
        try:
            for iid in tree.get_children():
                email = (tree.set(iid, "email") or "").strip()
                if not email:
                    continue
                status = tree.set(iid, "status")
                if not self._status_is_done(status, done_keys):
                    pending.add(email)
        except Exception:
            pass
        return pending

    def _prompt_resume(self, kind: str, count: int) -> bool:
        msg = (
            f"Có {count} tài khoản chưa OK.\n"
            f"Bạn muốn chạy tiếp các tài khoản chưa OK không?"
        )
        return messagebox.askyesno("Tiep tuc", msg)

    def _reorder_tree_by_accounts(self, tree: ttk.Treeview, accounts: list) -> None:
        try:
            email_to_iid = self._map_email_to_item_id(tree)
            idx = 0
            for acc in accounts:
                email = (acc.get("uid") or "").strip()
                iid = email_to_iid.get(email)
                if not iid:
                    continue
                tree.move(iid, "", idx)
                idx += 1
        except Exception:
            pass

    def _apply_status_tag(self, item_id: str, status: str) -> None:
        status_upper = (status or "").upper()
        if any(key in status_upper for key in ["ERR", "ERROR", "FAIL", "BLOCKED", "LOI"]):
            self.tree.item(item_id, tags=("status_err",))
        elif any(key in status_upper for key in ["OK", "SUCCESS", "DONE", "POSTING", "UPLOAD"]):
            self.tree.item(item_id, tags=("status_ok",))
        else:
            self.tree.item(item_id, tags=())

    def _apply_profile_status_tag(self, item_id: str, status: str) -> None:
        status_upper = (status or "").upper()
        if any(key in status_upper for key in ["ERR", "ERROR", "FAIL", "BLOCKED", "LOI"]):
            self.profile_tree.item(item_id, tags=("status_err",))
        elif any(key in status_upper for key in ["OK", "SUCCESS", "DONE", "UPDATED", "POSTING", "UPLOAD"]):
            self.profile_tree.item(item_id, tags=("status_ok",))
        else:
            self.profile_tree.item(item_id, tags=())

    def _apply_fb_status_tag(self, item_id: str, status: str) -> None:
        status_upper = (status or "").upper()
        if any(key in status_upper for key in ["ERR", "ERROR", "FAIL", "BLOCKED", "LOI"]):
            self.fb_tree.item(item_id, tags=("status_err",))
        elif any(key in status_upper for key in ["OK", "SUCCESS", "DONE", "POSTING", "UPLOAD"]):
            self.fb_tree.item(item_id, tags=("status_ok",))
        else:
            self.fb_tree.item(item_id, tags=())

    def _apply_fb_profile_status_tag(self, item_id: str, status: str) -> None:
        status_upper = (status or "").upper()
        if any(key in status_upper for key in ["ERR", "ERROR", "FAIL", "BLOCKED", "LOI"]):
            self.fb_profile_tree.item(item_id, tags=("status_err",))
        elif any(key in status_upper for key in ["OK", "SUCCESS", "DONE", "UPDATED", "POSTING", "UPLOAD"]):
            self.fb_profile_tree.item(item_id, tags=("status_ok",))
        else:
            self.fb_profile_tree.item(item_id, tags=())

    def _next_proxy(self) -> str:
        with self._extra_proxy_lock:
            if not self._extra_proxies:
                return ""
            proxy = self._extra_proxies[self._extra_proxy_idx % len(self._extra_proxies)]
            self._extra_proxy_idx += 1
            return proxy

    def _is_proxy_error(self, msg: str) -> bool:
        text = (msg or "").lower()
        if "proxy" not in text:
            return False
        proxy_keywords = [
            "connect",
            "connection",
            "cannot",
            "can't",
            "failed",
            "timeout",
            "tunnel",
            "khong the",
            "không thể",
            "ket noi",
            "kết nối",
        ]
        return any(k in text for k in proxy_keywords)

    def _set_proxy_cell(self, tree: ttk.Treeview, item_id: str, proxy: str) -> None:
        try:
            if tree == self.tree:
                item_id = self._resolve_upload_item_id(item_id)
            tree.set(item_id, "proxy", proxy)
        except Exception:
            pass

    def _save_cache_by_kind(self, kind: str) -> None:
        if kind == "upload":
            self._save_accounts_cache()
        elif kind == "profile":
            self._save_profile_accounts_cache()
        elif kind == "fb":
            self._save_fb_accounts_cache()
        elif kind == "fb_profile":
            self._save_fb_profile_accounts_cache()

    def _load_extra_proxy_list(self) -> None:
        try:
            if not os.path.exists(self._extra_proxy_file):
                return
            with open(self._extra_proxy_file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return
        proxies = []
        for raw in content.splitlines():
            line = (raw or "").strip()
            if not line:
                continue
            for sep in (",", "\t", ";", " "):
                if sep in line:
                    line = line.split(sep, 1)[0].strip()
                    break
            if line:
                proxies.append(line)
        if not proxies:
            return
        with self._extra_proxy_lock:
            self._extra_proxies = proxies
            self._extra_proxy_idx = 0

    def _save_extra_proxy_list(self) -> None:
        try:
            with self._extra_proxy_lock:
                proxies = list(self._extra_proxies)
        except Exception:
            return
        try:
            with open(self._extra_proxy_file, "w", encoding="utf-8") as f:
                f.write("\n".join(proxies))
        except Exception:
            pass

    def _replace_proxy_for_account(self, acc: dict, item_id: str, kind: str, tree: ttk.Treeview) -> bool:
        new_proxy = self._next_proxy()
        if not new_proxy:
            self._log("[PROXY] No extra proxies available")
            return False
        acc["proxy"] = new_proxy
        self._set_proxy_cell(tree, item_id, new_proxy)
        try:
            self._save_cache_by_kind(kind)
        except Exception:
            pass
        self._log(f"[PROXY] Swapped proxy for {acc.get('uid','')} -> {new_proxy}")
        return True

    def _retry_start_profile_with_new_proxy(
        self,
        acc: dict,
        item_id: str,
        kind: str,
        tree: ttk.Treeview,
        status_setter,
        win_pos: str | None = None,
        win_size: str | None = None,
        created_set: str = "created_profiles",
    ) -> tuple[str | None, dict | None, str]:
        if not self._replace_proxy_for_account(acc, item_id, kind, tree):
            return None, None, ""
        ok_c = False
        data_c = {}
        msg_c = ""
        with self.create_lock:
            for attempt in range(2):
                ok_c, data_c, msg_c = create_profile(acc["uid"], acc["proxy"], SCOOPZ_URL)
                if ok_c:
                    break
                time.sleep(2 + attempt)
        if not ok_c:
            status_setter(f"CREATE ERR: {msg_c}")
            return None, None, msg_c
        profile_id = None
        if isinstance(data_c, dict):
            profile_id = (data_c.get("data") or {}).get("id") or data_c.get("id") or data_c.get("profile_id")
        if not profile_id:
            status_setter("NO PROFILE ID")
            return None, None, "NO PROFILE ID"
        self._remember_profile_path(profile_id, data_c)
        try:
            getattr(self, created_set).add(profile_id)
        except Exception:
            pass
        status_setter("START...")
        if win_pos is None:
            ok_s, data_s, msg_s = start_profile(profile_id)
        else:
            ok_s, data_s, msg_s = start_profile(profile_id, win_pos=win_pos, win_size=win_size)
        if not ok_s:
            status_setter(f"START ERR: {msg_s}")
            return None, None, msg_s
        return profile_id, data_s, ""

    def _clear_status_tags(self) -> None:
        try:
            for iid in self.tree.get_children():
                self.tree.item(iid, tags=())
        except Exception:
            pass

    def _reset_statuses(self, tree: ttk.Treeview, accounts: list, ready_text: str = "READY") -> None:
        try:
            for acc in accounts:
                acc["status"] = ready_text
        except Exception:
            pass
        try:
            for iid in tree.get_children():
                tree.set(iid, "status", ready_text)
                tree.item(iid, tags=())
        except Exception:
            pass

    def _reset_all_statuses(self) -> None:
        self._reset_statuses(self.tree, self.accounts, "READY")
        self._reset_statuses(self.profile_tree, self.profile_accounts, "READY")
        self._reset_statuses(self.fb_tree, self.fb_accounts, "READY")
        self._reset_statuses(self.fb_profile_tree, self.fb_profile_accounts, "READY")
        try:
            self._save_accounts_cache()
            self._save_profile_accounts_cache()
            self._save_fb_accounts_cache()
            self._save_fb_profile_accounts_cache()
        except Exception:
            pass

    def _log(self, msg: str) -> None:
        def _is_noisy(m: str) -> bool:
            text = (m or "").strip()
            if text.startswith("[DL]"):
                return True
            if text.startswith("[LOGIN]") and not any(k in text for k in ("ERR", "OK")):
                return True
            if text.startswith("[PROFILE]") and not any(k in text for k in ("ERR", "OK", "UPDATED", "OPENED", "CHANGE")):
                return True
            return False

        if _is_noisy(msg):
            return

        def _append():
            self.log_box.configure(state="normal")
            self.log_box.insert(tk.END, msg + "\n")
            self.log_box.see(tk.END)
            self.log_box.configure(state="disabled")
        self.root.after(0, _append)

    def _clear_log_files(self) -> None:
        paths = [
            os.path.join(_THIS_DIR, "logs", "app.log"),
            os.path.join(_THIS_DIR, "logs", "uploads.log"),
            os.path.join(_THIS_DIR, "logs", "downloads.log"),
            os.path.join(_THIS_DIR, "logs", "errors.log"),
            os.path.join(_THIS_DIR, "logs", "threads.log"),
            os.path.join(_THIS_DIR, "logs", "failed_accounts.log"),
        ]
        for path in paths:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8"):
                    pass
            except Exception:
                pass

    def _clear_log_view(self) -> None:
        try:
            self.log_box.configure(state="normal")
            self.log_box.delete("1.0", tk.END)
            self.log_box.configure(state="disabled")
        except Exception:
            pass

    def _clear_all_logs(self) -> None:
        self._clear_log_files()
        self._clear_log_view()

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

    def _set_profile_info(self, item_id: str, profile_url: str, followers, posts=None) -> None:
        def _update():
            resolved_id = self._resolve_upload_item_id(item_id)
            if profile_url:
                self.tree.set(resolved_id, "profile_url", profile_url)
            if followers is not None:
                self.tree.set(resolved_id, "followers", str(followers))
            if posts is not None:
                self.tree.set(resolved_id, "posts", str(posts))
        self.root.after(0, _update)
        try:
            email = self._lookup_item_email(item_id)
            if not email:
                try:
                    email = self.tree.set(item_id, "email")
                except Exception:
                    email = ""
            if email:
                for acc in self.accounts:
                    if acc.get("uid") == email:
                        if profile_url:
                            acc["profile_url"] = profile_url
                        if followers is not None:
                            acc["followers"] = followers
                        if posts is not None:
                            acc["posts"] = posts
                        break
                self._save_accounts_cache()
                # Keep original order; no auto sort after fetching followers
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
        count = 0
        for item_id in self.tree.get_children():
            self.tree.set(item_id, "chk", "v")
            count += 1
        self._log(f"[SELECT] UPLOAD select all ({count})")

    def _deselect_all_accounts(self) -> None:
        """Deselect all accounts (unmark all)"""
        count = 0
        for item_id in self.tree.get_children():
            self.tree.set(item_id, "chk", "")
            count += 1
        self._log(f"[SELECT] UPLOAD deselect all ({count})")

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
        elif tree == self.fb_tree:
            if idx is None or idx >= len(self.fb_accounts):
                return
            if col_name == "email":
                self.fb_accounts[idx]["uid"] = new_value
            elif col_name in ("pass", "proxy", "facebook"):
                self.fb_accounts[idx][col_name] = new_value
            self._save_fb_accounts_cache()
        elif tree == self.fb_profile_tree:
            if idx is None or idx >= len(self.fb_profile_accounts):
                return
            if col_name == "email":
                self.fb_profile_accounts[idx]["uid"] = new_value
            elif col_name in ("pass", "proxy", "facebook"):
                self.fb_profile_accounts[idx][col_name] = new_value
            self._save_fb_profile_accounts_cache()

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

    def _select_all_profile_accounts(self) -> None:
        count = 0
        for item_id in self.profile_tree.get_children():
            self.profile_tree.set(item_id, "chk", "v")
            count += 1
        self._log(f"[SELECT] PROFILE select all ({count})")

    def _deselect_all_profile_accounts(self) -> None:
        count = 0
        for item_id in self.profile_tree.get_children():
            self.profile_tree.set(item_id, "chk", "")
            count += 1
        self._log(f"[SELECT] PROFILE deselect all ({count})")

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

    def _toggle_checked_fb(self, item_id: str) -> None:
        cur = self.fb_tree.set(item_id, "chk")
        self.fb_tree.set(item_id, "chk", "" if cur == "v" else "v")

    def _set_checked_selected_fb(self, checked: bool) -> None:
        mark = "v" if checked else ""
        for item_id in self.fb_tree.selection():
            self.fb_tree.set(item_id, "chk", mark)

    def _select_all_fb_accounts(self) -> None:
        count = 0
        for item_id in self.fb_tree.get_children():
            self.fb_tree.set(item_id, "chk", "v")
            count += 1
        self._log(f"[SELECT] FB select all ({count})")

    def _deselect_all_fb_accounts(self) -> None:
        count = 0
        for item_id in self.fb_tree.get_children():
            self.fb_tree.set(item_id, "chk", "")
            count += 1
        self._log(f"[SELECT] FB deselect all ({count})")

    def _on_fb_tree_click(self, event) -> None:
        region = self.fb_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        column = self.fb_tree.identify_column(event.x)
        row = self.fb_tree.identify_row(event.y)
        if row:
            try:
                col_idx = int(column[1:]) - 1
                col_name = self.fb_tree["columns"][col_idx]
            except Exception:
                col_name = ""
            if col_name in {"email", "pass", "proxy", "facebook"}:
                self._begin_cell_edit(self.fb_tree, row, col_name)
                return "break"
        if column == "#1" and row:
            self._toggle_checked_fb(row)
            return "break"
        if row:
            self._fb_dragging = True
            self._fb_drag_start = row

    def _on_fb_tree_right_click(self, event) -> None:
        row = self.fb_tree.identify_row(event.y)
        if row:
            if row not in self.fb_tree.selection():
                self.fb_tree.selection_set(row)
            self.fb_menu.tk_popup(event.x_root, event.y_root)

    def _on_fb_tree_drag(self, event) -> None:
        if not self._fb_dragging or not self._fb_drag_start:
            return
        row = self.fb_tree.identify_row(event.y)
        if not row:
            return
        children = list(self.fb_tree.get_children())
        try:
            start_idx = children.index(self._fb_drag_start)
            cur_idx = children.index(row)
        except ValueError:
            return
        lo = min(start_idx, cur_idx)
        hi = max(start_idx, cur_idx)
        self.fb_tree.selection_set(children[lo : hi + 1])

    def _on_fb_tree_release(self, event) -> None:
        self._fb_dragging = False
        self._fb_drag_start = None

    def _toggle_checked_fb_profile(self, item_id: str) -> None:
        cur = self.fb_profile_tree.set(item_id, "chk")
        self.fb_profile_tree.set(item_id, "chk", "" if cur == "v" else "v")

    def _set_checked_selected_fb_profile(self, checked: bool) -> None:
        mark = "v" if checked else ""
        for item_id in self.fb_profile_tree.selection():
            self.fb_profile_tree.set(item_id, "chk", mark)

    def _select_all_fb_profile_accounts(self) -> None:
        count = 0
        for item_id in self.fb_profile_tree.get_children():
            self.fb_profile_tree.set(item_id, "chk", "v")
            count += 1
        self._log(f"[SELECT] FB PROFILE select all ({count})")

    def _deselect_all_fb_profile_accounts(self) -> None:
        count = 0
        for item_id in self.fb_profile_tree.get_children():
            self.fb_profile_tree.set(item_id, "chk", "")
            count += 1
        self._log(f"[SELECT] FB PROFILE deselect all ({count})")

    def _on_fb_profile_tree_click(self, event) -> None:
        region = self.fb_profile_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        column = self.fb_profile_tree.identify_column(event.x)
        row = self.fb_profile_tree.identify_row(event.y)
        if row:
            try:
                col_idx = int(column[1:]) - 1
                col_name = self.fb_profile_tree["columns"][col_idx]
            except Exception:
                col_name = ""
            if col_name in {"email", "pass", "proxy", "facebook"}:
                self._begin_cell_edit(self.fb_profile_tree, row, col_name)
                return "break"
        if column == "#1" and row:
            self._toggle_checked_fb_profile(row)
            return "break"
        if row:
            self._fb_profile_dragging = True
            self._fb_profile_drag_start = row

    def _on_fb_profile_tree_right_click(self, event) -> None:
        row = self.fb_profile_tree.identify_row(event.y)
        if row:
            if row not in self.fb_profile_tree.selection():
                self.fb_profile_tree.selection_set(row)
            self.fb_profile_menu.tk_popup(event.x_root, event.y_root)

    def _on_fb_profile_tree_drag(self, event) -> None:
        if not self._fb_profile_dragging or not self._fb_profile_drag_start:
            return
        row = self.fb_profile_tree.identify_row(event.y)
        if not row:
            return
        children = list(self.fb_profile_tree.get_children())
        try:
            start_idx = children.index(self._fb_profile_drag_start)
            cur_idx = children.index(row)
        except ValueError:
            return
        lo = min(start_idx, cur_idx)
        hi = max(start_idx, cur_idx)
        self.fb_profile_tree.selection_set(children[lo : hi + 1])

    def _on_fb_profile_tree_release(self, event) -> None:
        self._fb_profile_dragging = False
        self._fb_profile_drag_start = None

    def _get_selected_accounts(self):
        items = []
        acc_by_email = {str(a.get("uid") or "").strip(): a for a in self.accounts}
        for iid in self.tree.selection():
            email = (self.tree.set(iid, "email") or "").strip()
            acc = acc_by_email.get(email)
            if acc:
                items.append((iid, acc))
        return items

    def _get_selected_profile_accounts(self):
        items = []
        acc_by_email = {str(a.get("uid") or "").strip(): a for a in self.profile_accounts}
        for iid in self.profile_tree.selection():
            email = (self.profile_tree.set(iid, "email") or "").strip()
            acc = acc_by_email.get(email)
            if acc:
                items.append((iid, acc))
        return items

    def _get_checked_accounts(self):
        items = []
        acc_by_email = {str(a.get("uid") or "").strip(): a for a in self.accounts}
        for iid in self.tree.get_children():
            if self.tree.set(iid, "chk") != "v":
                continue
            email = (self.tree.set(iid, "email") or "").strip()
            acc = acc_by_email.get(email)
            if acc:
                items.append((iid, acc))
        return items

    def _get_checked_profile_accounts(self):
        items = []
        acc_by_email = {str(a.get("uid") or "").strip(): a for a in self.profile_accounts}
        for iid in self.profile_tree.get_children():
            if self.profile_tree.set(iid, "chk") != "v":
                continue
            email = (self.profile_tree.set(iid, "email") or "").strip()
            acc = acc_by_email.get(email)
            if acc:
                items.append((iid, acc))
        return items

    def _get_context_accounts(self):
        if self._context_item:
            email = (self.tree.set(self._context_item, "email") or "").strip()
            acc_by_email = {str(a.get("uid") or "").strip(): a for a in self.accounts}
            acc = acc_by_email.get(email)
            if acc:
                return [(self._context_item, acc)]
        return []

    def _get_context_profile_accounts(self):
        if self._profile_context_item:
            email = (self.profile_tree.set(self._profile_context_item, "email") or "").strip()
            acc_by_email = {str(a.get("uid") or "").strip(): a for a in self.profile_accounts}
            acc = acc_by_email.get(email)
            if acc:
                return [(self._profile_context_item, acc)]
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
            self._bind_item_email(item_id, acc.get("uid", ""))
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
            self._bind_item_email(item_id, acc.get("uid", ""))
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
            self._bind_item_email(item_id, acc.get("uid", ""))
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

    def _load_fb_accounts_cache(self) -> list:
        if not os.path.exists(self._fb_accounts_file):
            return []
        try:
            with open(self._fb_accounts_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            return []
        return []

    def _save_fb_accounts_cache(self) -> None:
        try:
            with open(self._fb_accounts_file, "w", encoding="utf-8") as f:
                json.dump(self.fb_accounts, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_fb_profile_accounts_cache(self) -> list:
        if not os.path.exists(self._fb_profile_accounts_file):
            return []
        try:
            with open(self._fb_profile_accounts_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            return []
        return []

    def _save_fb_profile_accounts_cache(self) -> None:
        try:
            with open(self._fb_profile_accounts_file, "w", encoding="utf-8") as f:
                json.dump(self.fb_profile_accounts, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _on_close(self) -> None:
        self._save_accounts_cache()
        self._save_profile_accounts_cache()
        self._save_fb_accounts_cache()
        self._save_fb_profile_accounts_cache()
        # Print error summary before closing
        self.error_logger.print_error_summary()
        try:
            self.root.destroy()
        except Exception:
            pass

    def import_accounts(self) -> None:
        if self._is_profile_tab():
            self.import_profile_accounts()
            return
        if self._is_fb_tab():
            self.import_fb_accounts()
            return
        if self._is_fb_profile_tab():
            self.import_fb_profile_accounts()
            return
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

        existing_by_uid = {str(a.get("uid") or "").strip(): a for a in self.accounts}
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
            acc = {"uid": uid, "pass": pwd, "proxy": proxy, "youtube": yt}
            old = existing_by_uid.get(uid)
            if old:
                acc["followers"] = old.get("followers")
                acc["posts"] = old.get("posts")
                acc["profile_url"] = old.get("profile_url", "")
            new_accounts.append(acc)

        if not new_accounts:
            messagebox.showinfo("Import", "Khong tim thay dong du lieu hop le.")
            return

        self.accounts = new_accounts
        self._load_rows()
        self._save_accounts_cache()
        self._log(f"[IMPORT] Loaded {len(new_accounts)} accounts")

    def import_proxy_list(self) -> None:
        path = filedialog.askopenfilename(
            title="Import proxy list",
            filetypes=[
                ("Text/CSV", "*.txt;*.csv;*.tsv"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            messagebox.showerror("Import Proxy", f"Loi doc file: {e}")
            return
        proxies = []
        for raw in content.splitlines():
            line = (raw or "").strip()
            if not line:
                continue
            # Accept first field if CSV/TSV
            for sep in (",", "\t", ";", " "):
                if sep in line:
                    line = line.split(sep, 1)[0].strip()
                    break
            if line:
                proxies.append(line)
        if not proxies:
            messagebox.showinfo("Import Proxy", "Khong tim thay proxy hop le.")
            return
        with self._extra_proxy_lock:
            self._extra_proxies = proxies
            self._extra_proxy_idx = 0
        self._save_extra_proxy_list()
        self._log(f"[PROXY] Loaded {len(proxies)} proxies")

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

    def import_fb_accounts(self) -> None:
        path = filedialog.askopenfilename(
            title="Import FB accounts",
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
            fb_link = (row[3] or "").strip()
            if uid.lower() in ("email", "uid") and pwd.lower() in ("pass", "password") and proxy.lower() in ("proxy", "raw_proxy"):
                continue
            if not uid:
                continue
            new_accounts.append({"uid": uid, "pass": pwd, "proxy": proxy, "facebook": fb_link})

        if not new_accounts:
            messagebox.showinfo("Import", "Khong tim thay dong du lieu hop le.")
            return

        self.fb_accounts = new_accounts
        self._load_fb_rows()
        self._save_fb_accounts_cache()
        self._log(f"[IMPORT FB] Loaded {len(new_accounts)} accounts")

    def import_fb_profile_accounts(self) -> None:
        path = filedialog.askopenfilename(
            title="Import FB profile accounts",
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
            fb_link = (row[3] or "").strip()
            if uid.lower() in ("email", "uid") and pwd.lower() in ("pass", "password") and proxy.lower() in ("proxy", "raw_proxy"):
                continue
            if not uid:
                continue
            new_accounts.append({"uid": uid, "pass": pwd, "proxy": proxy, "facebook": fb_link})

        if not new_accounts:
            messagebox.showinfo("Import", "Khong tim thay dong du lieu hop le.")
            return

        self.fb_profile_accounts = new_accounts
        self._load_fb_profile_rows()
        self._save_fb_profile_accounts_cache()
        self._log(f"[IMPORT FB PROFILE] Loaded {len(new_accounts)} accounts")

    def _is_profile_tab(self) -> bool:
        try:
            return self.notebook.nametowidget(self.notebook.select()) == self.tab_profile
        except Exception:
            return False

    def _is_fb_tab(self) -> bool:
        try:
            return self.notebook.nametowidget(self.notebook.select()) == self.tab_fb
        except Exception:
            return False

    def _is_fb_profile_tab(self) -> bool:
        try:
            return self.notebook.nametowidget(self.notebook.select()) == self.tab_fb_profile
        except Exception:
            return False

    def start_profile_jobs(self) -> None:
        if self._profile_batch_running or self.executor is not None:
            return
        self._reset_all_statuses()
        self._clear_all_logs()
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

        self._fixed_threads = max_threads
        self.stop_event.clear()
        self._profile_retry_round = 0
        with self.profile_failed_lock:
            self.profile_failed_accounts = []
        pending = self._resume_pending.get("profile") or set()
        if pending:
            if self._prompt_resume("profile", len(pending)):
                checked_emails = pending
            else:
                self._resume_pending["profile"] = set()
                checked_emails = self._get_checked_email_set(self.profile_tree)
        else:
            checked_emails = self._get_checked_email_set(self.profile_tree)
        if not checked_emails:
            messagebox.showinfo("Thong bao", "Khong co profile nao duoc tick.")
            return
        self._set_run_total("profile", len(checked_emails))
        self._profile_batch_running = True

        def _sleep_with_stop(total_sec: float) -> None:
            end_time = time.time() + max(0.0, total_sec)
            next_log = 0.0
            while time.time() < end_time:
                if self.stop_event.is_set():
                    break
                remaining = max(0.0, end_time - time.time())
                # Log countdown every 10s, and each second for last 5s
                now = time.time()
                if remaining <= 5 or now >= next_log:
                    mm = int(remaining) // 60
                    ss = int(remaining) % 60
                    self._log(f"[PROFILE BATCH] Resume in {mm:02d}:{ss:02d}")
                    next_log = now + (1.0 if remaining <= 5 else 10.0)
                time.sleep(min(PROFILE_BATCH_PAUSE_CHECK_SEC, remaining))

        def _run_batch(batch_items: list) -> None:
            if not batch_items or self.stop_event.is_set():
                return

            self._profile_retry_round = 0
            with self.profile_failed_lock:
                self.profile_failed_accounts = []

            try:
                screen_w = self.root.winfo_screenwidth()
                screen_h = self.root.winfo_screenheight()
            except Exception:
                screen_w, screen_h = 1920, 1080

            gap = 6
            taskbar_h = 40
            usable_w = screen_w - (gap * 2)
            usable_h = (screen_h - taskbar_h) - (gap * 2)
            active_count = len(batch_items)
            cols = min(5, active_count)
            rows_layout = min(2, max(1, math.ceil(active_count / cols)))
            win_w = int((usable_w - gap * (cols - 1)) / cols)
            win_h = int((usable_h - gap * (rows_layout - 1)) / rows_layout)
            win_w = max(150, min(280, win_w))
            win_h = max(420, min(600, win_h))

            slot_idx = 0
            max_slots = cols * rows_layout
            self.executor = ThreadPoolExecutor(max_workers=max_threads)
            self.profile_semaphore = threading.BoundedSemaphore(max_threads)
            futures = []
            for item_id, acc in batch_items:
                if self.stop_event.is_set():
                    break
                pos = slot_idx % max_slots
                col = pos % cols
                row = pos // cols
                x = gap + col * (win_w + gap)
                y = gap + row * (win_h + gap)
                win_pos = f"{x},{y}"
                win_size = f"{win_w},{win_h}"
                futures.append(self.executor.submit(self._profile_open_worker, item_id, acc, win_pos, win_size))
                slot_idx += 1
                if PROFILE_BATCH_STAGGER_SEC > 0:
                    time.sleep(PROFILE_BATCH_STAGGER_SEC)

            for f in as_completed(futures):
                try:
                    f.result()
                except Exception:
                    pass

    def _reset_batch_pause_state(self, lane: str) -> None:
        key = (lane or "").upper()
        with self._batch_pause_lock:
            self._batch_pause_state[key] = {"started": 0, "release_at": 0.0}

    def _wait_batch_pause_if_needed(self, lane: str) -> bool:
        if PROFILE_BATCH_SIZE <= 0 or PROFILE_BATCH_PAUSE_SEC <= 0:
            return True

        key = (lane or "").upper()
        with self._batch_pause_lock:
            state = self._batch_pause_state.setdefault(key, {"started": 0, "release_at": 0.0})
            state["started"] += 1
            started = state["started"]
            if started > 1 and (started - 1) % PROFILE_BATCH_SIZE == 0:
                now = time.time()
                state["release_at"] = max(now, state["release_at"]) + PROFILE_BATCH_PAUSE_SEC
                self._log(
                    f"[{key} BATCH] Reached {started - 1} profiles, pause {PROFILE_BATCH_PAUSE_SEC}s"
                )
            release_at = state["release_at"]

        next_log = 0.0
        while True:
            wait_s = release_at - time.time()
            if wait_s <= 0:
                return not self.stop_event.is_set()
            if self.stop_event.is_set():
                return False
            now = time.time()
            if wait_s <= 5 or now >= next_log:
                mm = int(wait_s) // 60
                ss = int(wait_s) % 60
                self._log(f"[{key} BATCH] Resume in {mm:02d}:{ss:02d}")
                next_log = now + (1.0 if wait_s <= 5 else 10.0)
            time.sleep(min(PROFILE_BATCH_PAUSE_CHECK_SEC, wait_s))

            try:
                self.executor.shutdown(wait=True)
            except Exception:
                pass
            self.executor = None

            with self.profile_failed_lock:
                failed_list = self.profile_failed_accounts.copy()
                self.profile_failed_accounts = []

            while failed_list and not self.stop_event.is_set():
                if self._profile_retry_round >= 3:
                    self._log(f"[PROFILE RETRY] Stop retry after 3 rounds (remaining: {len(failed_list)})")
                    break
                self._profile_retry_round += 1
                self._log(
                    f"[PROFILE RETRY] Retrying {len(failed_list)} failed accounts (round {self._profile_retry_round}/3)..."
                )

                self.executor = ThreadPoolExecutor(max_workers=max_threads)
                futures = []
                active_count = len(failed_list)
                cols = min(5, active_count)
                rows_layout = max(1, (active_count + cols - 1) // cols)
                win_w = int((usable_w - gap * (cols - 1)) / cols)
                win_h = int((usable_h - gap * (rows_layout - 1)) / rows_layout)
                win_w = max(150, min(280, win_w))
                win_h = max(420, min(600, win_h))
                for idx, (item_id, acc) in enumerate(failed_list):
                    if self.stop_event.is_set():
                        break
                    pos = idx % (cols * rows_layout)
                    col = pos % cols
                    row = pos // cols
                    x = gap + col * (win_w + gap)
                    y = gap + row * (win_h + gap)
                    retry_win_pos = f"{x},{y}"
                    retry_win_size = f"{win_w},{win_h}"
                    futures.append(self.executor.submit(self._profile_open_worker, item_id, acc, retry_win_pos, retry_win_size))
                    if PROFILE_BATCH_STAGGER_SEC > 0:
                        time.sleep(PROFILE_BATCH_STAGGER_SEC)

                for f in as_completed(futures):
                    try:
                        f.result()
                    except Exception:
                        pass

                try:
                    self.executor.shutdown(wait=True)
                except Exception:
                    pass
                self.executor = None

                with self.profile_failed_lock:
                    failed_list = self.profile_failed_accounts.copy()
                    self.profile_failed_accounts = []

            self._clear_profile_failed_log()

        def _batch_runner():
            try:
                items = []
                email_to_iid = self._map_email_to_item_id(self.profile_tree)
                for acc in self.profile_accounts:
                    email = (acc.get("uid") or "").strip()
                    if email in checked_emails:
                        item_id = email_to_iid.get(email)
                        if item_id:
                            items.append((item_id, acc))

                if not items:
                    return

                total = len(items)
                batch_size = max(1, int(PROFILE_BATCH_SIZE))
                for start_idx in range(0, total, batch_size):
                    if self.stop_event.is_set():
                        break
                    batch = items[start_idx : start_idx + batch_size]
                    batch_no = (start_idx // batch_size) + 1
                    total_batches = math.ceil(total / batch_size)
                    self._log(f"[PROFILE BATCH] Start batch {batch_no}/{total_batches} ({len(batch)} profiles)")
                    _run_batch(batch)
                    if self.stop_event.is_set():
                        break
                    if start_idx + batch_size < total:
                        self._log(f"[PROFILE BATCH] Pause {PROFILE_BATCH_PAUSE_SEC}s before next batch")
                        _sleep_with_stop(PROFILE_BATCH_PAUSE_SEC)
                self._log("[PROFILE BATCH] Done")
            finally:
                self._profile_batch_running = False
                self._reset_run("profile")

        threading.Thread(target=_batch_runner, daemon=True).start()


    def start_jobs(self) -> None:
        if self._is_profile_tab():
            self.start_profile_jobs()
            return
        if self._is_fb_profile_tab():
            self.start_fb_profile_jobs()
            return
        if self._is_fb_tab():
            self.start_fb_jobs()
            return
        if self.executor is not None:
            return
        self._reset_all_statuses()
        self._clear_all_logs()
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

        self._fixed_threads = max_threads
        self.stop_event.clear()
        self._reset_batch_pause_state("YTB")
        self._clear_status_tags()
        self._retry_round = 0
        # Clear failed accounts list at start of new cycle
        with self.failed_accounts_lock:
            self.failed_accounts = []
        
        # Use exact number of threads (no extra retry threads)
        self.executor = ThreadPoolExecutor(max_workers=max_threads)
        self.login_semaphore = threading.BoundedSemaphore(max_threads)
        self.upload_retry_semaphore = threading.BoundedSemaphore(max_threads)

        self._reset_upload_tree_order()
        pending = self._resume_pending.get("upload") or set()
        if pending:
            if self._prompt_resume("upload", len(pending)):
                checked_emails = pending
            else:
                self._resume_pending["upload"] = set()
                checked_emails = self._get_checked_email_set(self.tree)
        else:
            checked_emails = self._get_checked_email_set(self.tree)
        if not checked_emails:
            messagebox.showinfo("Thong bao", "Khong co profile nao duoc tick.")
            return
        self._set_run_total("upload", len(checked_emails))

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
        active_count = len(checked_emails)
        
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
        email_to_iid = self._map_email_to_item_id(self.tree)
        for acc in self.accounts:
            email = (acc.get("uid") or "").strip()
            if email not in checked_emails:
                continue
            item_id = email_to_iid.get(email)
            if not item_id:
                continue
            self._bind_item_email(item_id, acc.get("uid", ""))
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
            try:
                failed_list.extend(self._collect_transient_failures())
            except Exception:
                pass
            
            self.executor = None
            
            # If failed accounts exist, retry them immediately (only during run)
            if failed_list and not self.stop_event.is_set():
                if self._retry_round < 3:
                    self._retry_round += 1
                    self._log(f"[RETRY] Retrying {len(failed_list)} failed accounts (round {self._retry_round}/3)...")
                    # Don't use the last loop's win_pos/win_size; let _retry_failed_accounts calculate its own layout
                    self.root.after(1000, lambda fl=failed_list: self._retry_failed_accounts(fl, max_threads, max_videos))
                    return
                self._log(f"[RETRY] Stop retry after 3 rounds (remaining: {len(failed_list)})")
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
            self._reset_run("upload")

        threading.Thread(target=_waiter, daemon=True).start()

    def _do_repeat_cycle(self) -> None:
        """Repeat cycle for smooth continuous upload without recalculating layout"""
        if self.executor is not None:
            return
        
        try:
            max_threads = int(self._fixed_threads or int(self.entry_threads.get()))
            if max_threads <= 0:
                raise ValueError
        except Exception:
            return

        # Get checked items (should still be checked from previous run)
        checked_emails = self._get_checked_email_set(self.tree)
        if not checked_emails:
            return
        self._set_run_total("upload", len(checked_emails))

        # Clear executor state
        self.stop_event.clear()
        self._reset_batch_pause_state("YTB")
        self._clear_status_tags()
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
        active_count = len(checked_emails)

        cols = min(5, active_count)
        rows_layout = min(2, max(1, math.ceil(active_count / cols)))

        win_w = int((usable_w - gap * (cols - 1)) / cols)
        win_h = int((usable_h - gap * (rows_layout - 1)) / rows_layout)

        win_w = max(150, min(280, win_w))
        win_h = max(420, min(600, win_h))

        futures = []
        slot_idx = 0
        max_slots = cols * rows_layout

        self._log(f"\n[REPEAT] Starting repeat cycle... (checked: {len(checked_emails)} accounts)")

        email_to_iid = self._map_email_to_item_id(self.tree)
        for acc in self.accounts:
            email = (acc.get("uid") or "").strip()
            if email not in checked_emails:
                continue
            item_id = email_to_iid.get(email)
            if not item_id:
                continue
            self._bind_item_email(item_id, acc.get("uid", ""))
            
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
            try:
                failed_list.extend(self._collect_transient_failures())
            except Exception:
                pass

            self.executor = None

            # Retry failed accounts
            if failed_list and not self.stop_event.is_set():
                if self._retry_round < 3:
                    self._retry_round += 1
                    self._log(f"[RETRY] Retrying {len(failed_list)} failed accounts (round {self._retry_round}/3)...")
                    self.root.after(1000, lambda fl=failed_list: self._retry_failed_accounts(fl, max_threads, max_videos))
                    return
                self._log(f"[RETRY] Stop retry after 3 rounds (remaining: {len(failed_list)})")

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
            self._reset_run("upload")

        threading.Thread(target=_repeat_waiter, daemon=True).start()

    def start_scan(self) -> None:
        if self._is_fb_profile_tab():
            self._log("[FB PROFILE] Khong co scan o tab nay.")
            return
        if self._is_fb_tab():
            self.start_fb_scan()
            return
        if self.executor is not None:
            return

        try:
            max_threads = int(self.entry_threads.get())
            if max_threads <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Loi", "So luong phai > 0")
            return

        checked_emails = self._get_checked_email_set(self.tree)
        if not checked_emails:
            messagebox.showinfo("Thong bao", "Khong co profile nao duoc tick.")
            return

        self.stop_event.clear()
        self.executor = ThreadPoolExecutor(max_workers=max_threads)

        futures = []
        email_to_iid = self._map_email_to_item_id(self.tree)
        for acc in self.accounts:
            email = (acc.get("uid") or "").strip()
            if email not in checked_emails:
                continue
            item_id = email_to_iid.get(email)
            if not item_id:
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

    def start_fb_scan(self) -> None:
        if self.executor is not None:
            return
        try:
            max_threads = int(self.entry_threads.get())
            if max_threads <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Loi", "So luong phai > 0")
            return

        pending = self._resume_pending.get("fb") or set()
        if pending:
            if self._prompt_resume("fb", len(pending)):
                checked_emails = pending
            else:
                self._resume_pending["fb"] = set()
                checked_emails = self._get_checked_email_set(self.fb_tree)
        else:
            checked_emails = self._get_checked_email_set(self.fb_tree)
        if not checked_emails:
            messagebox.showinfo("Thong bao", "Khong co profile nao duoc tick.")
            return

        self.stop_event.clear()
        self._reorder_tree_by_accounts(self.fb_tree, self.fb_accounts)
        selected = []
        email_to_item = {}
        email_to_iid = self._map_email_to_item_id(self.fb_tree)
        for acc in self.fb_accounts:
            email = (acc.get("uid") or "").strip()
            if email not in checked_emails:
                continue
            item_id = email_to_iid.get(email)
            if not item_id:
                continue
            selected.append(acc)
            if email:
                email_to_item[email] = item_id
                self._set_fb_status(item_id, "QUEUED")

        def _on_status(email: str, status: str) -> None:
            item_id = email_to_item.get((email or "").strip())
            if not item_id:
                return
            self._set_fb_status(item_id, status)

        def _runner():
            scan_facebook_reels_multi(
                selected,
                stop_check=lambda: self.stop_event.is_set(),
                logger=self._log,
                cookie_file=os.path.join(_THIS_DIR, "cookiefb.txt"),
                max_workers=2,
                on_status=_on_status,
            )

        self.executor = ThreadPoolExecutor(max_workers=1)
        fut = self.executor.submit(_runner)

        def _waiter():
            try:
                fut.result()
            except Exception as e:
                self._log(f"[FB SCAN] ERR: {e}")
            finally:
                try:
                    self.executor.shutdown(wait=False)
                except Exception:
                    pass
                self.executor = None

        threading.Thread(target=_waiter, daemon=True).start()

    def _fb_scan_worker(self, item_id: str, acc: dict) -> None:
        if self.stop_event.is_set():
            return
        reels_url = (acc.get("facebook") or "").strip()
        if not reels_url:
            self._log(f"[{acc['uid']}] FB SCAN SKIP: No reels URL")
            return
        self._set_fb_status(item_id, "SCAN...")
        self._log(f"[{acc['uid']}] FB SCAN START")
        total, added = scan_facebook_reels_for_email(
            acc["uid"],
            reels_url,
            lambda: self.stop_event.is_set(),
            self._log,
            cookie_file=os.path.join(_THIS_DIR, "cookiefb.txt"),
        )
        self._set_fb_status(item_id, f"SCAN OK ({added})")
        self._log(f"[{acc['uid']}] FB SCAN OK: added {added}, total {total}")

    def start_fb_profile_jobs(self) -> None:
        if self.executor is not None:
            return
        self._reset_all_statuses()
        self._clear_all_logs()
        try:
            max_threads = int(self.entry_threads.get())
            if max_threads <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Loi", "So luong phai > 0")
            return

        pending = self._resume_pending.get("fb_profile") or set()
        if pending:
            if self._prompt_resume("fb_profile", len(pending)):
                checked_emails = pending
            else:
                self._resume_pending["fb_profile"] = set()
                checked_emails = self._get_checked_email_set(self.fb_profile_tree)
        else:
            checked_emails = self._get_checked_email_set(self.fb_profile_tree)
        if not checked_emails:
            messagebox.showinfo("Thong bao", "Khong co profile nao duoc tick.")
            return
        self._set_run_total("fb_profile", len(checked_emails))

        self._fixed_threads = max_threads
        self.stop_event.clear()
        self.executor = ThreadPoolExecutor(max_workers=max_threads)
        self.profile_semaphore = threading.BoundedSemaphore(max_threads)

        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
        except Exception:
            screen_w, screen_h = 1920, 1080
        gap = 6
        taskbar_h = 40
        usable_w = screen_w - (gap * 2)
        usable_h = (screen_h - taskbar_h) - (gap * 2)
        active_count = len(checked_emails)
        cols = min(5, active_count)
        rows_layout = min(2, max(1, math.ceil(active_count / cols)))
        win_w = int((usable_w - gap * (cols - 1)) / cols)
        win_h = int((usable_h - gap * (rows_layout - 1)) / rows_layout)
        win_w = max(150, min(280, win_w))
        win_h = max(420, min(600, win_h))

        futures = []
        slot_idx = 0
        max_slots = cols * rows_layout
        email_to_iid = self._map_email_to_item_id(self.fb_profile_tree)
        for acc in self.fb_profile_accounts:
            email = (acc.get("uid") or "").strip()
            if email not in checked_emails:
                continue
            item_id = email_to_iid.get(email)
            if not item_id:
                continue
            pos = slot_idx % max_slots
            col = pos % cols
            row = pos // cols
            x = gap + col * (win_w + gap)
            y = gap + row * (win_h + gap)
            win_pos = f"{x},{y}"
            win_size = f"{win_w},{win_h}"
            futures.append(self.executor.submit(self._fb_profile_worker, item_id, acc, win_pos, win_size))
            slot_idx += 1

        def _waiter():
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception:
                    pass
            self.executor = None
            self._reset_run("fb_profile")

        threading.Thread(target=_waiter, daemon=True).start()

    def _fb_profile_worker(self, item_id: str, acc: dict, win_pos: str, win_size: str) -> None:
        sem = self.profile_semaphore
        if sem:
            sem.acquire()
        if self.stop_event.is_set():
            if sem:
                sem.release()
            return
        profile_id = None
        started = False
        email = (acc.get("uid") or "").strip()
        try:
            started = True
            fb_url = (acc.get("facebook") or "").strip()
            if not fb_url:
                self._set_fb_profile_status(item_id, "FB LINK ERR")
                return

            self._set_fb_profile_status(item_id, "CREATE...")
            ok_c = False
            data_c = {}
            msg_c = ""
            with self.create_lock:
                for attempt in range(3):
                    ok_c, data_c, msg_c = create_profile(acc["uid"], acc["proxy"], SCOOPZ_URL)
                    if ok_c:
                        break
                    self._set_fb_profile_status(item_id, f"CREATE RETRY {attempt+1}/3")
                    time.sleep(3 + attempt)
            if not ok_c:
                self._set_fb_profile_status(item_id, f"CREATE ERR: {msg_c}")
                return

            if isinstance(data_c, dict):
                profile_id = (data_c.get("data") or {}).get("id") or data_c.get("id") or data_c.get("profile_id")
            if not profile_id:
                self._set_fb_profile_status(item_id, "NO PROFILE ID")
                return
            self._remember_profile_path(profile_id, data_c)
            self.created_profiles.add(profile_id)

            self._set_fb_profile_status(item_id, "START...")
            ok_s, data_s, msg_s = start_profile(profile_id, win_pos=win_pos, win_size=win_size)
            if not ok_s:
                if self._is_proxy_error(msg_s):
                    try:
                        close_profile(profile_id, 3)
                        delete_profile(profile_id, 10)
                    except Exception:
                        pass
                    try:
                        self.created_profiles.discard(profile_id)
                    except Exception:
                        pass
                    self._delete_profile_path(profile_id)
                    new_id, new_data_s, _err = self._retry_start_profile_with_new_proxy(
                        acc,
                        item_id,
                        "fb_profile",
                        self.fb_profile_tree,
                        lambda s: self._set_fb_profile_status(item_id, s),
                        win_pos=win_pos,
                        win_size=win_size,
                        created_set="created_profiles",
                    )
                    if new_id and new_data_s:
                        profile_id = new_id
                        data_s = new_data_s
                        ok_s = True
                    else:
                        self._set_fb_profile_status(item_id, f"START ERR: {msg_s}")
                        return
                else:
                    self._set_fb_profile_status(item_id, f"START ERR: {msg_s}")
                    return
            driver_path, remote = extract_driver_info(data_s)
            if not (driver_path and remote):
                self._set_fb_profile_status(item_id, "STARTED (no debug)")
                return

            self._set_fb_profile_status(item_id, "LOGIN...")
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
                self._set_fb_profile_status(item_id, self._format_login_error(err_login))
                return
            if self.stop_event.is_set():
                return

            self._set_fb_profile_status(item_id, "LOGIN OK")
            self._set_fb_profile_status(item_id, "FB FETCH...")
            fb_name, fb_username, avatar_path = fetch_facebook_profile_assets_local(fb_url, self._log)
            if not (fb_name and fb_username and avatar_path and os.path.exists(avatar_path)):
                self._set_fb_profile_status(item_id, "FB FETCH ERR")
                return
            self._save_profile_assets(acc["uid"], fb_name, fb_username, avatar_path)

            self._set_fb_profile_status(item_id, "OPEN PROFILE...")
            self._set_fb_profile_status(item_id, "WAIT UPDATE...")
            ok_pf = False
            err_pf = ""
            with self.profile_update_lock:
                for attempt in range(1, 4):
                    if self.stop_event.is_set():
                        return
                    self._set_fb_profile_status(item_id, f"OPEN PROFILE... ({attempt}/3)")
                    ok_pf, err_pf = open_profile_in_scoopz(
                        driver_path,
                        remote,
                        avatar_path,
                        fb_name,
                        fb_username,
                        logger=self._log,
                        max_retries=3,
                    )
                    if ok_pf:
                        break
                    retryable = (
                        "cannot connect to chrome" in (err_pf or "").lower()
                        or "profile link not found" in (err_pf or "").lower()
                        or "profile page load timeout" in (err_pf or "").lower()
                        or "dialog busy" in (err_pf or "").lower()
                    )
                    if not retryable:
                        break
                    wait_s = 2 + attempt * 2
                    self._log(f"[{acc['uid']}] FB PROFILE RETRY {attempt}/3 in {wait_s}s: {err_pf}")
                    time.sleep(wait_s)
            if not ok_pf:
                self._set_fb_profile_status(item_id, f"PROFILE ERR: {err_pf}")
                return
            self._set_fb_profile_status(item_id, "PROFILE OPENED")
            self._set_fb_profile_status(item_id, "DONE")
        finally:
            if started:
                self._mark_run_done("fb_profile", email)
            if sem:
                try:
                    sem.release()
                except Exception:
                    pass
            try:
                if profile_id:
                    close_profile(profile_id, 3)
                    delete_profile(profile_id, 10)
            except Exception:
                pass
            try:
                if profile_id:
                    self.created_profiles.discard(profile_id)
            except Exception:
                pass
            if profile_id:
                self._delete_profile_path(profile_id)
                self._track_profile_cleanup()

    def start_fb_jobs(self) -> None:
        if self.executor is not None:
            return
        self._reset_all_statuses()
        self._clear_all_logs()
        try:
            max_threads = int(self.entry_threads.get())
            if max_threads <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Loi", "So luong phai > 0")
            return
        try:
            max_videos = int(self.entry_videos.get())
            if max_videos <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Loi", "Videos phai > 0")
            return

        self._fixed_threads = max_threads
        checked_emails = self._get_checked_email_set(self.fb_tree)
        if not checked_emails:
            messagebox.showinfo("Thong bao", "Khong co profile nao duoc tick.")
            return
        self._set_run_total("fb", len(checked_emails))

        self.stop_event.clear()
        self._reset_batch_pause_state("FB")
        self._retry_round = 0
        with self.failed_accounts_lock:
            self.failed_accounts = []
        self.executor = ThreadPoolExecutor(max_workers=max_threads)
        self.login_semaphore = threading.BoundedSemaphore(max_threads)
        self.upload_retry_semaphore = threading.BoundedSemaphore(max_threads)

        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
        except Exception:
            screen_w, screen_h = 1920, 1080

        gap = 6
        taskbar_h = 40
        usable_w = screen_w - (gap * 2)
        usable_h = (screen_h - taskbar_h) - (gap * 2)
        active_count = len(checked_emails)
        cols = min(5, active_count)
        rows_layout = min(2, max(1, math.ceil(active_count / cols)))
        win_w = int((usable_w - gap * (cols - 1)) / cols)
        win_h = int((usable_h - gap * (rows_layout - 1)) / rows_layout)
        win_w = max(150, min(280, win_w))
        win_h = max(420, min(600, win_h))

        futures = []
        slot_idx = 0
        max_slots = cols * rows_layout
        self._reorder_tree_by_accounts(self.fb_tree, self.fb_accounts)
        email_to_iid = self._map_email_to_item_id(self.fb_tree)
        for acc in self.fb_accounts:
            email = (acc.get("uid") or "").strip()
            if email not in checked_emails:
                continue
            item_id = email_to_iid.get(email)
            if not item_id:
                continue
            self._bind_item_email(item_id, acc.get("uid", ""))
            pos = slot_idx % max_slots
            col = pos % cols
            row = pos // cols
            x = gap + col * (win_w + gap)
            y = gap + row * (win_h + gap)
            win_pos = f"{x},{y}"
            win_size = f"{win_w},{win_h}"
            futures.append(self.executor.submit(self._fb_worker_one, item_id, acc, win_pos, win_size, max_videos))
            slot_idx += 1

        def _waiter():
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
                    self._log(f"[FB RETRY] Retrying {len(failed_list)} failed accounts (round {self._retry_round}/3)...")
                    self.root.after(
                        1000,
                        lambda fl=failed_list: self._retry_failed_fb_accounts(fl, max_threads, max_videos),
                    )
                    return
                self._log(f"[FB RETRY] Stop retry after 3 rounds (remaining: {len(failed_list)})")
            self._clear_failed_log()
            self._reset_run("fb")

        threading.Thread(target=_waiter, daemon=True).start()

    def _retry_failed_fb_accounts(self, failed_accounts: list, max_threads: int, max_videos: int) -> None:
        if self.stop_event.is_set():
            return

        self._log(f"[FB RETRY] Retrying {len(failed_accounts)} failed accounts...")
        try:
            for item_id, _acc in failed_accounts:
                self._set_fb_status(item_id, f"RETRY {self._retry_round}/3")
        except Exception:
            pass

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
            self._bind_item_email(item_id, acc.get("uid", ""))
            pos = idx % (cols * rows_layout)
            col = pos % cols
            row = pos // cols
            x = gap + col * (win_w + gap)
            y = gap + row * (win_h + gap)
            retry_win_pos = f"{x},{y}"
            retry_win_size = f"{win_w},{win_h}"
            futures.append(self.executor.submit(self._fb_worker_one, item_id, acc, retry_win_pos, retry_win_size, max_videos))

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
                    self._log(
                        f"[FB RETRY] Retrying {len(failed_list)} failed accounts (round {self._retry_round}/3)..."
                    )
                    self.root.after(
                        1000,
                        lambda fl=failed_list: self._retry_failed_fb_accounts(fl, max_threads, max_videos),
                    )
                    return
                self._log(f"[FB RETRY] Stop retry after 3 rounds (remaining: {len(failed_list)})")
            self._clear_failed_log()
            self._reset_run("fb")

        threading.Thread(target=_retry_waiter, daemon=True).start()

    def _fb_worker_one(self, item_id: str, acc: dict, win_pos: str, win_size: str, max_videos: int) -> None:
        email = (acc.get("uid") or "").strip()
        started = False
        try:
            if self.stop_event.is_set():
                return
            if not self._wait_batch_pause_if_needed("FB"):
                return
            started = True
            profile_id = None
            max_file_size_bytes = 100 * 1024 * 1024
    
            def _extract_fb_video_id(text: str) -> str:
                val = (text or "").strip()
                if not val:
                    return ""
                m = re.search(r"/reel/(\d+)", val)
                if m:
                    return m.group(1)
                return ""
    
            self._log(f"[{acc['uid']}] FB START")
            self._set_fb_status(item_id, "CREATE...")
            ok_c = False
            data_c = {}
            msg_c = ""
            with self.create_lock:
                for attempt in range(3):
                    ok_c, data_c, msg_c = create_profile(acc["uid"], acc["proxy"], SCOOPZ_URL)
                    if ok_c:
                        break
                    wait_s = 5 + attempt * 3
                    self._set_fb_status(item_id, f"CREATE RETRY {attempt+1}/3")
                    self._log(f"[{acc['uid']}] CREATE ERR: {msg_c} | retry in {wait_s}s")
                    time.sleep(wait_s)
            if not ok_c:
                self._set_fb_status(item_id, f"CREATE ERR: {msg_c}")
                self._record_failed(item_id, acc, f"CREATE ERR: {msg_c}")
                return
    
            profile_id = None
            if isinstance(data_c, dict):
                profile_id = (data_c.get("data") or {}).get("id") or data_c.get("id") or data_c.get("profile_id")
            if not profile_id:
                self._set_fb_status(item_id, "NO PROFILE ID")
                self._record_failed(item_id, acc, "NO PROFILE ID")
                return
            self._remember_profile_path(profile_id, data_c)
            self.created_profiles.add(profile_id)
    
            self._set_fb_status(item_id, "START...")
            ok_s, data_s, msg_s = start_profile(profile_id, win_pos=win_pos, win_size=win_size)
            if not ok_s:
                if self._is_proxy_error(msg_s):
                    try:
                        close_profile(profile_id, 3)
                        delete_profile(profile_id, 10)
                    except Exception:
                        pass
                    try:
                        self.created_profiles.discard(profile_id)
                    except Exception:
                        pass
                    self._delete_profile_path(profile_id)
                    new_id, new_data_s, _err = self._retry_start_profile_with_new_proxy(
                        acc,
                        item_id,
                        "fb",
                        self.fb_tree,
                        lambda s: self._set_fb_status(item_id, s),
                        win_pos=win_pos,
                        win_size=win_size,
                        created_set="created_profiles",
                    )
                    if new_id and new_data_s:
                        profile_id = new_id
                        data_s = new_data_s
                        ok_s = True
                    else:
                        self._set_fb_status(item_id, f"START ERR: {msg_s}")
                        self._record_failed(item_id, acc, f"START ERR: {msg_s}")
                        return
                else:
                    self._set_fb_status(item_id, f"START ERR: {msg_s}")
                    self._record_failed(item_id, acc, f"START ERR: {msg_s}")
                    return
    
            with self.active_lock:
                self.active_profiles[item_id] = profile_id
            driver_path, remote = extract_driver_info(data_s)
            status = "STARTED" if driver_path and remote else "STARTED (no debug)"
            self._set_fb_status(item_id, status)
    
            if not (driver_path and remote):
                self._record_failed(item_id, acc, "STARTED (no debug)")
                return
    
            self._set_fb_status(item_id, "LOGIN...")
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
                self._set_fb_status(item_id, status)
                self._record_failed(item_id, acc, status)
                return
    
            self._set_fb_status(item_id, "LOGIN OK")
            success_count = 0
            safety_guard = 0
            while success_count < max_videos:
                if self.stop_event.is_set():
                    break
                safety_guard += 1
                if safety_guard > max_videos * 5:
                    break
    
                self.operation_delayer.delay_before_download(acc["uid"], self._log_progress)
                ok_next, row = get_next_unuploaded(acc["uid"])
                if not ok_next:
                    self._set_fb_status(item_id, "HẾT VIDEO")
                    break
                row_url = (row.get("url") or "").strip()
                row_id = (row.get("video_id") or "").strip()
                if not row_url:
                    if row_id.startswith("http"):
                        row_url = row_id
                    elif row_id:
                        row_url = f"https://www.facebook.com/reel/{row_id}"
                if not row_url:
                    break
    
                self._set_fb_status(item_id, f"DOWNLOAD {success_count+1}/{max_videos}...")
                retry_dl = 0
                skip_current = False
                skip_account = False
                ok_dl = False
                path_or_err = ""
                vid_id = ""
                title = ""
                while True:
                    ok_dl, path_or_err, vid_id, title = download_one_facebook(
                        acc["uid"],
                        row_url,
                        self._log_progress,
                        cookie_path=os.path.join(_THIS_DIR, "cookiefb.txt"),
                        timeout_s=120,
                    )
                    if ok_dl:
                        break
                    err_text = str(path_or_err)
                    lower = err_text.lower()
                    is_timeout = "timeout" in lower or "timed out" in lower
                    if is_timeout:
                        if retry_dl < 1:
                            retry_dl += 1
                            self._log(f"[{acc['uid']}] FB DOWNLOAD TIMEOUT - RETRY 1/1")
                            continue
                        self._log(f"[{acc['uid']}] FB DOWNLOAD TIMEOUT - SKIP ACCOUNT")
                        self._set_fb_status(item_id, "DOWNLOAD TIMEOUT")
                        self._record_failed(item_id, acc, "DOWNLOAD TIMEOUT")
                        skip_account = True
                        break
                    break
                mark_id = vid_id or row_id or _extract_fb_video_id(row_url)
                if not ok_dl:
                    err_text = str(path_or_err)
                    lower = err_text.lower()
                    if "video skipped" in lower or "private" in lower or "isn't available" in lower:
                        try:
                            mark_uploaded(acc["uid"], mark_id)
                        except Exception:
                            pass
                        continue
                    if skip_account:
                        break
                    if skip_current:
                        continue
                    self._set_fb_status(item_id, f"DOWNLOAD ERR: {err_text}")
                    self._record_failed(item_id, acc, f"DOWNLOAD ERR: {err_text}")
                    break
    
                if vid_id and title:
                    try:
                        update_title_if_empty(acc["uid"], vid_id, title)
                    except Exception:
                        pass
                try:
                    if os.path.exists(path_or_err):
                        file_size = os.path.getsize(path_or_err)
                        if file_size > max_file_size_bytes:
                            self._log(
                                f"[{acc['uid']}] SKIP BIG FILE: {file_size / (1024 * 1024):.1f}MB > 100MB"
                            )
                            try:
                                mark_uploaded(acc["uid"], mark_id)
                            except Exception:
                                pass
                            self._delete_uploaded_video(path_or_err, acc["uid"])
                            continue
                except Exception:
                    pass
                caption = title or ""
                self.operation_delayer.delay_before_upload(acc["uid"], self._log_progress)
                with self.upload_retry_semaphore:
                    ok_p = False
                    drv = None
                    up_status = ""
                    up_msg = ""
                    token = self._enqueue_upload_turn()
                    if not self._wait_upload_turn(token):
                        return
                    try:
                        for attempt in range(3):
                            if self.stop_event.is_set():
                                break
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
                            if ok_p:
                                break
                            if up_status in ("dialog_lock_timeout", "caption_error", "dialog_error", "timeout", "unexpected_error", "error") and attempt < 2:
                                time.sleep(2 + attempt)
                                continue
                            break
                    finally:
                        self._release_upload_turn(token)
    
                if not ok_p:
                    self._set_fb_status(item_id, f"UPLOAD ERR: {up_msg or up_status}")
                    self._record_failed(item_id, acc, f"UPLOAD ERR: {up_msg or up_status}")
                    break
    
                self._set_fb_status(item_id, f"POSTING {success_count+1}/{max_videos}...")
                st, msg, _purl, _foll = upload_post_async(
                    drv,
                    self._log,
                    max_total_s=180,
                    post_button_semaphore=self.post_button_semaphore,
                )
                if st == "success":
                    try:
                        mark_uploaded(acc["uid"], mark_id)
                    except Exception:
                        pass
                    self._set_fb_status(item_id, "UPLOAD OK")
                    self._delete_uploaded_video(path_or_err, acc["uid"])
                    success_count += 1
                else:
                    err_text = msg or st
                    self._set_fb_status(item_id, f"UPLOAD ERR: {err_text}")
                    self._record_failed(item_id, acc, f"UPLOAD ERR: {err_text}")
                    break
    
            try:
                if profile_id:
                    close_profile(profile_id, 3)
                    delete_profile(profile_id, 10)
            except Exception:
                pass
            try:
                if profile_id:
                    self.created_profiles.discard(profile_id)
            except Exception:
                pass
            if profile_id:
                self._delete_profile_path(profile_id)
                self._track_profile_cleanup()
            try:
                with self.active_lock:
                    self.active_profiles.pop(item_id, None)
            except Exception:
                pass
        finally:
            if started:
                self._mark_run_done("fb", email)
    def _retry_failed_accounts(self, failed_accounts: list, max_threads: int, max_videos: int) -> None:
        """Retry failed accounts with new threads"""
        if self.stop_event.is_set():
            return
        
        self._log(f"[RETRY] Retrying {len(failed_accounts)} failed accounts (max {max_threads} threads)...")
        self._clear_status_tags()
        try:
            for item_id, _acc in failed_accounts:
                self._set_status(item_id, f"RETRY {self._retry_round}/3")
        except Exception:
            pass
        
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
            self._bind_item_email(item_id, acc.get("uid", ""))
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
            try:
                failed_list.extend(self._collect_transient_failures())
            except Exception:
                pass
            if failed_list and not self.stop_event.is_set():
                if self._retry_round < 3:
                    self._retry_round += 1
                    self._log(f"[RETRY] Retrying {len(failed_list)} failed accounts (round {self._retry_round}/3)...")
                    self.root.after(1000, lambda fl=failed_list: self._retry_failed_accounts(fl, max_threads, max_videos))
                    return
                self._log(f"[RETRY] Stop retry after 3 rounds (remaining: {len(failed_list)})")
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
        self._remember_profile_path(profile_id, data_c)
        self.created_profiles.add(profile_id)

        self._set_status(item_id, "START...", profile_id=profile_id)
        ok_s, data_s, msg_s = start_profile(profile_id)
        if not ok_s:
            if self._is_proxy_error(msg_s):
                try:
                    close_profile(profile_id, 3)
                    delete_profile(profile_id, 10)
                except Exception:
                    pass
                try:
                    self.created_profiles.discard(profile_id)
                except Exception:
                    pass
                self._delete_profile_path(profile_id)
                new_id, new_data_s, _err = self._retry_start_profile_with_new_proxy(
                    acc,
                    item_id,
                    "upload",
                    self.tree,
                    lambda s: self._set_status(item_id, s),
                    win_pos=None,
                    win_size=None,
                    created_set="created_profiles",
                )
                if new_id and new_data_s:
                    profile_id = new_id
                    data_s = new_data_s
                    ok_s = True
                else:
                    self._set_status(item_id, f"START ERR: {msg_s}")
                    self._log(f"[{acc['uid']}] START ERR: {msg_s}")
                    self._record_failed(item_id, acc, f"START ERR: {msg_s}")
                    return None, None, None
            else:
                self._set_status(item_id, f"START ERR: {msg_s}")
                self._log(f"[{acc['uid']}] START ERR: {msg_s}")
                self._record_failed(item_id, acc, f"START ERR: {msg_s}")
                return None, None, None

        driver_path, remote = extract_driver_info(data_s)
        if not driver_path or not remote:
            self._set_status(item_id, "STARTED (no debug)")
            try:
                close_profile(profile_id, 3)
                delete_profile(profile_id, 10)
            except Exception:
                pass
            try:
                self.created_profiles.discard(profile_id)
            except Exception:
                pass
            self._delete_profile_path(profile_id)
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
            try:
                close_profile(profile_id, 3)
                delete_profile(profile_id, 10)
            except Exception:
                pass
            try:
                self.created_profiles.discard(profile_id)
            except Exception:
                pass
            self._delete_profile_path(profile_id)
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

    def _cleanup_profile_session(self, item_id: str = None, profile_id: str = None) -> None:
        info = None
        if item_id is not None:
            with self.active_drivers_lock:
                info = self.active_drivers.pop(item_id, None)
        if info and not profile_id:
            profile_id = info.get("profile_id")
        try:
            if info and "close_func" in info:
                info["close_func"]()
        except Exception:
            pass
        if profile_id:
            try:
                close_profile(profile_id, 3)
                delete_profile(profile_id, 10)
            except Exception:
                pass
            try:
                self.created_profiles.discard(profile_id)
            except Exception:
                pass
            self._delete_profile_path(profile_id)
            self._track_profile_cleanup()

    def _extract_profile_path(self, data: dict) -> str:
        payload = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
        if not isinstance(payload, dict):
            return ""
        for key in (
            "profile_path",
            "profilePath",
            "profile_dir",
            "profileDir",
            "path",
            "folder",
            "local_path",
            "localPath",
        ):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""

    def _get_gpm_root(self) -> str:
        try:
            raw = self.entry_gpm_path.get().strip()
        except Exception:
            raw = ""
        if not raw:
            return ""
        try:
            return os.path.abspath(os.path.expanduser(raw))
        except Exception:
            return raw

    def _guess_profile_path(self) -> str:
        gpm_root = self._get_gpm_root()
        if not gpm_root or not os.path.isdir(gpm_root):
            return ""
        try:
            entries = []
            for name in os.listdir(gpm_root):
                if name.lower() == "profile_data.db":
                    continue
                path = os.path.join(gpm_root, name)
                if not os.path.isdir(path):
                    continue
                if path in self.profile_paths_used:
                    continue
                try:
                    mtime = os.path.getmtime(path)
                except Exception:
                    mtime = 0
                entries.append((mtime, path))
            if not entries:
                return ""
            entries.sort(key=lambda x: x[0], reverse=True)
            return entries[0][1]
        except Exception:
            return ""

    def _remember_profile_path(self, profile_id: str, data: dict) -> None:
        if not profile_id:
            return
        path = self._extract_profile_path(data or {})
        if not path:
            path = self._guess_profile_path()
            if not path:
                try:
                    self._log(f"[GPM] profile_path missing for {profile_id}")
                except Exception:
                    pass
                return
            try:
                self._log(f"[GPM] profile_path guessed for {profile_id}: {path}")
            except Exception:
                pass
        with self.profile_paths_lock:
            self.profile_paths[profile_id] = path
            self.profile_paths_used.add(path)
        try:
            self._log(f"[GPM] profile_path for {profile_id}: {path}")
        except Exception:
            pass

    def _delete_profile_path(self, profile_id: str) -> None:
        if not profile_id:
            return
        with self.profile_paths_lock:
            path = self.profile_paths.pop(profile_id, None)
            if path:
                self.profile_paths_used.discard(path)
        if not path:
            return
        try:
            abs_path = os.path.abspath(path)
            if os.path.isdir(abs_path):
                shutil.rmtree(abs_path, ignore_errors=True)
        except Exception:
            pass

    def _track_profile_cleanup(self) -> None:
        with self._gpm_cleanup_lock:
            self._gpm_cleanup_count += 1
            count = self._gpm_cleanup_count
        if count >= 10:
            self._cleanup_gpm_root_if_needed()

    def _cleanup_gpm_root_if_needed(self) -> None:
        with self._gpm_cleanup_lock:
            if self._gpm_cleanup_running:
                return
            self._gpm_cleanup_running = True
        try:
            self._cleanup_gpm_root(force=False)
        finally:
            with self._gpm_cleanup_lock:
                self._gpm_cleanup_count = 0
                self._gpm_cleanup_running = False

    def _cleanup_gpm_root(self, force: bool = False) -> None:
        gpm_root = self._get_gpm_root()
        if not gpm_root or not os.path.isdir(gpm_root):
            return
        try:
            if force:
                self._log(f"[GPM] Cleaning all profile folders in {gpm_root} (force)")
            else:
                self._log(f"[GPM] Cleaning profile folders in {gpm_root}")
        except Exception:
            pass
        try:
            for name in os.listdir(gpm_root):
                if name.lower() == "profile_data.db":
                    continue
                path = os.path.join(gpm_root, name)
                if not os.path.isdir(path):
                    continue
                if not force and path in self.profile_paths_used:
                    continue
                try:
                    shutil.rmtree(path, ignore_errors=True)
                except Exception:
                    pass
        except Exception:
            pass

    def _login_only_worker(self, item_id: str, acc: dict) -> None:
        if self.stop_event.is_set():
            return
        try:
            self._ensure_logged_in(item_id, acc)
            self._set_status(item_id, "LOGIN OK (HOLD)")
            self._log(f"[{acc['uid']}] LOGIN OK (HOLD) - will close on STOP")
        except Exception:
            pass

    def _upload_only_worker(self, item_id: str, acc: dict) -> None:
        if self.stop_event.is_set():
            return
        profile_id = None
        try:
            driver_path, remote, profile_id = self._ensure_logged_in(item_id, acc)
            if not driver_path or not remote:
                return
            download_started = threading.Event()

            def _idle_watchdog():
                if download_started.wait(timeout=30):
                    return
                if self.stop_event.is_set():
                    return
                ok_next, row = get_next_unuploaded(acc["uid"])
                if not ok_next:
                    self._set_status(item_id, "H?T VIDEO")
                    self._log(f"[{acc['uid']}] H?T VIDEO: {row.get('msg', 'No URL in CSV')}")
                    return
                self._set_status(item_id, "LOGIN OK (IDLE)")
                self._log(f"[{acc['uid']}] LOGIN OK (IDLE) - no download started")

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
                    self._set_status(item_id, "H?T VIDEO")
                    self._log(f"[{acc['uid']}] H?T VIDEO: {row.get('msg', 'No URL in CSV')}")
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
                    fallback_cookie_path=COOKIES_FILE_FALLBACK,
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
                token = self._enqueue_upload_turn()
                if not self._wait_upload_turn(token):
                    return
                try:
                    ok_p = False
                    drv = None
                    up_status = ""
                    up_msg = ""
                    retry_reopen = {"caption_error", "dialog_error", "timeout", "unexpected_error", "error"}
                    for attempt in range(3):
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
                        if ok_p:
                            break
                        if up_status in retry_reopen and attempt < 2:
                            wait_s = 2 + attempt
                            self._log(f"[{acc['uid']}] Upload page retry {attempt+1}/2 in {wait_s}s (status={up_status})")
                            time.sleep(wait_s)
                            continue
                        break
                finally:
                    self._release_upload_turn(token)
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
                    try:
                        followers = None
                        profile_url = ""
                        posts = None
                        for attempt in range(3):
                            followers, profile_url, posts = fetch_followers(driver_path, remote, self._log)
                            if followers is not None or posts is not None:
                                break
                            time.sleep(2 + attempt)
                        if followers is not None or posts is not None:
                            if followers is not None:
                                self._log(f"[{acc['uid']}] FOLLOWERS: {followers}")
                            if posts is not None:
                                self._log(f"[{acc['uid']}] POSTS: {posts}")
                            self._set_profile_info(item_id, profile_url, followers, posts)
                        else:
                            self._log(f"[{acc['uid']}] FOLLOW ERR: empty")
                    except Exception as e:
                        self._log(f"[{acc['uid']}] FOLLOW ERR: {e}")
                    time.sleep(10.0)
                else:
                    err_text = msg or st
                    status_text = "UPLOAD LOI" if "Select video not found" in (err_text or "") else f"UPLOAD ERR: {err_text}"
                    self._set_status(item_id, status_text)
                    self._log(f"[{acc['uid']}] UPLOAD ERR: {err_text}")
                    if st == "timeout":
                        self._record_failed(item_id, acc, f"POST ERR: {err_text}")
                    return
        finally:
            if profile_id:
                self._cleanup_profile_session(item_id, profile_id)

    def _follow_only_worker(self, item_id: str, acc: dict) -> None:
        if self.stop_event.is_set():
            return
        profile_id = None
        try:
            driver_path, remote, profile_id = self._ensure_logged_in(item_id, acc)
            if not driver_path or not remote:
                return
            followers = None
            profile_url = ""
            posts = None
            for attempt in range(3):
                followers, profile_url, posts = fetch_followers(driver_path, remote, self._log)
                if followers is not None or posts is not None:
                    break
                time.sleep(2 + attempt)
            if followers is not None or posts is not None:
                if followers is not None:
                    self._log(f"[{acc['uid']}] FOLLOWERS: {followers}")
                if posts is not None:
                    self._log(f"[{acc['uid']}] POSTS: {posts}")
                self._set_profile_info(item_id, profile_url, followers, posts)
                self._set_status(item_id, "FOLLOW OK")
            else:
                self._set_status(item_id, "FOLLOW ERR")
                self._log(f"[{acc['uid']}] FOLLOW ERR")
        finally:
            if profile_id:
                self._cleanup_profile_session(item_id, profile_id)

    def _profile_open_worker(self, item_id: str, acc: dict, win_pos: str, win_size: str) -> None:
        sem = self.profile_semaphore
        if sem:
            sem.acquire()
        profile_id = None
        started = False
        email = (acc.get("uid") or "").strip()
        try:
            if self.stop_event.is_set():
                return
            started = True
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
            self._remember_profile_path(profile_id, data_c)
            self.profile_created_profiles.add(profile_id)

            self._set_profile_status(item_id, "START...")
            ok_s, data_s, msg_s = start_profile(profile_id, win_pos=win_pos, win_size=win_size)
            if not ok_s:
                if self._is_proxy_error(msg_s):
                    try:
                        close_profile(profile_id, 3)
                        delete_profile(profile_id, 10)
                    except Exception:
                        pass
                    try:
                        self.profile_created_profiles.discard(profile_id)
                    except Exception:
                        pass
                    self._delete_profile_path(profile_id)
                    new_id, new_data_s, _err = self._retry_start_profile_with_new_proxy(
                        acc,
                        item_id,
                        "profile",
                        self.profile_tree,
                        lambda s: self._set_profile_status(item_id, s),
                        win_pos=win_pos,
                        win_size=win_size,
                        created_set="profile_created_profiles",
                    )
                    if new_id and new_data_s:
                        profile_id = new_id
                        data_s = new_data_s
                        ok_s = True
                    else:
                        self._set_profile_status(item_id, f"START ERR: {msg_s}")
                        self._log(f"[{acc['uid']}] START ERR: {msg_s}")
                        self._record_profile_failed(item_id, acc, f"START ERR: {msg_s}")
                        return
                else:
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
            if started:
                self._mark_run_done("profile", email)
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
                self._delete_profile_path(profile_id)
                self._track_profile_cleanup()
            if sem:
                sem.release()

    def stop_jobs(self) -> None:
        self._clear_all_logs()
        self.stop_event.set()
        self._fixed_threads = None
        try:
            self._resume_pending["upload"] = self._collect_pending_emails(self.tree, {"UPLOAD OK", "DONE"})
            self._resume_pending["profile"] = self._collect_pending_emails(self.profile_tree, {"DONE"})
            self._resume_pending["fb"] = self._collect_pending_emails(self.fb_tree, {"UPLOAD OK", "DONE"})
            self._resume_pending["fb_profile"] = self._collect_pending_emails(self.fb_profile_tree, {"DONE"})
        except Exception:
            pass
        self._reset_batch_pause_state("YTB")
        self._reset_batch_pause_state("FB")
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
                target=lambda p=pid: self._cleanup_profile_session(None, p),
                daemon=True,
            ).start()
        try:
            self._cleanup_gpm_root(force=True)
        except Exception:
            pass

    def reload_app(self) -> None:
        self.stop_jobs()
        self._reset_all_statuses()
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
        email = (acc.get("uid") or "").strip()
        started = False
        try:
            if self.stop_event.is_set():
                return
            if not self._wait_batch_pause_if_needed("YTB"):
                return
            started = True
    
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
            self._remember_profile_path(profile_id, data_c)
            self.created_profiles.add(profile_id)
    
            self._set_status(item_id, "START...", profile_id=profile_id)
            ok_s, data_s, msg_s = start_profile(profile_id, win_pos=win_pos, win_size=win_size)
            if not ok_s:
                if self._is_proxy_error(msg_s):
                    swapped = self._replace_proxy_for_account(acc, item_id, "upload", self.tree)
                    if swapped:
                        self._set_status(item_id, f"START ERR: {msg_s} (proxy replaced)")
                        self._log(f"[{acc['uid']}] START ERR: {msg_s} (proxy replaced)")
                        self._record_failed(item_id, acc, f"START ERR: {msg_s} (proxy replaced)")
                        return
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
                        ok_next, row = get_next_unuploaded(acc["uid"])
                        if not ok_next:
                            self._set_status(item_id, "HẾT VIDEO")
                            self._log(f"[{acc['uid']}] HẾT VIDEO: {row.get('msg', 'No URL in CSV')}")
                            return
                        self._set_status(item_id, "LOGIN OK (IDLE)")
                        self._log(f"[{acc['uid']}] LOGIN OK (IDLE) - no download started")
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
                            self._set_status(item_id, "HẾT VIDEO")
                            self._log(f"[{acc['uid']}] HẾT VIDEO: {row.get('msg', 'No URL in CSV')}")
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
                        skip_account = False
                        while True:
                            ok_dl, path_or_err, vid_id, title = download_one(
                                acc["uid"],
                                row_url,
                                self._log_progress,
                                cookie_path=COOKIES_FILE,
                                fallback_cookie_path=COOKIES_FILE_FALLBACK,
                                timeout_s=120,
                            )
                            if ok_dl:
                                break
                            err_text = str(path_or_err)
                            lower = err_text.lower()
                            is_timeout = "timeout" in lower or "timed out" in lower
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
                            if is_timeout:
                                if retry_dl < 1:
                                    retry_dl += 1
                                    self._log(f"[{acc['uid']}] DOWNLOAD TIMEOUT - RETRY 1/1")
                                    continue
                                self._log(f"[{acc['uid']}] DOWNLOAD TIMEOUT - SKIP ACCOUNT")
                                self._set_status(item_id, "DOWNLOAD TIMEOUT")
                                self._record_failed(item_id, acc, "DOWNLOAD TIMEOUT")
                                skip_account = True
                                break

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
                        if skip_account:
                            break
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
                                token = self._enqueue_upload_turn()
                                if not self._wait_upload_turn(token):
                                    return
                                try:
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
    
                                        # Retry by re-opening upload page on certain failures
                                        if up_status in ("caption_error", "dialog_error", "timeout", "unexpected_error", "error"):
                                            if attempt < 2:
                                                wait_time = 2 + attempt
                                                self._log(f"[{acc['uid']}] Upload page retry {attempt+1}/2 in {wait_time}s (status={up_status})")
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
                                finally:
                                    self._release_upload_turn(token)
    
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
                    if profile_id:
                        self.created_profiles.discard(profile_id)
                except Exception:
                    pass
                if profile_id:
                    self._delete_profile_path(profile_id)
                    self._track_profile_cleanup()
            try:
                with self.active_lock:
                    self.active_profiles.pop(item_id, None)
            except Exception:
                pass
        finally:
            if started:
                self._mark_run_done("upload", email)

if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
