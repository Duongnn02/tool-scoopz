# -*- coding: utf-8 -*-

import os
import re
import shutil
import multiprocessing as mp
from typing import Callable, Tuple

import yt_dlp

from operation_orchestrator import get_orchestrator

Logger = Callable[[str], None]


def _sanitize_fb_title(raw_title: str) -> str:
    title = (raw_title or "").strip()
    if not title:
        return ""
    parts = [p.strip() for p in title.split("·")]
    if len(parts) <= 1:
        return title

    metrics_pattern = re.compile(
        r"^\s*[\d.,]+(?:\s*[KMB])?\s*(views?|reactions?|comments?|shares?|lượt xem|lượt thích|bình luận|chia sẻ)\s*$",
        re.IGNORECASE,
    )
    kept = [p for p in parts if p and not metrics_pattern.match(p)]
    cleaned = " · ".join(kept).strip()
    return cleaned


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


def _make_progress_hook(logger=None, email: str = ""):
    def _hook(d: dict) -> None:
        if d.get("status") != "finished":
            return
        total = (d.get("_total_bytes_str") or d.get("_total_bytes_estimate_str") or "").strip()
        speed = (d.get("_speed_str") or "").strip()
        elapsed = (d.get("_elapsed_str") or "").strip()
        prefix = f"[DL] {email} " if email else "[DL] "
        msg = f"{prefix}[download] 100% of {total} in {elapsed} at {speed}"
        if logger:
            logger(msg)
        else:
            print(msg)

    return _hook


def _silent_logger(_msg: str) -> None:
    return


def _resolve_output_path(info: dict, out_dir: str, ydl: yt_dlp.YoutubeDL) -> str:
    path = ydl.prepare_filename(info)
    if path and os.path.exists(path):
        return path
    for item in info.get("requested_downloads") or []:
        file_path = (item or {}).get("filepath")
        if file_path and os.path.exists(file_path):
            return file_path
    vid = (info.get("id") or "").strip()
    if vid:
        prefix = vid + "."
        for name in os.listdir(out_dir):
            if name.startswith(prefix):
                candidate = os.path.join(out_dir, name)
                if os.path.exists(candidate):
                    return candidate
    return ""


def _download_once(
    url: str,
    out_dir: str,
    logger: Logger,
    email: str,
    timeout_s: int,
    cookie_file: str = "",
) -> Tuple[bool, str, str, str]:
    opts = {
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "socket_timeout": timeout_s,
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 8,
        "progress_hooks": [_make_progress_hook(logger=logger, email=email)],
        "quiet": True,
        "no_warnings": True,
    }
    if cookie_file:
        opts["cookiefile"] = cookie_file

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            return False, "yt-dlp khong co thong tin video", "", ""
        path = _resolve_output_path(info, out_dir, ydl)
        vid = (info.get("id") or "").strip()
        title = _sanitize_fb_title((info.get("title") or "").strip())

    if not path or not os.path.exists(path):
        return False, "yt-dlp tai xong nhung khong tim thay file", "", ""
    return True, path, vid, title


def _download_once_worker(
    q: "mp.Queue",
    url: str,
    out_dir: str,
    email: str,
    timeout_s: int,
    cookie_file: str,
) -> None:
    try:
        ok, path, vid, title = _download_once(
            url,
            out_dir,
            _silent_logger,
            email,
            timeout_s,
            cookie_file=cookie_file,
        )
        q.put((ok, path, vid, title))
    except Exception as e:
        q.put((False, str(e), "", ""))


def _download_once_with_timeout(
    url: str,
    out_dir: str,
    email: str,
    timeout_s: int,
    cookie_file: str = "",
) -> Tuple[bool, str, str, str]:
    ctx = mp.get_context("spawn")
    q: "mp.Queue" = ctx.Queue()
    p = ctx.Process(
        target=_download_once_worker,
        args=(q, url, out_dir, email, timeout_s, cookie_file),
    )
    p.daemon = True
    p.start()
    p.join(timeout_s)
    if p.is_alive():
        try:
            p.terminate()
        except Exception:
            pass
        try:
            p.join(5)
        except Exception:
            pass
        return False, f"timeout after {timeout_s}s", "", ""
    try:
        if not q.empty():
            return q.get_nowait()
    except Exception:
        pass
    return False, "download failed", "", ""


def download_one_facebook(
    email: str,
    url: str,
    logger: Logger,
    cookie_path: str = "",
    timeout_s: int = 120,
) -> Tuple[bool, str, str, str]:
    orchestrator = get_orchestrator()
    acquired = orchestrator.acquire_download_lock(email, timeout_s=timeout_s, logger=logger)
    if not acquired:
        return False, f"download lock timeout after {timeout_s}s", "", ""
    try:
        email_safe = _safe_email(email)
        out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "video", email_safe))
        os.makedirs(out_dir, exist_ok=True)

        logger(f"[DL] START {email} {url}")
        cookie_ok = cookie_path and os.path.exists(cookie_path)

        first_cookie = cookie_path if cookie_ok else ""
        second_cookie = "" if first_cookie else (cookie_path if cookie_ok else "")

        for cookie_file in (first_cookie, second_cookie):
            try:
                return _download_once_with_timeout(
                    url,
                    out_dir,
                    email,
                    timeout_s,
                    cookie_file=cookie_file,
                )
            except Exception as e:
                err = str(e).lower()
                restricted = any(
                    k in err
                    for k in [
                        "video unavailable",
                        "private",
                        "content isn't available",
                        "login",
                        "checkpoint",
                        "this page isn't available",
                    ]
                )
                if restricted:
                    return False, f"VIDEO SKIPPED: {e}", "", ""
                if cookie_file and ("403" in err or "forbidden" in err):
                    continue
                return False, f"fb-dlp loi: {e}", "", ""
        return False, "fb-dlp loi: cannot download video", "", ""
    finally:
        if acquired:
            orchestrator.release_download_lock(email)
