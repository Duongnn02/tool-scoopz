# -*- coding: utf-8 -*-
"""
Tool tăng view và tương tác (like, comment, follow) trên Scoopz
Sử dụng mobile emulation để giả lập thiết bị di động
"""

import time
import random
import os
from typing import Tuple, Dict, Any, List
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException


class ScoopzInteraction:
    """Tool tương tác video Scoopz với mobile emulation"""
    
    def __init__(self, logger=None, headless=False):
        """
        Args:
            logger: Hàm log message
            headless: Chạy ẩn hay hiển thị
        """
        self.logger = logger or print
        self.headless = headless
        self.driver = None
        self.wait = None
        
    def _log(self, msg: str) -> None:
        """Log message"""
        try:
            self.logger(msg)
        except Exception:
            print(msg)
    
    def init_driver(self, scoopz_url: str = "https://scoopz.com") -> bool:
        """
        Khởi tạo driver với mobile emulation
        
        Args:
            scoopz_url: URL Scoopz
            
        Returns:
            True nếu thành công
        """
        try:
            options = webdriver.ChromeOptions()
            
            # Real mobile emulation - iPhone 12 Pro config
            mobile_emulation = {
                "deviceMetrics": {
                    "width": 390,
                    "height": 844,
                    "pixelRatio": 3.0
                },
                "userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
            }
            options.add_experimental_option("mobileEmulation", mobile_emulation)
            
            if self.headless:
                options.add_argument("--headless=new")
            
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            
            self.driver = webdriver.Chrome(options=options)
            self.wait = WebDriverWait(self.driver, 15)
            
            self._log("[INTERACTION] Driver initialized with mobile emulation")
            return True
        except Exception as e:
            self._log(f"[INTERACTION] Init driver error: {e}")
            return False
    
    def open_video(self, video_url: str) -> bool:
        """
        Mở video từ URL
        
        Args:
            video_url: URL video Scoopz
            
        Returns:
            True nếu thành công
        """
        if not self.driver:
            self._log("[INTERACTION] Driver not initialized")
            return False
        
        try:
            self._log(f"[INTERACTION] Opening video: {video_url}")
            self.driver.get(video_url)
            
            # Wait for video to load
            time.sleep(2)
            try:
                self.wait.until(
                    EC.presence_of_element_located((By.TAG_NAME, "video"))
                )
            except TimeoutException:
                self._log("[INTERACTION] Video element not found, but continuing")
            
            self._log("[INTERACTION] Video page loaded")
            return True
        except Exception as e:
            self._log(f"[INTERACTION] Open video error: {e}")
            return False
    
    def watch_video(self, duration: int = 30) -> bool:
        """
        Xem video trong khoảng thời gian (để tăng view time)
        
        Args:
            duration: Thời gian xem (giây)
            
        Returns:
            True nếu thành công
        """
        try:
            self._log(f"[INTERACTION] Watching video for {duration} seconds...")
            
            # Tìm video element
            try:
                video = self.driver.find_element(By.TAG_NAME, "video")
                # Thử play video
                self.driver.execute_script("arguments[0].play();", video)
                self._log("[INTERACTION] Video playing")
            except Exception as e:
                self._log(f"[INTERACTION] Play video warning: {e}")
            
            # Scroll down một chút để thấy full video
            try:
                self.driver.execute_script("window.scrollBy(0, window.innerHeight / 3);")
                time.sleep(0.5)
            except Exception:
                pass
            
            # Wait khoảng thời gian xem
            time.sleep(duration)
            
            self._log(f"[INTERACTION] Watched {duration} seconds")
            return True
        except Exception as e:
            self._log(f"[INTERACTION] Watch video error: {e}")
            return False
    
    def like_video(self) -> bool:
        """
        Like video
        
        Returns:
            True nếu thành công
        """
        try:
            self._log("[INTERACTION] Looking for like button...")
            
            # Các selector có thể cho like button
            like_selectors = [
                "//button[.//svg[contains(@class, 'like')]]",
                "//button[contains(@class, 'like')]",
                "//button[contains(@aria-label, 'like')]",
                "//button[contains(@aria-label, 'Like')]",
                "//div[@role='button'][contains(., 'Like')]",
                "//button[.//span[contains(text(), 'Like')]]"
            ]
            
            like_btn = None
            for selector in like_selectors:
                try:
                    like_btn = self.driver.find_element(By.XPATH, selector)
                    if like_btn:
                        self._log(f"[INTERACTION] Like button found: {selector}")
                        break
                except NoSuchElementException:
                    continue
            
            if not like_btn:
                self._log("[INTERACTION] Like button not found")
                return False
            
            # Scroll to like button
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", like_btn)
            except Exception:
                pass
            
            time.sleep(0.3)
            
            try:
                like_btn.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", like_btn)
            
            self._log("[INTERACTION] Like button clicked")
            time.sleep(0.5)
            return True
        except Exception as e:
            self._log(f"[INTERACTION] Like video error: {e}")
            return False
    
    def comment_video(self, comment_text: str) -> bool:
        """
        Comment trên video
        
        Args:
            comment_text: Nội dung comment
            
        Returns:
            True nếu thành công
        """
        try:
            self._log(f"[INTERACTION] Looking for comment input...")
            
            # Tìm input comment
            comment_selectors = [
                "//input[@placeholder*='comment']",
                "//input[@placeholder*='Comment']",
                "//textarea[@placeholder*='comment']",
                "//textarea[@placeholder*='Comment']",
                "//div[@contenteditable='true']",
                "//input[contains(@class, 'comment')]"
            ]
            
            comment_input = None
            for selector in comment_selectors:
                try:
                    comment_input = self.driver.find_element(By.XPATH, selector)
                    if comment_input:
                        self._log(f"[INTERACTION] Comment input found: {selector}")
                        break
                except NoSuchElementException:
                    continue
            
            if not comment_input:
                self._log("[INTERACTION] Comment input not found")
                return False
            
            # Scroll to input
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", comment_input)
            except Exception:
                pass
            
            time.sleep(0.3)
            
            # Click và type comment
            try:
                comment_input.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", comment_input)
            
            time.sleep(0.3)
            comment_input.send_keys(comment_text)
            
            self._log(f"[INTERACTION] Comment typed: {comment_text[:50]}...")
            time.sleep(0.5)
            
            # Tìm và click button submit comment
            submit_selectors = [
                "//button[contains(text(), 'Send')]",
                "//button[contains(text(), 'Post')]",
                "//button[contains(@aria-label, 'Send')]",
                "//button[contains(@aria-label, 'Post')]",
                "//button[@type='submit']"
            ]
            
            submit_btn = None
            for selector in submit_selectors:
                try:
                    submit_btn = self.driver.find_element(By.XPATH, selector)
                    if submit_btn:
                        self._log(f"[INTERACTION] Submit button found")
                        break
                except NoSuchElementException:
                    continue
            
            if submit_btn:
                try:
                    submit_btn.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", submit_btn)
                self._log("[INTERACTION] Comment submitted")
            else:
                self._log("[INTERACTION] Submit button not found, trying Enter key")
                comment_input.send_keys(Keys.ENTER)
            
            time.sleep(0.5)
            return True
        except Exception as e:
            self._log(f"[INTERACTION] Comment video error: {e}")
            return False
    
    def follow_channel(self) -> bool:
        """
        Follow channel
        
        Returns:
            True nếu thành công
        """
        try:
            self._log("[INTERACTION] Looking for follow button...")
            
            # Các selector cho follow button
            follow_selectors = [
                "//button[contains(text(), 'Follow')]",
                "//button[contains(@aria-label, 'Follow')]",
                "//button[contains(@aria-label, 'follow')]",
                "//button[contains(text(), 'follow')]",
                "//div[@role='button'][contains(., 'Follow')]"
            ]
            
            follow_btn = None
            for selector in follow_selectors:
                try:
                    follow_btn = self.driver.find_element(By.XPATH, selector)
                    if follow_btn and "unfollow" not in follow_btn.text.lower():
                        self._log(f"[INTERACTION] Follow button found")
                        break
                except NoSuchElementException:
                    continue
            
            if not follow_btn:
                self._log("[INTERACTION] Follow button not found")
                return False
            
            # Scroll to follow button
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", follow_btn)
            except Exception:
                pass
            
            time.sleep(0.3)
            
            try:
                follow_btn.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", follow_btn)
            
            self._log("[INTERACTION] Follow button clicked")
            time.sleep(0.5)
            return True
        except Exception as e:
            self._log(f"[INTERACTION] Follow channel error: {e}")
            return False
    
    def interact_video(
        self,
        video_url: str,
        watch_duration: int = 30,
        do_like: bool = True,
        do_comment: bool = False,
        comment_text: str = "",
        do_follow: bool = True,
        random_actions: bool = True
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Tương tác đầy đủ với video
        
        Args:
            video_url: URL video
            watch_duration: Thời gian xem (giây)
            do_like: Có like không
            do_comment: Có comment không
            comment_text: Nội dung comment
            do_follow: Có follow không
            random_actions: Có random thứ tự action không
            
        Returns:
            (success, result_dict)
        """
        result = {
            "video_url": video_url,
            "watched": False,
            "liked": False,
            "commented": False,
            "followed": False,
            "errors": []
        }
        
        try:
            # Mở video
            if not self.open_video(video_url):
                result["errors"].append("Failed to open video")
                return False, result
            
            # Xem video
            if not self.watch_video(watch_duration):
                result["errors"].append("Failed to watch video")
            else:
                result["watched"] = True
            
            # Random delay
            time.sleep(random.uniform(1, 3))
            
            # Like
            if do_like:
                if self.like_video():
                    result["liked"] = True
                    time.sleep(random.uniform(1, 2))
            
            # Comment
            if do_comment and comment_text:
                if self.comment_video(comment_text):
                    result["commented"] = True
                    time.sleep(random.uniform(1, 2))
            
            # Follow
            if do_follow:
                if self.follow_channel():
                    result["followed"] = True
                    time.sleep(random.uniform(1, 2))
            
            success = result["watched"] or result["liked"] or result["commented"] or result["followed"]
            return success, result
        except Exception as e:
            result["errors"].append(str(e))
            self._log(f"[INTERACTION] Interact video error: {e}")
            return False, result
    
    def close(self) -> None:
        """Đóng driver"""
        if self.driver:
            try:
                self.driver.quit()
                self._log("[INTERACTION] Driver closed")
            except Exception:
                pass


def main():
    """Test function"""
    # Test tương tác video
    interaction = ScoopzInteraction(headless=False)
    
    if not interaction.init_driver():
        print("Failed to initialize driver")
        return
    
    try:
        # Nhập URL video
        # Paste từ clipboard hoặc input từ terminal
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            video_url = root.clipboard_get().strip()
            if video_url:
                print(f"✓ Video URL từ clipboard: {video_url}")
            else:
                raise Exception("Clipboard empty")
        except Exception:
            video_url = input("Enter video URL: ").strip()
        finally:
            root.destroy()
        
        if not video_url:
            print("No URL provided")
            return
        
        # Tương tác video
        success, result = interaction.interact_video(
            video_url=video_url,
            watch_duration=30,
            do_like=True,
            do_comment=False,
            do_follow=True
        )
        
        print(f"\nInteraction Result:")
        print(f"  Success: {success}")
        print(f"  Watched: {result['watched']}")
        print(f"  Liked: {result['liked']}")
        print(f"  Commented: {result['commented']}")
        print(f"  Followed: {result['followed']}")
        if result['errors']:
            print(f"  Errors: {result['errors']}")
    
    finally:
        interaction.close()


if __name__ == "__main__":
    main()
