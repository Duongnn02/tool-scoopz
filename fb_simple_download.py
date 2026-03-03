# -*- coding: utf-8 -*-

import os
import re
import shutil
import subprocess
import time
import json
import multiprocessing as mp
from typing import Callable, Tuple

import requests
import yt_dlp
from bs4 import BeautifulSoup

from operation_orchestrator import get_orchestrator
from savef_api_config import load_savef_config

Logger = Callable[[str], None]


def _sanitize_fb_title(raw_title: str) -> str:
    title = (raw_title or '').strip()
    if not title:
        return ''
    return title

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
        "format": "bestvideo+bestaudio/best",
        "format_sort": ["res", "fps", "tbr", "vcodec:h264", "acodec:aac"],
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


def _parse_netscape_cookies(cookie_file: str) -> list[dict]:
    path = (cookie_file or "").strip()
    if not path or not os.path.exists(path):
        return []
    cookies = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                domain, _, cpath, secure, expiry, name, value = parts[:7]
                item = {
                    "domain": domain,
                    "path": cpath or "/",
                    "name": name,
                    "value": value,
                    "secure": (secure or "").upper() == "TRUE",
                }
                if expiry.isdigit() and int(expiry) > 0:
                    item["expiry"] = int(expiry)
                cookies.append(item)
    except Exception:
        return []
    return cookies


def _collect_candidate_media_urls(driver) -> list[str]:
    urls = []
    try:
        raw = driver.execute_script(
            """
            const out = [];
            const seen = new Set();
            const push = (u) => {
              if (!u || typeof u !== 'string') return;
              if (!u.startsWith('http')) return;
              if (seen.has(u)) return;
              seen.add(u);
              out.push(u);
            };
            document.querySelectorAll('video').forEach(v => {
              push(v.currentSrc || '');
              push(v.src || '');
            });
            try {
              performance.getEntriesByType('resource').forEach(r => {
                const n = (r && r.name) ? r.name : '';
                if (!n) return;
                if (n.includes('.mp4') || n.includes('.m3u8') || n.includes('.mpd')) push(n);
              });
            } catch (e) {}
            return out;
            """
        )
        if isinstance(raw, list):
            for item in raw:
                u = str(item or "").strip()
                if u and u.startswith("http"):
                    urls.append(u)
    except Exception:
        pass

    if urls:
        return list(dict.fromkeys(urls))

    try:
        html = driver.page_source or ""
        html = html.replace("\\/", "/")
        patterns = [
            r"https://[^\"'<>\\]+?\.mp4[^\"'<>\\]*",
            r"https://[^\"'<>\\]+?\.m3u8[^\"'<>\\]*",
            r"https://[^\"'<>\\]+?\.mpd[^\"'<>\\]*",
        ]
        for pat in patterns:
            urls.extend(re.findall(pat, html, flags=re.IGNORECASE))
    except Exception:
        pass
    return list(dict.fromkeys(urls))


def _collect_candidate_media_urls_from_performance_logs(driver) -> list[str]:
    urls = []
    try:
        logs = driver.get_log("performance")
    except Exception:
        return []
    for entry in logs or []:
        try:
            msg = json.loads((entry or {}).get("message") or "{}")
            message = ((msg.get("message") or {}) if isinstance(msg, dict) else {})
            method = str(message.get("method") or "")
            params = message.get("params") or {}
            if not method.startswith("Network."):
                continue

            url = ""
            if method == "Network.responseReceived":
                response = params.get("response") or {}
                url = str(response.get("url") or "")
                mime = str(response.get("mimeType") or "").lower()
                if "video" in mime and url.startswith("http"):
                    urls.append(url)
            elif method in ("Network.requestWillBeSent", "Network.requestWillBeSentExtraInfo"):
                request = params.get("request") or {}
                url = str(request.get("url") or "")
                if url.startswith("http"):
                    lu = url.lower()
                    if (".mp4" in lu) or (".m3u8" in lu) or (".mpd" in lu):
                        urls.append(url)
        except Exception:
            continue
    return list(dict.fromkeys(urls))


def _gather_media_candidates(driver, wait_s: int = 20) -> list[str]:
    end_at = time.time() + max(5, wait_s)
    all_urls = []
    while time.time() < end_at:
        try:
            driver.execute_script(
                """
                document.querySelectorAll('video').forEach(v => {
                  try { v.muted = true; } catch (e) {}
                  try { v.play(); } catch (e) {}
                });
                """
            )
        except Exception:
            pass

        urls_dom = _collect_candidate_media_urls(driver)
        urls_perf = _collect_candidate_media_urls_from_performance_logs(driver)
        all_urls.extend(urls_dom)
        all_urls.extend(urls_perf)
        all_urls = list(dict.fromkeys(all_urls))
        if all_urls:
            break
        time.sleep(1.0)
    return all_urls


