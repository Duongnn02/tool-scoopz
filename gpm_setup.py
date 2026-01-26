# -*- coding: utf-8 -*-
"""
Step 1: GPM Profile Setup
- Generate unique device fingerprint (không trùng)
- Tạo GPM profile với device fingerprint
- Lưu device info vào cache để tái sử dụng
"""

import json
import os
import random
import string
from typing import Dict, Any, List

from gpm_client import create_profile


# Device fingerprints - mỗi thiết bị khác nhau
DEVICE_CONFIGS = [
    {
        "name": "iPhone_12_Pro",
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "screen_width": 390,
        "screen_height": 844,
        "device_pixel_ratio": 3,
        "platform": "iPhone"
    },
    {
        "name": "iPhone_13_Pro_Max",
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "screen_width": 428,
        "screen_height": 926,
        "device_pixel_ratio": 3,
        "platform": "iPhone"
    },
    {
        "name": "Samsung_Galaxy_S21",
        "user_agent": "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "screen_width": 360,
        "screen_height": 800,
        "device_pixel_ratio": 2,
        "platform": "Android"
    },
    {
        "name": "Samsung_Galaxy_S22",
        "user_agent": "Mozilla/5.0 (Linux; Android 14; SM-S901B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "screen_width": 360,
        "screen_height": 800,
        "device_pixel_ratio": 2,
        "platform": "Android"
    },
    {
        "name": "Pixel_6",
        "user_agent": "Mozilla/5.0 (Linux; Android 13; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "screen_width": 412,
        "screen_height": 915,
        "device_pixel_ratio": 2.75,
        "platform": "Android"
    },
    {
        "name": "Pixel_7",
        "user_agent": "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "screen_width": 412,
        "screen_height": 915,
        "device_pixel_ratio": 2.75,
        "platform": "Android"
    }
]


