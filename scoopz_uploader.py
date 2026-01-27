# -*- coding: utf-8 -*-

import os
import time
import threading
import random
import re
from tkinter import Tk
from typing import Callable, Tuple, Optional

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains
from bs4 import BeautifulSoup

try:
    from pywinauto import Application
    from pywinauto.keyboard import send_keys
    PYWINAUTO_AVAILABLE = True
except ImportError as e:
    Application = None
    send_keys = None
    PYWINAUTO_AVAILABLE = False

try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except ImportError:
    PYPERCLIP_AVAILABLE = False

from config import SCOOPZ_URL
from operation_orchestrator import get_orchestrator

Logger = Callable[[str], None]
StopChecker = Callable[[], bool]


def _log(logger: Logger, msg: str) -> None:
    if logger:
        logger(msg)


def _attach_driver(driver_path: str, remote_debugging_address: str):
    options = webdriver.ChromeOptions()
    options.add_experimental_option("debuggerAddress", remote_debugging_address.strip())
    service = Service(driver_path)
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def _force_click(driver, el) -> bool:
    """Multi-method click with retries for maximum reliability"""
    # Method 1: Scroll to center
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.1)
    except Exception:
        pass
    
    # Method 2: Direct click
    try:
        el.click()
        time.sleep(0.05)
        return True
    except Exception as e:
        pass
    
    # Method 3: ActionChains with multiple attempts
    try:
        for attempt in range(2):
            try:
                ActionChains(driver).move_to_element(el).pause(0.05).click().perform()
                time.sleep(0.05)
                return True
            except Exception:
                time.sleep(0.05)
                continue
    except Exception:
        pass
    
    # Method 4: JavaScript click
    try:
        driver.execute_script("arguments[0].click();", el)
        time.sleep(0.05)
        return True
    except Exception:
        pass
    
    # Method 5: JavaScript with event dispatch
    try:
        driver.execute_script("""
            const evt = new MouseEvent('click', {
                bubbles: true,
                cancelable: true,
                view: window
            });
            arguments[0].dispatchEvent(evt);
        """, el)
        time.sleep(0.05)
        return True
    except Exception:
        pass
    
    return False


def _parse_followers(text: str) -> Optional[int]:
    txt = (text or "").strip().replace(",", "").upper()
    if not txt:
        return None
    try:
        if txt.endswith("K"):
            return int(float(txt[:-1]) * 1000)
        if txt.endswith("M"):
            return int(float(txt[:-1]) * 1_000_000)
        if txt.endswith("B"):
            return int(float(txt[:-1]) * 1_000_000_000)
        if txt.isdigit():
            return int(txt)
    except Exception:
        return None
    return None


def _sanitize_bmp(text: str) -> str:
    if not text:
        return ""
    return "".join(ch for ch in text if ord(ch) <= 0xFFFF)


def _set_clipboard(text: str) -> bool:
    try:
        root = Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception:
        return False


def _set_editor_text(driver, editor, text: str) -> None:
    try:
        driver.execute_script(
            "arguments[0].innerText = arguments[1];"
            "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));",
            editor,
            text,
        )
    except Exception:
        editor.click()
        time.sleep(0.1)
        editor.send_keys(text)




