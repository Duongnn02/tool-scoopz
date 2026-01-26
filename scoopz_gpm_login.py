# -*- coding: utf-8 -*-
"""
Tool Scoopz: GPM Login + Interaction
Sử dụng GPM để login + tương tác video (like, comment, follow)
"""

import time
import re
from typing import Tuple, Dict, Any

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from gpm_client import (
    build_raw_proxy,
    create_profile,
    start_profile,
    close_profile,
    delete_profile,
    extract_driver_info,
)
from config import SCOOPZ_URL


# Test accounts fix cứng
TEST_ACCOUNTS = [
    {
        "email": "garantwude@hotmail.com",
        "password": "CPYAnnYKa8@",
        "proxy": "145.223.44.84:5767:uvsmvbyr:6d9c706mwyge"
    },
    {
        "email": "ahendmampai@hotmail.com",
        "password": "OmZPOYClq8@",
        "proxy": "166.88.224.158:6056:uvsmvbyr:6d9c706mwyge"
    },
    {
        "email": "ohnatoxlam@hotmail.com",
        "password": "mTmaFNYaz2@",
        "proxy": "104.238.37.68:6625:uvsmvbyr:6d9c706mwyge"
    },
    {
        "email": "cendreefiba@hotmail.com",
        "password": "LnQYzpqlC2@",
        "proxy": "107.173.128.37:7491:uvsmvbyr:6d9c706mwyge"
    },
    {
        "email": "lihanwikto@hotmail.com",
        "password": "IIoKeHKoZ5@",
        "proxy": "154.6.127.85:5556:uvsmvbyr:6d9c706mwyge"
    },
    {
        "email": "unekenslits@hotmail.com",
        "password": "NnGSAoTDk3@",
        "proxy": "64.64.110.142:6665:uvsmvbyr:6d9c706mwyge"
    }
]


class ScoopzGPMLogin:
    """Tool login Scoopz qua GPM"""
    
    def __init__(self, chrome_driver_path: str, logger=None):
        """
        Args:
            chrome_driver_path: Đường dẫn chromedriver
            logger: Hàm log
        """
        self.chrome_driver_path = chrome_driver_path
        self.logger = logger or print
        self.driver = None
        self.wait = None
        
    def _log(self, msg: str) -> None:
        """Log message"""
        try:
            self.logger(msg)
        except Exception:
            print(msg)
    
    def login_scoopz(
        self,
        driver_path: str,
        remote_debug_address: str,
        email: str,
        password: str,
        scoopz_url: str = SCOOPZ_URL
    ) -> Tuple[bool, str]:
        """
        Step 2: Login Scoopz từ GPM profile
        
        Args:
            driver_path: Chromedriver path
            remote_debug_address: GPM remote debug address (127.0.0.1:9222)
            email: Email account
            password: Password
            scoopz_url: Scoopz URL
            
        Returns:
            (success, error_message)
        """
        last_err = ""
        
        try:
            # Attach tới Chrome của GPM
            self._log(f"[LOGIN] Step 2: Attaching to GPM Chrome: {remote_debug_address}")
            options = webdriver.ChromeOptions()
            options.add_experimental_option("debuggerAddress", remote_debug_address.strip())
            service = Service(driver_path)
            driver = webdriver.Chrome(service=service, options=options)
            wait = WebDriverWait(driver, 15)
            
            self._log("[LOGIN] Attached to GPM Chrome")
            time.sleep(1)
            
            # Navigate to Scoopz
            self._log(f"[LOGIN] Opening: {scoopz_url}")
            driver.get(scoopz_url)
            time.sleep(2)
            
            # Check if already logged in
            try:
                driver.find_element(By.XPATH, "//a[starts-with(@href, '/@')]")
                self._log("[LOGIN] Already logged in!")
                driver.quit()
                return True, ""
            except NoSuchElementException:
                self._log("[LOGIN] Not logged in, proceeding...")
            
            # Find login button
            self._log("[LOGIN] Looking for login button...")
            login_btn = None
            
            login_xpaths = [
                "//button[normalize-space()='Login']",
                "//button[normalize-space()='Sign in']",
                "//a[normalize-space()='Login']",
                "//a[normalize-space()='Sign in']",
            ]
            
            for xpath in login_xpaths:
                try:
                    login_btn = driver.find_element(By.XPATH, xpath)
                    if login_btn:
                        self._log("[LOGIN] Login button found")
                        break
                except NoSuchElementException:
                    continue
            
            if not login_btn:
                # Try direct login URL
                self._log("[LOGIN] Login button not found, trying direct URL")
                driver.get(scoopz_url.rstrip("/") + "/login")
                time.sleep(1)
            else:
                login_btn.click()
                time.sleep(1)
            
            # Find email input
            self._log("[LOGIN] Looking for email input...")
            email_xpaths = [
                "//input[@type='email']",
                "//input[@name='email']",
                "//input[contains(@placeholder, 'email')]",
            ]
            
            email_input = None
            for xpath in email_xpaths:
                try:
                    email_input = driver.find_element(By.XPATH, xpath)
                    if email_input:
                        self._log("[LOGIN] Email input found")
                        break
                except NoSuchElementException:
                    continue
            
            if not email_input:
                last_err = "Email input not found"
                self._log(f"[LOGIN] {last_err}")
                driver.quit()
                return False, last_err
            
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
            try:
                password_input = wait.until(
                    EC.presence_of_element_located((By.XPATH, "//input[@type='password']"))
                )
            except TimeoutException:
                last_err = "Password input not found"
                self._log(f"[LOGIN] {last_err}")
                driver.quit()
                return False, last_err
            
            # Enter password
            self._log("[LOGIN] Entering password...")
            password_input.click()
            time.sleep(0.3)
            password_input.clear()
            time.sleep(0.2)
            password_input.send_keys(password)
            time.sleep(0.5)
            
            # Find submit button
            self._log("[LOGIN] Looking for submit button...")
            submit_xpaths = [
                "//button[normalize-space()='Login']",
                "//button[normalize-space()='Sign in']",
                "//button[@type='submit']",
                "//input[@type='submit']",
            ]
            
            submit_btn = None
            for xpath in submit_xpaths:
                try:
                    submit_btn = driver.find_element(By.XPATH, xpath)
                    if submit_btn:
                        self._log("[LOGIN] Submit button found")
                        break
                except NoSuchElementException:
                    continue
            
            if not submit_btn:
                last_err = "Submit button not found"
                self._log(f"[LOGIN] {last_err}")
                driver.quit()
                return False, last_err
            
            # Click submit
            self._log("[LOGIN] Clicking submit...")
            submit_btn.click()
            
            # Wait for login to complete
            self._log("[LOGIN] Waiting for login to complete...")
            time.sleep(3)
            
            # Verify login success
            try:
                wait.until(
                    EC.presence_of_element_located((By.XPATH, "//a[starts-with(@href, '/@')]"))
                )
                self._log("[LOGIN] Step 2: Login successful!")
                time.sleep(1)
                driver.quit()
                return True, ""
            except TimeoutException:
                last_err = "Login verification failed - profile link not found"
                self._log(f"[LOGIN] {last_err}")
                driver.quit()
                return False, last_err
        
        except Exception as e:
            last_err = str(e)
            self._log(f"[LOGIN] Error: {e}")
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
            return False, last_err