def _is_fb_login_gate(driver) -> bool:
    try:
        url = str(driver.current_url or "").lower()
    except Exception:
        url = ""
    if "/login" in url or "/checkpoint" in url:
        return True
    try:
        has_login_form = bool(
            driver.execute_script(
                """
                return Boolean(
                  document.querySelector('form[data-testid="royal_login_form"]') ||
                  (document.querySelector('input[name="email"]') && document.querySelector('input[name="pass"]'))
                );
                """
            )
        )
        return has_login_form
    except Exception:
        return False


def _download_mp4_via_requests(
    media_url: str,
    output_path: str,
    timeout_s: int,
    cookies: dict | None = None,
    user_agent: str = "",
) -> Tuple[bool, str]:
    headers = {}
    if user_agent:
        headers["User-Agent"] = user_agent
    try:
        with requests.get(
            media_url,
            stream=True,
            timeout=(15, max(30, timeout_s)),
            headers=headers,
            cookies=(cookies or {}),
        ) as resp:
            resp.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return True, output_path
        return False, "empty downloaded file"
    except Exception as e:
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
        except Exception:
            pass
        return False, str(e)


def _extract_savef_720_link(html: str) -> str:
    text = (html or "").strip()
    if not text:
        return ""

    try:
        soup = BeautifulSoup(text, "html.parser")
        exact = soup.select_one('a.download-link-fb[title="Download 720p (HD)"][href]')
        if exact:
            href = (exact.get("href") or "").strip()
            if href:
                return href

        for row in soup.select("#fbdownloader .tab__content table tbody tr"):
            qnode = row.select_one(".video-quality")
            quality = (qnode.get_text(" ", strip=True) if qnode else "").lower()
            if "720" not in quality:
                continue
            link = row.select_one("a[href]")
            if link:
                href = (link.get("href") or "").strip()
                if href:
                    return href
    except Exception:
        pass

    m = re.search(r'href="([^"]+)"[^>]*>\s*Tải xuống\s*</a>', text, flags=re.IGNORECASE)
    if m and ("720p" in text.lower()):
        return (m.group(1) or "").strip()
    return ""


def _download_via_savef_api(
    url: str,
    out_dir: str,
    email: str,
    timeout_s: int,
    logger: Logger,
) -> Tuple[bool, str, str, str]:
    cfg = load_savef_config()
    payload = {
        "p": "home",
        "k_exp": cfg["k_exp"],
        "k_token": cfg["k_token"],
        "q": (url or "").strip(),
        "lang": cfg["lang"],
        "web": cfg["web"],
        "v": cfg["v"],
        "w": cfg["w"],
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://savef.app",
        "Referer": cfg["referer"],
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
    }
    try:
        resp = requests.post(cfg["api_url"], data=payload, headers=headers, timeout=max(20, timeout_s))
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return False, f"savef api request failed: {e}", "", ""

    if str(data.get("status") or "").lower() != "ok":
        return False, "savef api status not ok", "", ""

    html = str(data.get("data") or "")
    dl_link = _extract_savef_720_link(html)
    if not dl_link:
        return False, "savef api no 720 link", "", ""

    vid = ""
    m = re.search(r"/reel/(\d+)", url)
    if m:
        vid = m.group(1)
    if not vid:
        vid = str(int(time.time()))
    out_path = os.path.join(out_dir, f"{vid}.mp4")
    if os.path.exists(out_path):
        out_path = os.path.join(out_dir, f"{vid}_savef.mp4")

    logger(f"[DL] {email} savef 720 link detected")
    ok, p_or_err = _download_mp4_via_requests(
        dl_link,
        out_path,
        timeout_s=max(timeout_s, 60),
        user_agent=headers["User-Agent"],
    )
    if not ok:
        return False, f"savef api download failed: {p_or_err}", "", ""
    return True, p_or_err, vid, "savef_720p"


def _download_stream_via_ffmpeg(media_url: str, output_path: str, timeout_s: int) -> Tuple[bool, str]:
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        media_url,
        "-c",
        "copy",
        output_path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=max(60, timeout_s))
    except FileNotFoundError:
        return False, "ffmpeg not found"
    except Exception as e:
        return False, str(e)

    if proc.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        return True, output_path
    try:
        if os.path.exists(output_path):
            os.remove(output_path)
    except Exception:
        pass
    stderr = (proc.stderr or "").strip()
    return False, stderr or "ffmpeg failed"