def _select_file_in_dialog(video_path: str, logger: Logger, timeout: int = 15, semaphore: Optional[threading.BoundedSemaphore] = None) -> bool:
    """Select file in dialog with SERIAL handling (one dialog at a time).
    
    Args:
        video_path: Path to video file
        logger: Logger function
        timeout: Timeout in seconds (default 15s - increased from 3s)
        semaphore: BoundedSemaphore(1) to ensure only 1 dialog opens at a time!
    
    Returns:
        True if file selected, False otherwise
    """
    # ⭐ SERIAL DIALOG HANDLING: Only 1 thread can open dialog at a time
    acquired = False
    if semaphore:
        _log(logger, f"[UPLOAD-DIALOG] Waiting for dialog slot (semaphore)...")
        # ⭐ DIALOG PRIORITY: Timeout 30s (longer than user interaction time) to ensure this dialog slot is acquired
        acquired = semaphore.acquire(timeout=30)
        if not acquired:
            _log(logger, f"[UPLOAD-DIALOG] ✗ Timeout waiting for dialog slot (30s) - other thread still using dialog")
            return False
        _log(logger, f"[UPLOAD-DIALOG] ✓ Got dialog slot, proceeding...")
    
    try:
        video_path = os.path.abspath(video_path)
        safe_path = video_path.replace("{", "{{").replace("}", "}}")
        title_re = "Open|M\\u1edf|Ch\\u1ecdn t\\u1ec7p|Ch\\u1ecdn t\\u1eadp tin|File Upload|Upload"

        def _try_backend(backend: str) -> bool:
            _log(logger, f"[UPLOAD-DIALOG] ====== Trying backend: {backend} ======")
            dlg = None
            start = time.time()
            attempt = 0
            # Loop chờ dialog mở - aggressive retry
            while time.time() - start < timeout:
                attempt += 1
                try:
                    _log(logger, f"[UPLOAD-DIALOG] {backend} attempt #{attempt}: connect(timeout=0.5)...")
                    # ⭐ Try to connect with regex, but if multiple matches, get all and pick the "Open" dialog (most recent)
                    try:
                        app = Application(backend=backend).connect(title_re=title_re, timeout=0.5)
                        dlg = app.window(title_re=title_re)
                    except Exception as e:
                        if "2 elements" in str(e) or "multiple" in str(e).lower():
                            # Multiple dialogs match - try to get the main "Open" one
                            _log(logger, f"[UPLOAD-DIALOG] {backend}: Multiple dialogs found, selecting 'Open'...")
                            app = Application(backend=backend).connect(title_re="Open", timeout=0.5)
                            dlg = app.window(title_re="Open")
                        else:
                            raise
                    
                    elapsed = time.time() - start
                    _log(logger, f"[UPLOAD-DIALOG] ✓ {backend}: Dialog found after {elapsed:.2f}s (attempt #{attempt})")
                    break
                except Exception as e:
                    elapsed = time.time() - start
                    _log(logger, f"[UPLOAD-DIALOG] {backend} attempt #{attempt} ({elapsed:.2f}s): {str(e)[:50]}")
                    time.sleep(0.05)  # Retry every 50ms

            if dlg is None:
                _log(logger, f"[UPLOAD-DIALOG] ✗ {backend}: Dialog not found after {timeout}s ({attempt} attempts)")
                return False

            try:
                # Set focus trước
                _log(logger, f"[UPLOAD-DIALOG] {backend}: Setting focus...")
                dlg.set_focus()
                time.sleep(0.1)  # ⭐ Reduced from 0.3s to 0.1s
                _log(logger, f"[UPLOAD-DIALOG] ✓ {backend}: Dialog focused")
                
                # Thử phương pháp 1: set_edit_text qua auto_id=1148
                input_set = False
                try:
                    _log(logger, f"[UPLOAD-DIALOG] {backend}: Trying auto_id=1148...")
                    edit = dlg.child_window(auto_id="1148")
                    _log(logger, f"[UPLOAD-DIALOG] {backend}: Found auto_id=1148, setting text...")
                    edit.set_edit_text(video_path)
                    _log(logger, f"[UPLOAD-DIALOG] ✓ {backend}: Text set via auto_id=1148")
                    input_set = True
                except Exception as e:
                    _log(logger, f"[UPLOAD-DIALOG] {backend}: auto_id=1148 failed - {str(e)[:100]}")
                
                # Thử phương pháp 2: set_edit_text qua Edit class
                if not input_set:
                    try:
                        _log(logger, f"[UPLOAD-DIALOG] {backend}: Trying Edit class...")
                        edit = dlg.child_window(class_name="Edit")
                        _log(logger, f"[UPLOAD-DIALOG] {backend}: Found Edit class, setting text...")
                        edit.set_edit_text(video_path)
                        _log(logger, f"[UPLOAD-DIALOG] ✓ {backend}: Text set via Edit class")
                        input_set = True
                    except Exception as e:
                        _log(logger, f"[UPLOAD-DIALOG] {backend}: Edit class failed - {str(e)[:100]}")
                
                # Thử phương pháp 3: send_keys (gõ từng ký tự)
                if not input_set:
                    _log(logger, f"[UPLOAD-DIALOG] {backend}: Using clipboard+paste method (FAST)...")
                    # Focus lại bằng Alt+N (Filename field)
                    _log(logger, f"[UPLOAD-DIALOG] {backend}: Sending Alt+N...")
                    send_keys("%n")
                    time.sleep(0.1)  # ⭐ Reduced from 0.2s to 0.1s
                    _log(logger, f"[UPLOAD-DIALOG] {backend}: Alt+N sent, pasting...")
                    
                    # ⭐ FAST METHOD: Use clipboard + paste instead of typing each character
                    # This is 10-20x faster than send_keys with pause
                    if PYPERCLIP_AVAILABLE:
                        try:
                            pyperclip.copy(video_path)
                            send_keys("^v")  # Ctrl+V = paste
                            _log(logger, f"[UPLOAD-DIALOG] ✓ {backend}: Path pasted via clipboard (FAST - 10x faster)")
                            input_set = True
                        except Exception as e:
                            _log(logger, f"[UPLOAD-DIALOG] {backend}: clipboard paste failed - {e}, falling back to typing...")
                            # Fallback to typing if clipboard doesn't work
                            _log(logger, f"[UPLOAD-DIALOG] {backend}: Typing path ({len(safe_path)} chars, pause=0.005s - ULTRA FAST)...")
                            send_keys(safe_path, with_spaces=True, pause=0.005)  # ⭐ Reduced from 0.01s to 0.005s
                            input_set = True
                    else:
                        # pyperclip not available, use faster typing
                        _log(logger, f"[UPLOAD-DIALOG] {backend}: Typing path ({len(safe_path)} chars, pause=0.005s - ULTRA FAST)...")
                        send_keys(safe_path, with_spaces=True, pause=0.005)  # ⭐ Reduced from 0.01s to 0.005s
                        input_set = True
                    _log(logger, f"[UPLOAD-DIALOG] ✓ {backend}: Path input complete")
                
                _log(logger, f"[UPLOAD-DIALOG] {backend}: Sending ENTER...")
                send_keys("{ENTER}")
                _log(logger, f"[UPLOAD-DIALOG] ✓ {backend}: ENTER sent")
                return True
            except Exception as e:
                _log(logger, f"[UPLOAD-DIALOG] ✗ {backend}: Error - {e}")
                import traceback
                _log(logger, f"[UPLOAD-DIALOG] Traceback: {traceback.format_exc()}")
                return False

        # Try UIA first, then win32
        _log(logger, f"[UPLOAD-DIALOG] ====== Starting dialog input (timeout={timeout}s) ======")
        # Skip UIA - it causes 210s timeout. Use win32 only
        _log(logger, "[UPLOAD-DIALOG] Skipping UIA (causes long delay), using win32 only...")
        if _try_backend("win32"):
            _log(logger, "[UPLOAD-DIALOG] ✓✓✓ SUCCESS with win32 ✓✓✓")
            return True

        _log(logger, "[UPLOAD-DIALOG] ✗✗✗ win32 FAILED ✗✗✗")
        return False
    finally:
        # ⭐ ALWAYS release semaphore slot when done
        if acquired and semaphore:
            semaphore.release()
            _log(logger, "[UPLOAD-DIALOG] ✓ Released dialog slot (next thread can proceed)")


