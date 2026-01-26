# -*- coding: utf-8 -*-
"""
Tool tương tác Scoopz dùng GPM profile
Step 1: Init GPM profile + Login Scoopz
Step 2: Interact video (like, comment, follow)
"""

import time
import os
from typing import Tuple, Dict, Any
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException


class ScoopzGPMInteraction:
    """Tool tương tác Scoopz qua GPM profile"""
    
    def __init__(self, logger=None):
        """
        Args:
            logger: Hàm log message
        """
        self.logger = logger or print
        self.driver = None
        self.wait = None
        
    def _log(self, msg: str) -> None:
        """Log message"""
        try:
            self.logger(msg)
        except Exception:
            print(msg)
    
    def init_gpm_profile(
        self,
        gpm_path: str,
        profile_id: str,
        profile_name: str,
        proxy: str = ""
    ) -> bool:
        """
        Step 1: Khởi tạo GPM profile và attach Chrome
        
        Args:
            gpm_path: Đường dẫn GPM (ví dụ: "C:\\Program Files\\GPM\\gpm.exe")
            profile_id: ID profile trong GPM
            profile_name: Tên profile
            proxy: Proxy (format: ip:port hoặc ip:port:user:pass)
            
        Returns:
            True nếu thành công
        """
        try:
            self._log(f"[GPM] Step 1: Initializing GPM profile: {profile_name}")
            
            # Kiểm tra GPM executable tồn tại
            if not os.path.exists(gpm_path):
                self._log(f"[GPM] GPM executable not found: {gpm_path}")
                return False
            
            # TODO: Gọi GPM API/CLI để start profile
            # Tạm thời chỉ log, sau implement GPM subprocess call
            self._log(f"[GPM] Profile ID: {profile_id}")
            self._log(f"[GPM] Profile Name: {profile_name}")
            if proxy:
                self._log(f"[GPM] Proxy: {proxy}")
            
            time.sleep(1)
            self._log("[GPM] Step 1: GPM profile initialized (ready to attach Chrome)")
            return True
            
        except Exception as e:
            self._log(f"[GPM] Step 1 error: {e}")
            return False
    
    def attach_chrome_to_gpm(
        self,
        chrome_driver_path: str,
        remote_debug_port: int = 9222
    ) -> bool:
        """
        Step 1B: Attach Chrome driver tới GPM profile
        
        Args:
            chrome_driver_path: Đường dẫn chromedriver
            remote_debug_port: Port debug Chrome (từ GPM)
            
        Returns:
            True nếu thành công
        """
        try:
            self._log(f"[GPM] Step 1B: Attaching Chrome to GPM (port: {remote_debug_port})")
            
            # Connect tới Chrome via remote debugging
            options = webdriver.ChromeOptions()
            options.add_experimental_option(
                "debuggerAddress",
                f"127.0.0.1:{remote_debug_port}"
            )
            
            service = webdriver.ChromeService(chrome_driver_path)
            self.driver = webdriver.Chrome(service=service, options=options)
            self.wait = WebDriverWait(self.driver, 15)
            
            self._log("[GPM] Step 1B: Chrome attached successfully")
            time.sleep(1)
            return True
            
        except Exception as e:
            self._log(f"[GPM] Step 1B error: {e}")
            return False
    
    def login_scoopz(
        self,
        email: str,
        password: str,
        scoopz_url: str = "https://scoopz.com"
    ) -> bool:
        """
        Step 2: Login Scoopz
        
        Args:
            email: Email account
            password: Password
            scoopz_url: Scoopz URL
            
        Returns:
            True nếu thành công
        """
        if not self.driver:
            self._log("[LOGIN] Driver not initialized")
            return False
        
        try:
            self._log(f"[LOGIN] Step 2: Logging in to Scoopz: {email}")
            
            # Navigate to Scoopz
            self._log(f"[LOGIN] Opening: {scoopz_url}")
            self.driver.get(scoopz_url)
            time.sleep(2)
            
            # Check if already logged in
            try:
                self.driver.find_element(By.CSS_SELECTOR, "a[href*='/@']")
                self._log("[LOGIN] Already logged in (profile link found)")
                return True
            except NoSuchElementException:
                self._log("[LOGIN] Not logged in, proceeding with login")
            
            # Find login button/link
            self._log("[LOGIN] Looking for login button...")
            login_btn = None
            
            login_selectors = [
                "//button[contains(text(), 'Login')]",
                "//button[contains(text(), 'Sign in')]",
                "//a[contains(text(), 'Login')]",
                "//a[contains(text(), 'Sign in')]",
                "//button[contains(@class, 'login')]"
            ]
            
            for selector in login_selectors:
                try:
                    login_btn = self.driver.find_element(By.XPATH, selector)
                    if login_btn:
                        self._log(f"[LOGIN] Login button found")
                        break
                except NoSuchElementException:
                    continue
            
            if not login_btn:
                self._log("[LOGIN] Login button not found, checking URL...")
                # Try direct login URL
                login_url = scoopz_url.rstrip("/") + "/login"
                self.driver.get(login_url)
                time.sleep(1)
            else:
                login_btn.click()
                time.sleep(1)
            
            # Find email input
            self._log("[LOGIN] Looking for email input...")
            email_selectors = [
                "//input[@type='email']",
                "//input[@name='email']",
                "//input[@placeholder*='email']",
                "//input[@placeholder*='Email']"
            ]
            
            email_input = None
            for selector in email_selectors:
                try:
                    email_input = self.driver.find_element(By.XPATH, selector)
                    if email_input:
                        self._log("[LOGIN] Email input found")
                        break
                except NoSuchElementException:
                    continue
            
            if not email_input:
                self._log("[LOGIN] Email input not found")
                return False
            
            # Enter email
            self._log("[LOGIN] Entering email...")
            email_input.click()
            time.sleep(0.3)
            email_input.clear()
            time.sleep(0.2)
            email_input.send_keys(email)
            time.sleep(0.5)
            
            # Find password input
            self._log("[LOGIN] Looking for password input...")
            password_input = self.driver.find_element(By.XPATH, "//input[@type='password']")
            if not password_input:
                self._log("[LOGIN] Password input not found")
                return False
            
            # Enter password
            self._log("[LOGIN] Entering password...")
            password_input.click()
            time.sleep(0.3)
            password_input.clear()
            time.sleep(0.2)
            password_input.send_keys(password)
            time.sleep(0.5)
            
            # Find and click submit button
            self._log("[LOGIN] Looking for submit button...")
            submit_selectors = [
                "//button[contains(text(), 'Login')]",
                "//button[contains(text(), 'Sign in')]",
                "//button[@type='submit']",
                "//input[@type='submit']"
            ]
            
            submit_btn = None
            for selector in submit_selectors:
                try:
                    submit_btn = self.driver.find_element(By.XPATH, selector)
                    if submit_btn:
                        self._log("[LOGIN] Submit button found")
                        break
                except NoSuchElementException:
                    continue
            
            if not submit_btn:
                self._log("[LOGIN] Submit button not found")
                return False
            
            # Click submit
            self._log("[LOGIN] Clicking submit...")
            submit_btn.click()
            
            # Wait for login to complete
            self._log("[LOGIN] Waiting for login to complete...")
            time.sleep(3)
            
            # Verify login success
            try:
                self.wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/@']"))
                )
                self._log("[LOGIN] Step 2: Login successful!")
                time.sleep(1)
                return True
            except TimeoutException:
                self._log("[LOGIN] Login verification failed")
                return False
            
        except Exception as e:
            self._log(f"[LOGIN] Step 2 error: {e}")
            return False
    
    def close(self) -> None:
        """Đóng driver"""
        if self.driver:
            try:
                self.driver.quit()
                self._log("[GPM] Driver closed")
            except Exception:
                pass