def _download_via_selenium_fallback(
    url: str,
    out_dir: str,
    email: str,
    timeout_s: int,
    logger: Logger,
    cookie_file: str = "",
) -> Tuple[bool, str, str, str]:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except Exception as e:
        return False, f"selenium unavailable: {e}", "", ""

    base_dir = os.path.dirname(__file__)
    profile_dirs = [
        os.path.join(base_dir, "chrome_automation_user_data"),
        os.path.join(base_dir, "chrome_automation_user_data_2"),
        os.path.join(base_dir, "chrome_automation_user_data_3"),
        os.path.join(base_dir, "chrome_automation_user_data_4"),
    ]
    existing_profiles = [p for p in profile_dirs if os.path.isdir(p)]

    modes = [{"name": "headless-cookie", "headless": True, "user_data_dir": ""}]
    if existing_profiles:
        p = existing_profiles[0]
        modes.append({"name": f"profile:{os.path.basename(p)}", "headless": False, "user_data_dir": p})

    last_err = "selenium fallback: no media url"
    for mode in modes:
        opts = Options()
        if mode["headless"]:
            opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--window-size=1280,900")
        opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        user_data_dir = str(mode.get("user_data_dir") or "").strip()
        if user_data_dir:
            opts.add_argument(f"--user-data-dir={user_data_dir}")
            opts.add_argument("--profile-directory=Default")

        driver = None
        try:
            logger(f"[DL] {email} fallback mode: {mode['name']}")
            driver = webdriver.Chrome(options=opts)
            driver.set_page_load_timeout(max(30, timeout_s))
            driver.set_script_timeout(max(30, timeout_s))

            cookies = _parse_netscape_cookies(cookie_file)
            if cookies:
                try:
                    driver.get("https://www.facebook.com/")
                    for c in cookies:
                        item = dict(c)
                        try:
                            driver.add_cookie(item)
                        except Exception:
                            item.pop("expiry", None)
                            try:
                                driver.add_cookie(item)
                            except Exception:
                                continue
                except Exception:
                    pass

            driver.get(url)
            if _is_fb_login_gate(driver):
                last_err = f"{mode['name']}: login required"
                continue

            candidates = _gather_media_candidates(driver, wait_s=max(8, min(timeout_s, 12)))

            if not candidates:
                last_err = f"{mode['name']}: cannot detect media url"
                continue

            preferred = ""
            for u in candidates:
                lu = u.lower()
                if ".mp4" in lu:
                    preferred = u
                    break
            if not preferred:
                preferred = candidates[0]

            vid = ""
            m = re.search(r"/reel/(\d+)", url)
            if m:
                vid = m.group(1)
            if not vid:
                vid = str(int(time.time()))
            title = ""
            try:
                title = _sanitize_fb_title(
                    str(
                        driver.execute_script(
                            "return (document.querySelector('meta[property=\"og:title\"]')||{}).content || document.title || '';"
                        )
                        or ""
                    )
                )
            except Exception:
                title = ""

            out_path = os.path.join(out_dir, f"{vid}.mp4")
            ua = ""
            try:
                ua = str(driver.execute_script("return navigator.userAgent || '';") or "")
            except Exception:
                ua = ""
            cookie_dict = {}
            try:
                for c in driver.get_cookies() or []:
                    name = (c or {}).get("name")
                    value = (c or {}).get("value")
                    if name and value is not None:
                        cookie_dict[name] = value
            except Exception:
                cookie_dict = {}

            logger(f"[DL] {email} fallback media detected: {preferred[:140]}")
            lp = preferred.lower()
            if ".m3u8" in lp or ".mpd" in lp:
                ok, p_or_err = _download_stream_via_ffmpeg(preferred, out_path, timeout_s)
            else:
                ok, p_or_err = _download_mp4_via_requests(
                    preferred, out_path, timeout_s, cookies=cookie_dict, user_agent=ua
                )
            if not ok:
                last_err = f"{mode['name']}: download failed: {p_or_err}"
                continue
            return True, p_or_err, vid, title
        except Exception as e:
            last_err = f"{mode['name']}: {e}"
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
    return False, f"selenium fallback: {last_err}", "", ""


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

        last_err = ""
        for cookie_file in (first_cookie, second_cookie):
            try:
                ok, path_or_err, vid_id, title = _download_once_with_timeout(
                    url,
                    out_dir,
                    email,
                    timeout_s,
                    cookie_file=cookie_file,
                )
                if ok:
                    return True, path_or_err, vid_id, title
                last_err = str(path_or_err)
                logger(f"[DL] {email} yt-dlp fail -> fallback savef api: {last_err}")
                ok_sf, path_sf, vid_sf, title_sf = _download_via_savef_api(
                    url=url,
                    out_dir=out_dir,
                    email=email,
                    timeout_s=timeout_s,
                    logger=logger,
                )
                if ok_sf:
                    return True, path_sf, vid_sf, title_sf
                logger(f"[DL] {email} savef api fail -> fallback selenium: {path_sf}")
                ok_fb, path_fb, vid_fb, title_fb = _download_via_selenium_fallback(
                    url=url,
                    out_dir=out_dir,
                    email=email,
                    timeout_s=timeout_s,
                    logger=logger,
                    cookie_file=cookie_file,
                )
                if ok_fb:
                    return True, path_fb, vid_fb, title_fb
                last_err = f"{last_err} | {path_sf} | {path_fb}"
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
        if last_err:
            return False, f"fb-dlp loi: cannot download video ({last_err})", "", ""
        return False, "fb-dlp loi: cannot download video", "", ""
    finally:
        if acquired:
            orchestrator.release_download_lock(email)