def _crawl_html_find_select_button(driver, logger: Logger = None) -> Optional[object]:
    """
    Fast HTML crawl to find Select Video button using BeautifulSoup.
    Much faster than Selenium XPath waits.
    """
    try:
        _log(logger, "[UPLOAD] Crawling HTML for Select button...")
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        main = soup.find("main") or soup
        
        # Search for button/div containing "Select video" or "Chọn video"
        keywords = ['Select video', 'Chọn video', 'Select video to upload']
        
        for keyword in keywords:
            # Find elements containing keyword
            elements = main.find_all(['div', 'button'])
            for el in elements:
                text = el.get_text(strip=True)
                if keyword.lower() in text.lower():
                    # Get element id or data attributes to find it with Selenium
                    el_id = el.get('id')
                    el_class = el.get('class', [])
                    
                    if el_id:
                        try:
                            elem = driver.find_element(By.ID, el_id)
                            _log(logger, f"[UPLOAD] Found button via HTML crawl (ID: {el_id})")
                            return elem
                        except Exception:
                            pass
                    
                    # Try by class
                    if el_class:
                        class_str = ' '.join(el_class)
                        try:
                            elem = driver.find_element(By.CLASS_NAME, class_str.split()[0])
                            _log(logger, f"[UPLOAD] Found button via HTML crawl (CLASS: {class_str})")
                            return elem
                        except Exception:
                            pass
                    
                    # Try by XPath text
                    try:
                        elem = driver.find_element(By.XPATH, f"//*[contains(text(), '{keyword}')]")
                        _log(logger, f"[UPLOAD] Found button via HTML crawl (TEXT: {keyword})")
                        return elem
                    except Exception:
                        pass
        
        _log(logger, "[UPLOAD] HTML crawl: button not found in DOM")
        return None
    except Exception as e:
        _log(logger, f"[UPLOAD] HTML crawl error: {e}")
        return None


def _debug_log_all_buttons(driver, logger: Logger = None) -> None:
    """Log all clickable elements to find the real button text"""
    try:
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find all potential clickable elements
        buttons = soup.find_all(['button', 'div', 'a'], limit=50)
        
        found_elements = []
        for btn in buttons:
            text = (btn.get_text(strip=True) or "").strip()
            if text and len(text) < 100:  # Only relevant length texts
                classes = btn.get('class', [])
                role = btn.get('role', '')
                found_elements.append(f"Text: '{text}' | Role: {role} | Class: {' '.join(classes) if classes else 'none'}")
        
        if found_elements:
            _log(logger, "[UPLOAD] === ALL BUTTONS ON PAGE ===")
            for i, elem in enumerate(found_elements[:20], 1):  # First 20
                _log(logger, f"[UPLOAD] {i}. {elem}")
            _log(logger, "[UPLOAD] === END BUTTONS ===")
    except Exception as e:
        _log(logger, f"[UPLOAD] Debug log error: {e}")