def main():
    """Test Step 1 + Step 2"""
    interaction = ScoopzGPMInteraction(logger=print)
    
    # Input from user
    print("\n=== Scoopz GPM Interaction Tool ===")
    print("Step 1: Initialize GPM Profile")
    print("Step 2: Login Scoopz\n")
    
    # GPM Config
    gpm_path = input("Enter GPM path (e.g., C:\\Program Files\\GPM\\gpm.exe): ").strip()
    profile_id = input("Enter GPM Profile ID: ").strip()
    profile_name = input("Enter GPM Profile Name: ").strip()
    proxy = input("Enter Proxy (optional, format: ip:port): ").strip()
    
    # Step 1: Init GPM
    if not interaction.init_gpm_profile(gpm_path, profile_id, profile_name, proxy):
        print("Failed to init GPM profile")
        return
    
    # Manual: User should start GPM profile and get remote debug port
    remote_port = input("Enter Chrome remote debug port (default 9222): ").strip() or "9222"
    chrome_driver = input("Enter chromedriver path: ").strip()
    
    # Step 1B: Attach Chrome
    if not interaction.attach_chrome_to_gpm(chrome_driver, int(remote_port)):
        print("Failed to attach Chrome")
        interaction.close()
        return
    
    # Step 2: Login
    email = input("Enter Scoopz email: ").strip()
    password = input("Enter Scoopz password: ").strip()
    
    if not interaction.login_scoopz(email, password):
        print("Failed to login")
        interaction.close()
        return
    
    print("\n✅ Login successful!")
    print("Session saved in GPM profile - won't logout when Chrome closes")
    print("Ready for next step: Video interaction\n")
    
    # Keep driver open for testing
    input("Press Enter to close...")
    interaction.close()


if __name__ == "__main__":
    main()
