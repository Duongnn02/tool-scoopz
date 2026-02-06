# -*- coding: utf-8 -*-

import os
import shutil
import multiprocessing as mp
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


def pick_js_runtimes_dict() -> dict:
    # yt-dlp expects dict: {"deno": {}} or {"node": {}}
    if shutil.which("deno"):
        return {"deno": {}}
    if shutil.which("node"):
        return {"node": {}}
    return {}


def build_opts(js_runtimes: dict, out_dir: str, use_cookie: bool, cookie_file: str, logger=None, email: str = "", timeout_s: int = 120):
    opts = {
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "socket_timeout": timeout_s,
        "js_runtimes": js_runtimes,
        "extractor_args": {"youtube": {"player_client": ["android", "web_embedded"]}},
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 8,
        "progress_hooks": [_make_progress_hook(logger=logger, email=email)],
        "quiet": True,
        "no_warnings": True,
    }

    if use_cookie and cookie_file:
        opts["cookiefile"] = cookie_file

    return opts


def looks_like_need_cookie(err: str) -> bool:
    e = (err or "").lower()
    keywords = [
        "sign in to confirm youâ€™re not a bot",
        "sign in to confirm you're not a bot",
        "use --cookies",
        "cookies-from-browser",
        "http error 403",
        "403: forbidden",
        "forbidden",
        "login",
        "confirm youâ€™re not a bot",
        "confirm you're not a bot",
    ]
    return any(k in e for k in keywords)


def _download_once(url: str, out_dir: str, logger: Logger, email: str, timeout_s: int, cookie_file: str = "") -> Tuple[bool, str, str, str]:
    js_runtimes = pick_js_runtimes_dict()
    if not js_runtimes:
        raise RuntimeError("Thieu JS runtime (deno hoac node). Cai deno.exe (portable) + add PATH, hoac cai Node.js.")

    ydl_opts = build_opts(
        js_runtimes=js_runtimes,
        out_dir=out_dir,
        use_cookie=bool(cookie_file),
        cookie_file=cookie_file,
        logger=logger,
        email=email,
        timeout_s=timeout_s,
    )

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

        cookie_candidates = []
        if cookie_path and os.path.exists(cookie_path):
            cookie_candidates.append(cookie_path)
        if fallback_cookie_path and os.path.exists(fallback_cookie_path):
            cookie_candidates.append(fallback_cookie_path)
        
        logger(f"[DL] START {email} {url}")
        try:
            # First try without cookie
            ok, path, vid, title = _download_once_with_timeout(
                url,
                out_dir,
                email,
                timeout_s,
                cookie_file="",
            )
            if ok:
                return True, path, vid, title
            return False, path, vid, title
        except Exception as e:
            err_str = str(e)
            if looks_like_need_cookie(err_str):
                for cookie_file in cookie_candidates:
                    try:
                        logger(f"[DL] Retry with cookie: {cookie_file}")
                        return _download_once_with_timeout(
                            url,
                            out_dir,
                            email,
                            timeout_s,
                            cookie_file=cookie_file,
                        )
                    except Exception as e2:
                        err_str = str(e2)
                        if looks_like_need_cookie(err_str) or "403" in err_str.lower() or "forbidden" in err_str.lower():
                            continue
                        raise
            # Detect members-only and similar access restriction errors
            err_low = err_str.lower()
            is_access_restricted = any([
                "members-only" in err_low,
                "members only" in err_low,
                "join this channel" in err_low,
                "this video is available to channel members" in err_low,
                "premium only" in err_low,
                "membership required" in err_low,
                "you need to be a member" in err_low,
                "access denied" in err_low,
            ])
            # Detect video unavailable / age restricted (removed, terminated account, private, etc)
            is_unavailable = any([
                "video unavailable" in err_low,
                "has been removed by the uploader" in err_low,
                "no longer available" in err_low,
                "account associated with this video has been terminated" in err_low,
                "this video has been removed" in err_low,
                "private video" in err_low,
                "restricted" in err_low,
                "sign in to confirm your age" in err_low,
                "age-restricted" in err_low,
                "age restricted" in err_low,
            ])
            if is_access_restricted or is_unavailable:
                return False, f"VIDEO SKIPPED: {e}", "", ""
            return False, f"yt-dlp loi: {e}", "", ""
    finally:
        # Always release lock
        orchestrator.release_download_lock(email)