def _find_select_video(driver) -> Optional[object]:
    """
    Production-grade selector strategy for finding the "Select video" button.
    Optimized hierarchy: main → cursor-pointer → clickable element
    
    Performance: ~50-300ms vs 15s WebDriverWait fallback
    Thread-safe: No shared state, pure context-based search
    """
    
    # Most specific to least specific (fast-path optimization)
    selector_strategies = [
        # Strategy 1: OPTIMAL - From main→cursor-pointer→button (direct hierarchy)
        {
            "name": "hierarchy_button",
            "xpath": "//main//div[contains(@class,'cursor-pointer')]//*[self::button or (self::div and @role='button')]",
            "keywords": ['Select video', 'Chọn video', 'Select video to upload'],
        },
        # Strategy 2: FAST - Main→cursor-pointer direct (most reliable on this site)
        {
            "name": "hierarchy_div",
            "xpath": "//main//div[contains(@class,'cursor-pointer') and .//div[contains(., 'Select video')]]",
            "keywords": None,  # Text already in XPath
        },
        # Strategy 3: TEXT-BASED - Cursor-pointer containing exact text
        {
            "name": "text_exact",
            "xpath": "//div[@class and contains(@class,'cursor-pointer') and descendant-or-self::*[contains(., 'Select video') or contains(., 'Chọn video')]]",
            "keywords": None,
        },
        # Strategy 4: ROLE-BASED - Semantic (fallback)
        {
            "name": "role_based",
            "xpath": "//*[@role='button' or @role='link'][contains(., 'Select video') or contains(., 'Chọn video')]",
            "keywords": None,
        },
    ]
    
    # Pre-scroll to ensure visibility
    try:
        driver.execute_script("""
            (function() {
                const main = document.querySelector('main');
                if (!main) return;
                const cursorDiv = main.querySelector('div.cursor-pointer');
                if (cursorDiv) cursorDiv.scrollIntoView({block: 'center', behavior: 'instant'});
            })();
        """)
        time.sleep(0.15)
    except Exception:
        pass
    
    # Warm-up delay to let DOM settle (prevent race conditions)
    time.sleep(0.2)
    
    # Try to use main context for faster relative searches
    main_context = None
    try:
        main_context = driver.find_element(By.TAG_NAME, "main")
    except Exception:
        main_context = driver
    
    # Execute selector strategies in order
    for strategy in selector_strategies:
        try:
            context = main_context
            xpath = strategy["xpath"]
            
            # Adjust XPath if using relative context
            if context is not driver and xpath.startswith("//"):
                xpath = "." + xpath
            
            candidates = context.find_elements(By.XPATH, xpath)
            
            # Filter candidates by visibility and keyword match
            for candidate in candidates:
                try:
                    if not candidate.is_displayed():
                        continue
                    
                    # Optional: text verification for keyword strategies
                    if strategy["keywords"]:
                        text = candidate.text or candidate.get_attribute("innerText") or ""
                        if not any(kw.lower() in text.lower() for kw in strategy["keywords"]):
                            continue
                    
                    # Verify element is clickable
                    if candidate.is_enabled():
                        # IMPORTANT: Delay and verify element is still stable (not stale/gone)
                        time.sleep(0.1)
                        try:
                            # Re-verify after delay
                            if candidate.is_displayed() and candidate.is_enabled():
                                return candidate
                        except StaleElementReferenceException:
                            # Element became stale, try next candidate
                            continue
                        except Exception:
                            # Element disappeared, try next
                            continue
                        
                except StaleElementReferenceException:
                    continue
                except Exception:
                    continue
                    
        except (TimeoutException, NoSuchElementException):
            continue
        except Exception:
            continue
    
    # Final fallback: JavaScript-based search (most reliable but slower)
    try:
        element = driver.execute_script("""
            const keywords = ['Select video', 'Chọn video'];
            const main = document.querySelector('main');
            if (!main) return null;
            
            const cursorDiv = main.querySelector('div.cursor-pointer');
            if (!cursorDiv) return null;
            
            // Check if this div contains our keywords
            const text = cursorDiv.textContent || '';
            if (keywords.some(k => text.includes(k))) {
                return cursorDiv;
            }
            return null;
        """)
        if element:
            return element
    except Exception:
        pass
    
    return None


def _find_post_btn(driver) -> Optional[object]:
    """
    Production-grade selector strategy for finding the "Post" button.
    Optimized for single-button search (simpler than Select video).
    
    Performance: ~30-150ms
    Thread-safe: Pure context-based search, no state
    """
    
    # Warm-up delay to let DOM settle
    time.sleep(0.15)
    
    selector_strategies = [
        # Strategy 1: SEMANTIC - Role-based (most reliable)
        {
            "name": "role_button_post",
            "xpath": "//*[@role='button'][contains(., 'Post')]",
        },
        # Strategy 2: HTML TAG - Explicit button tag
        {
            "name": "button_tag",
            "xpath": "//button[contains(., 'Post') or contains(normalize-space(), 'Post')]",
        },
        # Strategy 3: DIV WITH TEXT - Fallback for custom buttons
        {
            "name": "div_post",
            "xpath": "//div[contains(@class, 'button') or contains(@class, 'btn')][contains(., 'Post')]",
        },
        # Strategy 4: GENERIC - Any element with Post text
        {
            "name": "any_post",
            "xpath": "//*[normalize-space()='Post']",
        },
    ]
    
    for strategy in selector_strategies:
        try:
            candidates = driver.find_elements(By.XPATH, strategy["xpath"])
            for candidate in candidates:
                try:
                    if candidate.is_displayed() and candidate.is_enabled():
                        # Verify element is still stable after delay
                        time.sleep(0.08)
                        try:
                            if candidate.is_displayed() and candidate.is_enabled():
                                return candidate
                        except StaleElementReferenceException:
                            continue
                except (StaleElementReferenceException, Exception):
                    continue
        except (NoSuchElementException, Exception):
            continue
    
    # JavaScript fallback
    try:
        element = driver.execute_script("""
            return document.querySelector('button[role="button"], button, [role="button"]')?.textContent?.includes('Post') 
                ? Array.from(document.querySelectorAll('button, [role="button"]')).find(el => el.textContent.includes('Post'))
                : null;
        """)
        if element:
            return element
    except Exception:
        pass
    
    return None


