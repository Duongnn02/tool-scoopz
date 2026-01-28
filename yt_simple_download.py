# -*- coding: utf-8 -*-

import os
import time
import shutil
from typing import Callable, Tuple

import yt_dlp

from operation_orchestrator import get_orchestrator

Logger = Callable[[str], None]

_ffmpeg_checked = False
_ffmpeg_available = False


def _check_ffmpeg(logger: Logger) -> bool:
    global _ffmpeg_checked, _ffmpeg_available
    if _ffmpeg_checked:
        return _ffmpeg_available
    _ffmpeg_checked = True
    _ffmpeg_available = bool(shutil.which("ffmpeg"))
    if not _ffmpeg_available and logger:
        logger("[DL] FFmpeg not found. Install ffmpeg and add to PATH to avoid merge errors.")
    return _ffmpeg_available


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


def download_one(
    email: str,
    url: str,
    logger: Logger,
    cookie_path: str = "",
    fallback_cookie_path: str = "",
    timeout_s: int = 120,
) -> Tuple[bool, str, str, str]:
    # Acquire download lock for sequential processing
    orchestrator = get_orchestrator()
    orchestrator.acquire_download_lock(email)
    
    try:
        _check_ffmpeg(logger)
        email_safe = _safe_email(email)
        out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "video", email_safe))
        os.makedirs(out_dir, exist_ok=True)

        last_log = {"t": 0.0, "pct": -1, "no_total_t": 0.0}

        def _progress_hook(d):
            try:
                if d.get("status") != "downloading":
                    return
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                now = time.time()
                if total <= 0:
                    if (now - last_log["no_total_t"]) >= 3.0:
                        logger(f"[DL] {email} downloading...")
                        last_log["no_total_t"] = now
                    return
                pct = int(downloaded * 100 / total)
                if pct == last_log["pct"] and (now - last_log["t"]) < 3.0:
                    return
                if (now - last_log["t"]) < 3.0 and (pct - last_log["pct"]) < 10:
                    return
                if pct not in (0, 100) and pct % 10 != 0 and (now - last_log["t"]) < 3.0:
                    return
                last_log["pct"] = pct
                last_log["t"] = now
                mb_done = downloaded / (1024 * 1024)
                mb_total = total / (1024 * 1024)
                logger(f"[DL] {email} {pct}% ({mb_done:.1f}/{mb_total:.1f} MB)")
            except Exception:
                pass

        class _QuietLogger:
            def debug(self, msg):
                pass
            def warning(self, msg):
                pass
            def error(self, msg):
                pass

        ydl_opts = {
            "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
            "format": "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/b[ext=mp4]/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "logger": _QuietLogger(),
            "merge_output_format": "mp4",
            "socket_timeout": timeout_s,
            "retries": 3,
            "fragment_retries": 3,
            "concurrent_fragment_downloads": 2,
            "ratelimit": 1_000_000,
            "sleep_interval": 1,
            "max_sleep_interval": 2,
            "progress_hooks": [_progress_hook],
        }
        cookie_candidates = []
        if cookie_path and os.path.exists(cookie_path):
            cookie_candidates.append(cookie_path)
        if fallback_cookie_path and os.path.exists(fallback_cookie_path):
            cookie_candidates.append(fallback_cookie_path)

        def _run_with_cookie(cookie_file: str) -> Tuple[bool, str, str, str]:
            if cookie_file:
                ydl_opts["cookiefile"] = cookie_file
            elif "cookiefile" in ydl_opts:
                ydl_opts.pop("cookiefile", None)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    return False, "yt-dlp khong co thong tin video", "", ""
                path = ydl.prepare_filename(info)
                vid = (info.get("id") or "").strip()
                title = (info.get("title") or "").strip()
            if not path or not os.path.exists(path):
                return False, "yt-dlp tai xong nhung khong tim thay file", "", ""
            return True, path, vid, title

        logger(f"[DL] START {email} {url}")
        try:
            if cookie_candidates:
                ok, path, vid, title = _run_with_cookie(cookie_candidates[0])
                if ok:
                    return True, path, vid, title
                # If first cookie fails with 403, try fallback cookie
                err_text = str(path).lower()
                if len(cookie_candidates) > 1 and ("403" in err_text or "forbidden" in err_text):
                    logger(f"[DL] 403 detected, retrying with fallback cookie...")
                    return _run_with_cookie(cookie_candidates[1])
                return False, path, vid, title
            return _run_with_cookie("")
        except Exception as e:
            err_str = str(e).lower()
            if cookie_candidates and len(cookie_candidates) > 1 and ("403" in err_str or "forbidden" in err_str):
                try:
                    logger(f"[DL] 403 detected, retrying with fallback cookie...")
                    return _run_with_cookie(cookie_candidates[1])
                except Exception:
                    pass
            if "ffmpeg is not installed" in err_str or "ffmpeg" in err_str and "not installed" in err_str:
                if logger:
                    logger("[DL] FFmpeg missing. Install ffmpeg and add to PATH.")
            # Detect members-only and similar access restriction errors
            is_access_restricted = any([
                "members-only" in err_str,
                "members only" in err_str,
                "join this channel" in err_str,
                "this video is available to channel members" in err_str,
                "premium only" in err_str,
                "membership required" in err_str,
                "you need to be a member" in err_str,
                "access denied" in err_str,
            ])
            # Detect video unavailable / age restricted (removed, terminated account, private, etc)
            is_unavailable = any([
                "video unavailable" in err_str,
                "has been removed by the uploader" in err_str,
                "no longer available" in err_str,
                "account associated with this video has been terminated" in err_str,
                "this video has been removed" in err_str,
                "private video" in err_str,
                "restricted" in err_str,
                "sign in to confirm your age" in err_str,
                "age-restricted" in err_str,
                "age restricted" in err_str,
            ])
            if is_access_restricted or is_unavailable:
                return False, f"VIDEO SKIPPED: {e}", "", ""
            return False, f"yt-dlp loi: {e}", "", ""
    finally:
        # Always release lock
        orchestrator.release_download_lock(email)