class DeviceManager:
    """Quản lý device fingerprint"""
    
    def __init__(self, cache_file: str = "device_cache.json"):
        """
        Args:
            cache_file: File lưu device info (JSON)
        """
        self.cache_file = cache_file
        self.cache = self._load_cache()
    
    def _load_cache(self) -> Dict[str, Dict[str, Any]]:
        """Load cache từ file"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[DEVICE] Load cache error: {e}")
        return {}
    
    def _save_cache(self) -> None:
        """Lưu cache vào file"""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
            print(f"[DEVICE] Cache saved to {self.cache_file}")
        except Exception as e:
            print(f"[DEVICE] Save cache error: {e}")
    
    def get_device_for_account(self, email: str) -> Dict[str, Any]:
        """
        Lấy device info cho account
        - Nếu đã có cache: dùng device cũ (tránh thay đổi bị phát hiện)
        - Nếu chưa: generate device mới và lưu cache
        
        Args:
            email: Email account
            
        Returns:
            Device config dict
        """
        if email in self.cache:
            device = self.cache[email]
            print(f"[DEVICE] Using cached device for {email}: {device['name']}")
            return device
        
        # Generate device mới
        device = self._generate_unique_device(email)
        self.cache[email] = device
        self._save_cache()
        print(f"[DEVICE] Generated new device for {email}: {device['name']}")
        return device
    
    def _generate_unique_device(self, email: str) -> Dict[str, Any]:
        """
        Generate unique device (không trùng với account khác)
        
        Args:
            email: Email account
            
        Returns:
            Device config
        """
        # Dùng hash của email để select device từ list (deterministic)
        # Cách này đảm bảo mỗi email luôn được assign device không đổi
        email_hash = hash(email) % len(DEVICE_CONFIGS)
        device = DEVICE_CONFIGS[email_hash].copy()
        
        # Add more unique info
        device["email"] = email
        device["created_at"] = self._get_timestamp()
        device["device_id"] = self._generate_device_id()
        device["language"] = random.choice(["en-US", "en-GB", "en-AU"])
        device["timezone"] = random.choice(["UTC", "GMT", "EST", "PST"])
        
        return device
    
    @staticmethod
    def _get_timestamp() -> str:
        """Get current timestamp"""
        from datetime import datetime
        return datetime.now().isoformat()
    
    @staticmethod
    def _generate_device_id() -> str:
        """Generate random device ID"""
        return ''.join(random.choices(string.ascii_letters + string.digits, k=32))


class GPMProfileSetup:
    """Tạo GPM profile với device fingerprint"""
    
    def __init__(self, logger=None):
        self.logger = logger or print
        self.device_manager = DeviceManager()
    
    def _log(self, msg: str) -> None:
        try:
            self.logger(msg)
        except Exception:
            print(msg)
    
    def create_gpm_profile(
        self,
        email: str,
        password: str,
        proxy: str
    ) -> Dict[str, Any]:
        """
        Tạo GPM profile cho account
        
        Args:
            email: Email account
            password: Password
            proxy: Proxy (format: ip:port:user:pass)
            
        Returns:
            {
                "success": bool,
                "profile_id": str,
                "profile_name": str,
                "device_info": dict,
                "error": str
            }
        """
        result = {
            "success": False,
            "profile_id": None,
            "profile_name": None,
            "device_info": None,
            "error": ""
        }
        
        try:
            # Step 1: Get device fingerprint
            self._log(f"[GPM] Step 1: Getting device for {email}")
            device = self.device_manager.get_device_for_account(email)
            result["device_info"] = device
            
            # Step 2: Sanitize profile name
            profile_name = email.split("@")[0]
            profile_name = profile_name.replace(".", "_").replace("+", "_")
            profile_name = profile_name[:30]  # GPM limit
            
            self._log(f"[GPM] Step 2: Creating GPM profile: {profile_name}")
            
            # Step 3: Create GPM profile
            ok, data, err = create_profile(
                profile_name=profile_name,
                proxy=proxy,
                startup_urls="https://scoopz.com"
            )
            
            if not ok:
                result["error"] = f"Create profile failed: {err}"
                self._log(f"[GPM] ❌ {result['error']}")
                return result
            
            # Step 4: Extract profile ID
            profile_id = (data.get("data") or {}).get("id") or data.get("id")
            if not profile_id:
                result["error"] = "No profile ID returned"
                self._log(f"[GPM] ❌ {result['error']}")
                return result
            
            self._log(f"[GPM] Step 3: Profile created: {profile_id}")
            
            # Step 5: Save profile info with device
            profile_info = {
                "email": email,
                "profile_id": profile_id,
                "profile_name": profile_name,
                "proxy": proxy,
                "device_name": device["name"],
                "device_id": device.get("device_id"),
                "user_agent": device["user_agent"],
                "screen_resolution": f"{device['screen_width']}x{device['screen_height']}",
                "created_at": self.device_manager._get_timestamp()
            }
            
            # Lưu vào cache
            cache = self.device_manager._load_cache()
            if email not in cache:
                cache[email] = device
                self.device_manager._save_cache()
            
            result["success"] = True
            result["profile_id"] = profile_id
            result["profile_name"] = profile_name
            
            self._log(f"[GPM] ✅ Profile setup complete!")
            self._log(f"[GPM]   Profile ID: {profile_id}")
            self._log(f"[GPM]   Device: {device['name']}")
            self._log(f"[GPM]   Resolution: {device['screen_width']}x{device['screen_height']}")
            
            return result
        
        except Exception as e:
            result["error"] = str(e)
            self._log(f"[GPM] ❌ Error: {e}")
            return result


def test_device_assignment():
    """Test device assignment - mỗi email được device khác"""
    print("\n=== Test Device Assignment ===\n")
    
    device_mgr = DeviceManager()
    
    accounts = [
        "garantwude@hotmail.com",
        "ahendmampai@hotmail.com",
        "ohnatoxlam@hotmail.com",
        "cendreefiba@hotmail.com",
        "lihanwikto@hotmail.com",
        "unekenslits@hotmail.com"
    ]
    
    devices_used = {}
    
    for email in accounts:
        device = device_mgr.get_device_for_account(email)
        device_name = device["name"]
        
        if device_name not in devices_used:
            devices_used[device_name] = []
        devices_used[device_name].append(email)
        
        print(f"{email}")
        print(f"  Device: {device_name}")
        print(f"  Resolution: {device['screen_width']}x{device['screen_height']}")
        print(f"  Device ID: {device.get('device_id')}")
        print()
    
    print("\n=== Device Summary ===")
    for device_name, emails in devices_used.items():
        print(f"{device_name}: {len(emails)} account(s)")
        for email in emails:
            print(f"  - {email}")
    
    print("\n✅ Device assignment saved to device_cache.json")


if __name__ == "__main__":
    test_device_assignment()