def _is_post_enabled(el) -> bool:
    try:
        if el.get_attribute("disabled"):
            return False
    except Exception:
        pass
    try:
        cls = (el.get_attribute("class") or "").lower()
        if "cursor-not-allowed" in cls:
            return False
        if "text-gray-600" in cls and "bg-gray-800" in cls:
            return False
    except Exception:
        pass
    return True


def _save_html_snapshot(driver, acc_email: str, logger: Logger) -> None:
    if not acc_email:
        return
    safe_name = acc_email.replace("@", "_at_").replace(".", "_")
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "html_snapshots")
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception:
        return
    out_path = os.path.join(out_dir, f"{safe_name}.html")
    try:
        html = driver.page_source or ""
        try:
            soup = BeautifulSoup(html, "html.parser")
            main = soup.find("main")
            html = str(main) if main else html
        except Exception:
            pass
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        _log(logger, f"[UPLOAD] Saved HTML snapshot: {out_path}")
    except Exception as e:
        _log(logger, f"[UPLOAD] Snapshot save failed: {e}")


def _check_circle_available(driver, logger: Logger, timeout: int = 5) -> bool:
    """Check if circle selection feature is available on upload page."""
    try:
        wait = WebDriverWait(driver, max(1, timeout))
        circle_input = wait.until(
            EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Choose a circle']"))
        )
        _log(logger, "[UPLOAD] ✓ Circle feature available")
        return True
    except TimeoutException:
        _log(logger, "[UPLOAD] ✗ Circle feature not available (skipping)")
        return False
    except Exception as e:
        _log(logger, f"[UPLOAD] Circle check failed: {e}")
        return False


def _get_available_circles(driver, logger: Logger, timeout: int = 3) -> list:
    """Get list of available circles from dropdown."""
    try:
        wait = WebDriverWait(driver, max(1, timeout))
        circle_input = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//input[@placeholder='Choose a circle']"))
        )
        
        # Click to show dropdown
        circle_input.click()
        time.sleep(0.3)
        
        # Get all circle options
        circle_elements = wait.until(
            EC.presence_of_all_elements_located((By.XPATH, 
                "//div[@class and contains(@class,'cursor-pointer')]//div[contains(@class,'font-semibold')]"))
        )
        
        circles = []
        for elem in circle_elements:
            text = elem.text.strip()
            if text:
                circles.append(text)
        
        _log(logger, f"[UPLOAD] Available circles: {circles}")
        return circles
    except Exception as e:
        _log(logger, f"[UPLOAD] Failed to get circles: {e}")
        return []


def _find_matching_circle(caption: str, available_circles: list, logger: Logger) -> str:
    """
    Match circle to caption content.
    Returns matching circle name or random circle if no match found.
    """
    if not available_circles:
        return ""
    
    caption_lower = caption.lower()
    
    # Map keywords to circles
    circle_keywords = {
        "OddlySatisfying": ["oddly", "satisfying", "asmr", "soothing", "relaxing"],
        "OutdoorAdventure": ["outdoor", "adventure", "hiking", "camping", "nature", "wild", "extreme"],
        "PublicFreakout": ["freakout", "crazy", "chaos", "wild", "angry", "fight"],
        "TrueCrime": ["crime", "murder", "investigation", "detective", "criminal", "police"],
        "Bodycam": ["bodycam", "body cam", "police", "arrest", "law enforcement"],
        "IndigenousVoices": ["indigenous", "native", "aboriginal", "first nations"],
        "HowDoILook": ["look", "outfit", "fashion", "style", "clothes", "dress"],
        "BootyPhysics": ["booty", "dance", "twerk", "shake"],
        "FightCam": ["fight", "boxing", "mma", "combat", "battle", "duel"],
        "BeFit": ["fitness", "workout", "gym", "exercise", "training", "fit"],
    }
    
    # Score each circle based on keyword matches
    scores = {}
    for circle, keywords in circle_keywords.items():
        if circle in available_circles:
            score = sum(1 for kw in keywords if kw in caption_lower)
            if score > 0:
                scores[circle] = score
    
    if scores:
        best_circle = max(scores.items(), key=lambda x: x[1])[0]
        _log(logger, f"[UPLOAD] Matched circle to caption: {best_circle} (score: {scores[best_circle]})")
        return best_circle
    else:
        # Random selection if no match
        import random
        chosen = random.choice(available_circles)
        _log(logger, f"[UPLOAD] No matching circle found, choosing random: {chosen}")
        return chosen