def test_login_single(chrome_driver_path: str, account: Dict[str, str]) -> bool:
    """Test login 1 account"""
    
    print(f"\n{'='*60}")
    print(f"Testing: {account['email']}")
    print(f"Proxy: {account['proxy']}")
    print(f"{'='*60}")
    
    # Step 1: Create GPM profile
    print("\n[Step 1] Creating GPM profile...")
    profile_name = re.sub(r"[^a-z0-9_]", "_", account['email'].lower())
    ok_create, data_create, msg_create = create_profile(
        profile_name=profile_name,
        proxy=account['proxy'],
        startup_urls=SCOOPZ_URL,
    )
    
    if not ok_create:
        print(f"❌ Create profile failed: {msg_create}")
        return False
    
    profile_id = (data_create.get("data") or {}).get("id") or data_create.get("id")
    if not profile_id:
        print(f"❌ No profile ID returned")
        return False
    
    print(f"✅ Profile created: {profile_id}")
    
    # Step 2: Start GPM profile
    print("\n[Step 2] Starting GPM profile...")
    ok_start, data_start, msg_start = start_profile(
        profile_id=profile_id,
        win_pos="0,0",
        win_size="390,844"
    )
    
    if not ok_start:
        print(f"❌ Start profile failed: {msg_start}")
        delete_profile(profile_id, timeout=10)
        return False
    
    print(f"✅ Profile started")
    time.sleep(2)
    
    # Extract Chrome driver info
    driver_path, remote = extract_driver_info(data_start)
    if not driver_path or not remote:
        print(f"❌ Failed to extract driver info")
        close_profile(profile_id, timeout=3)
        delete_profile(profile_id, timeout=10)
        return False
    
    print(f"Driver: {driver_path}")
    print(f"Remote: {remote}")
    
    # Step 3: Login
    print("\n[Step 3] Login Scoopz...")
    login_tool = ScoopzGPMLogin(driver_path)
    ok_login, err_login = login_tool.login_scoopz(
        driver_path=driver_path,
        remote_debug_address=remote,
        email=account['email'],
        password=account['password']
    )
    
    if not ok_login:
        print(f"❌ Login failed: {err_login}")
        close_profile(profile_id, timeout=3)
        delete_profile(profile_id, timeout=10)
        return False
    
    print(f"✅ Login successful!")
    
    # Step 4: Close
    print("\n[Step 4] Closing...")
    close_profile(profile_id, timeout=3)
    delete_profile(profile_id, timeout=10)
    
    print(f"✅ Account test successful!\n")
    return True


def main():
    """Main test"""
    chrome_driver_path = r"C:\Users\Admin\Downloads\chromedriver-win64\chromedriver.exe"
    
    print(f"\nScoopz GPM Login Test")
    print(f"Total accounts: {len(TEST_ACCOUNTS)}")
    
    success_count = 0
    fail_count = 0
    
    for idx, account in enumerate(TEST_ACCOUNTS, 1):
        print(f"\n[{idx}/{len(TEST_ACCOUNTS)}]", end=" ")
        try:
            if test_login_single(chrome_driver_path, account):
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            print(f"❌ Exception: {e}")
            fail_count += 1
        
        # Delay between tests
        if idx < len(TEST_ACCOUNTS):
            print("Waiting before next account...")
            time.sleep(3)
    
    print(f"\n\n{'='*60}")
    print(f"Test Results:")
    print(f"  Success: {success_count}/{len(TEST_ACCOUNTS)}")
    print(f"  Failed: {fail_count}/{len(TEST_ACCOUNTS)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