def _select_circle(driver, circle_name: str, logger: Logger, timeout: int = 10) -> bool:
    """Select a circle from the dropdown menu. If circle_name is empty, skip selection."""
    if not circle_name or circle_name.strip().lower() in ["", "none", "skip"]:
        _log(logger, "[UPLOAD] Skipping circle selection (no circle specified)")
        return True  # Success = skipped without error
    
    try:
        circle_name = circle_name.strip()
        _log(logger, f"[UPLOAD] Attempting to select circle: {circle_name}")
        
        start_time = time.time()
        def _remaining() -> float:
            return max(0.0, timeout - (time.time() - start_time))
        
        wait = WebDriverWait(driver, max(1, int(_remaining())))
        
        # Find and click on the circle search input
        circle_input = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//input[@placeholder='Choose a circle']"))
        )
        _log(logger, "[UPLOAD] Found circle search input")
        
        # Click to focus and show dropdown
        circle_input.click()
        time.sleep(0.5)
        
        # Clear any existing text
        circle_input.clear()
        time.sleep(0.2)
        
        # Type circle name to search
        circle_input.send_keys(circle_name)
        time.sleep(0.8)
        
        # Find circle option in dropdown
        circle_option = wait.until(
            EC.element_to_be_clickable((By.XPATH, 
                f"//div[@class and contains(@class,'cursor-pointer')]//div[contains(@class,'font-semibold') and contains(., '{circle_name}')]/../.."))
        )
        _log(logger, f"[UPLOAD] Found circle option: {circle_name}")
        
        # Click to select
        circle_option.click()
        time.sleep(0.5)
        
        _log(logger, f"[UPLOAD] ✓ Successfully selected circle: {circle_name}")
        return True
        
    except TimeoutException:
        _log(logger, f"[UPLOAD] Circle selection timeout for: {circle_name} (skipping)")
        return True  # Don't fail upload if circle selection times out
    except NoSuchElementException:
        _log(logger, f"[UPLOAD] Circle not found: {circle_name} (skipping)")
        return True  # Don't fail upload if circle not found
    except Exception as e:
        _log(logger, f"[UPLOAD] Circle selection error: {e} (skipping)")
        return True  # Don't fail upload if circle selection fails

def upload_prepare(
    driver_path: str,
    remote_debugging_address: str,
    video_path: str,
    caption: str,
    is_stopped: StopChecker,
    logger: Logger,
    acc_email: str = "",
    circle_name: str = "",
    max_total_s: int = 360,
    file_dialog_semaphore: Optional[threading.BoundedSemaphore] = None,  # ⭐ Serial dialog handling
) -> Tuple[bool, Optional[object], str, str]:
    video_path = os.path.abspath(video_path)
    if not os.path.exists(video_path):
        return False, None, "file_not_found", f"File not found: {video_path}"
    if not driver_path or not remote_debugging_address:
        return False, None, "no_driver", "Missing driver_path / remote_debugging_address"

    driver = None
    start_time = time.time()
    def _remaining() -> float:
        return max(0.0, max_total_s - (time.time() - start_time))

    try:
        driver = _attach_driver(driver_path, remote_debugging_address)
        wait = WebDriverWait(driver, max(1, int(min(60, _remaining()))))

        upload_url = SCOOPZ_URL.rstrip("/") + "/upload"
        _log(logger, f"[UPLOAD] Navigating to upload page: {upload_url}")
        driver.get(upload_url)
        time.sleep(0.8)  # Reduced from 2.0s
        
        # Wait for page to fully load
        try:
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            _log(logger, "[UPLOAD] Page readyState complete")
        except Exception as e:
            _log(logger, f"[UPLOAD] readyState check failed: {e}")
            pass
        
        # Wait a bit more for page to settle, then log initial debug info
        time.sleep(0.3)
        try:
            btn_count = driver.execute_script("return document.querySelectorAll('[role=\"button\"], button, div').length")
            _log(logger, f"[UPLOAD] Page has {btn_count} potential clickable elements")
        except Exception:
            pass
        
        # Wait for body to be ready
        try:
            wait.until(lambda d: d.find_element(By.TAG_NAME, "body").is_displayed())
            _log(logger, "[UPLOAD] Body is displayed")
        except Exception as e:
            _log(logger, f"[UPLOAD] Body check failed: {e}")
            pass
            
        time.sleep(0.5)  # Reduced from 2.0s

        # Save HTML snapshot as soon as upload page is ready
        _save_html_snapshot(driver, acc_email, logger)

        if is_stopped():
            return False, driver, "stopped", "Stopped"

        # Acquire exclusive dialog lock (serial mode)
        orchestrator = get_orchestrator()
        _log(logger, "[UPLOAD] Dialog: waiting for exclusive lock (timeout=30s)...")
        if not orchestrator.acquire_dialog_lock(acc_email, timeout=30.0):
            return False, driver, "dialog_lock_timeout", "Could not acquire dialog lock"
        
        try:
            _log(logger, "[UPLOAD] Dialog: lock acquired")
            orchestrator.wait_for_dialog_open(wait_time=0.2)

            # ===== HTML/XPATH FIND SELECT BUTTON =====
            select_btn = None
            _log(logger, "[UPLOAD] Stage 1: Attempting to find Select button...")
            select_btn = _crawl_html_find_select_button(driver, logger)
            if select_btn is None:
                _log(logger, "[UPLOAD] Stage 1: HTML crawl returned None, trying XPath...")
                select_btn = _find_select_video(driver)
                if select_btn is not None:
                    _log(logger, "[UPLOAD] Stage 1: Found button via XPath")
            else:
                _log(logger, "[UPLOAD] Stage 1: Found button via HTML crawl")
            
            if select_btn is None:
                # Short wait: only 5s (not 15s) - button should already be there
                _log(logger, "[UPLOAD] Stage 2: Button not found, quick wait 5s...")
                try:
                    if _remaining() <= 0:
                        return False, driver, "timeout", "Upload prepare timeout"
                    wait_5 = WebDriverWait(driver, max(1, int(min(5, _remaining()))))
                    select_btn = wait_5.until(lambda d: _crawl_html_find_select_button(d, logger) or _find_select_video(d))
                    _log(logger, "[UPLOAD] Stage 2: Button found after short wait")
                except TimeoutException:
                    _log(logger, "[UPLOAD] Stage 2: Button not found after 5s - page may have failed to load")
                    select_btn = None
            
            if select_btn is None:
                return False, driver, "select_not_found", "Select video button not found"

            # Click the button with Selenium
            try:
                # Verify button is really clickable before attempting click
                try:
                    btn_text = select_btn.text or select_btn.get_attribute("innerText") or ""
                    btn_visible = select_btn.is_displayed()
                    btn_enabled = select_btn.is_enabled()
                    _log(logger, f"[UPLOAD] Button check: text='{btn_text}' visible={btn_visible} enabled={btn_enabled}")
                except Exception as e:
                    _log(logger, f"[UPLOAD] Button attribute check failed: {e}")
                
                if _force_click(driver, select_btn):
                    _log(logger, "[UPLOAD] ✓ Clicked Select button via Selenium")
                    # Wait for dialog to appear (longer wait - file picker takes time)
                    _log(logger, "[UPLOAD] Dialog: waiting 0.5s for dialog to open...")
                    time.sleep(0.3)
                    time.sleep(0.2)
                    _log(logger, "[UPLOAD] Dialog: sleep done, about to call _select_file_in_dialog...")
                else:
                    _log(logger, "[UPLOAD] ✗ _force_click returned False")
                    return False, driver, "select_click_error", "Could not click Select button"
            except Exception as e:
                _log(logger, f"[UPLOAD] ✗ Click error: {e}")
                return False, driver, "select_click_error", f"Select video click error: {e}"
            
            _log(logger, f"[UPLOAD] Dialog: calling _select_file_in_dialog('{video_path}', timeout=15)...")
            ok = _select_file_in_dialog(video_path, logger, timeout=15, semaphore=file_dialog_semaphore)
            _log(logger, f"[UPLOAD] Dialog: _select_file_in_dialog returned {ok}")
            if not ok:
                return False, driver, "dialog_error", "Open dialog failed"
        except Exception as e:
            _log(logger, f"[UPLOAD] Unexpected error: {e}")
            return False, driver, "unexpected_error", f"Unexpected error: {e}"
        finally:
            # Always release dialog lock
            orchestrator.release_dialog_lock("")

        try:
            if _remaining() <= 0:
                return False, driver, "timeout", "Upload prepare timeout"
            wait_caption = WebDriverWait(driver, max(1, int(min(10, _remaining()))))  # Reduced from 20s for faster response
            wait_caption.until(
                EC.presence_of_element_located(
                    (By.XPATH, "//div[contains(@class,'font-bold') and normalize-space()='Caption']")
                )
            )
        except TimeoutException:
            # Caption not appearing = account blocked or page failed to load properly
            return False, driver, "account_blocked", "Account blocked (caption field not found)"

        clean_caption = _sanitize_bmp(caption or "")
        try:
            if _remaining() <= 0:
                return False, driver, "timeout", "Upload prepare timeout"
            editor = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "div.tiptap.ProseMirror[contenteditable='true']"))
            )
            editor.click()
            time.sleep(0.2)
            _set_editor_text(driver, editor, clean_caption)
        except Exception as e:
            return False, driver, "caption_error", f"Caption input error: {e}"

        # Select circle - smart matching based on caption or random
        _log(logger, "[UPLOAD] Checking if circle feature is available...")
        if _check_circle_available(driver, logger, timeout=3):
            # Get available circles
            available_circles = _get_available_circles(driver, logger, timeout=3)
            
            if available_circles:
                # If circle_name specified, use it. Otherwise auto-select based on caption
                if circle_name and circle_name.strip().lower() not in ["", "none", "skip"]:
                    selected_circle = circle_name
                    _log(logger, f"[UPLOAD] Using specified circle: {selected_circle}")
                else:
                    # Auto-match circle to caption or random
                    selected_circle = _find_matching_circle(clean_caption, available_circles, logger)
                
                # Select the circle
                if selected_circle:
                    _log(logger, f"[UPLOAD] Selecting circle: {selected_circle}")
                    _select_circle(driver, selected_circle, logger, timeout=int(max(5, _remaining())))
                    # Note: _select_circle returns True even on error (non-blocking)
            else:
                _log(logger, "[UPLOAD] No circles available")
        else:
            _log(logger, "[UPLOAD] Circle feature not available on this account (skipping)")

        return True, driver, "ok", ""
    except Exception as e:
        return False, driver, "error", f"Upload prepare error: {e}"


def upload_post_async(
    driver, 
    logger: Logger, 
    max_total_s: int = 180,
    post_button_semaphore: Optional[threading.BoundedSemaphore] = None  # ⭐ Serial POST button handling
) -> Tuple[str, str, str, int | None]:
    if driver is None:
        return "error", "No driver", "", None
    try:
        start_time = time.time()
        def _remaining() -> float:
            return max(0.0, max_total_s - (time.time() - start_time))

        def _find_enabled_post():
            btn = _find_post_btn(driver)
            if btn is None:
                return None
            return btn if _is_post_enabled(btn) else None

        try:
            if _remaining() <= 0:
                return "timeout", "Post timeout", "", None
            post_btn = WebDriverWait(driver, max(1, int(_remaining()))).until(lambda d: _find_enabled_post())
        except TimeoutException:
            return "timeout", "Post button not enabled"

        # ⭐ SERIAL POST BUTTON HANDLING: Only 1 thread clicks POST at a time
        acquired = False
        if post_button_semaphore:
            _log(logger, f"[UPLOAD-POST] Waiting for POST button slot (semaphore)...")
            acquired = post_button_semaphore.acquire(timeout=30)
            if not acquired:
                _log(logger, f"[UPLOAD-POST] ✗ Timeout waiting for POST button slot (30s) - other thread using button")
                return "error", "POST button slot timeout", "", None
            _log(logger, f"[UPLOAD-POST] ✓ Got POST button slot, proceeding...")

        try:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", post_btn)
            except Exception:
                pass

            try:
                _log(logger, f"[UPLOAD-POST] Clicking POST button...")
                post_btn.click()
                _log(logger, f"[UPLOAD-POST] ✓ POST button clicked")
            except Exception:
                try:
                    _log(logger, f"[UPLOAD-POST] Direct click failed, using JS click...")
                    driver.execute_script("arguments[0].click();", post_btn)
                    _log(logger, f"[UPLOAD-POST] ✓ POST button clicked (JS)")
                except Exception as e:
                    _log(logger, f"[UPLOAD-POST] ✗ Click POST error: {e}")
                    return "error", f"Click Post error: {e}", "", None

            try:
                if _remaining() <= 0:
                    return "timeout", "Post timeout", "", None
                WebDriverWait(driver, max(1, int(_remaining()))).until(
                    EC.visibility_of_element_located((By.XPATH, "//*[contains(., 'Successfully posted')]"))
                )
                _log(logger, f"[UPLOAD-POST] ✓ Successfully posted message found")
            except TimeoutException:
                _log(logger, f"[UPLOAD-POST] ✗ Post result timeout")
                return "timeout", "Post result timeout", "", None
        finally:
            # ⭐ ALWAYS release POST button slot when done
            if acquired and post_button_semaphore:
                post_button_semaphore.release()
                _log(logger, "[UPLOAD-POST] ✓ Released POST button slot (next thread can proceed)")

        profile_url = ""
        followers = None
        try:
            back_btn = None
            try:
                back_btn = driver.find_element(By.XPATH, "//div[normalize-space()='Back to profile'] | //button[normalize-space()='Back to profile']")
            except Exception:
                back_btn = None
            if back_btn is not None:
                _force_click(driver, back_btn)
                time.sleep(1.2)
        except Exception:
            pass

        try:
            cur_url = (driver.current_url or "").strip()
            if "/@" in cur_url and "/upload" not in cur_url:
                profile_url = cur_url
            else:
                try:
                    prof_link = driver.find_element(By.CSS_SELECTOR, "a[href^='/@']")
                    _force_click(driver, prof_link)
                    time.sleep(1.0)
                    cur_url = (driver.current_url or "").strip()
                    if "/@" in cur_url and "/upload" not in cur_url:
                        profile_url = cur_url
                except Exception:
                    profile_url = ""
        except Exception:
            profile_url = ""
        try:
            foll_el = WebDriverWait(driver, 8).until(
                EC.visibility_of_element_located(
                    (By.XPATH, "//div[.//span[normalize-space()='Followers' or normalize-space()='Follower']]/span[contains(@class,'font-bold')]")
                )
            )
            txt = (foll_el.text or "").strip()
            followers = _parse_followers(txt)
        except Exception:
            followers = None

        return "success", "", profile_url, followers
    except Exception as e:
        return "error", f"Post error: {e}", "", None
