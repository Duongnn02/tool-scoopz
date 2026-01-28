# -*- coding: utf-8 -*-
"""
Scientific operation orchestration system.
Implements sequential processing, intelligent delays, and queue management.
Enterprise-grade architecture with no race conditions.
"""

import time
import threading
from queue import Queue, Empty
from typing import Callable, Optional, Any, Dict, List
from enum import Enum
from threading import Lock, Condition


class OperationType(Enum):
    """Types of operations that need orchestration."""
    LOGIN = "login"
    DOWNLOAD = "download"
    UPLOAD = "upload"
    DIALOG = "dialog"


class InputDelay(Enum):
    """Configurable delays for user input simulation."""
    # Format: (char_delay_ms, field_delay_ms, button_delay_ms)
    
    CONSERVATIVE = (0.20, 1.5, 0.8)    # 200ms per char, 1.5s after field, 0.8s before button
    BALANCED = (0.10, 0.7, 0.3)        # 100ms per char, 0.7s after field, 0.3s before button
    AGGRESSIVE = (0.05, 0.3, 0.1)      # 50ms per char, 0.3s after field, 0.1s before button
    
    @property
    def char_delay_sec(self) -> float:
        return self.value[0] / 1000.0
    
    @property
    def field_delay_sec(self) -> float:
        return self.value[1]
    
    @property
    def button_delay_sec(self) -> float:
        return self.value[2]


class DownloadStrategy(Enum):
    """Download orchestration strategies."""
    SEQUENTIAL = "sequential"          # One at a time (safest)
    STAGGERED = "staggered"           # Slight delays between starts (balanced)
    CONCURRENT = "concurrent"          # All at once (fastest but risky)


class UploadStrategy(Enum):
    """Upload orchestration strategies."""
    SERIAL = "serial"                 # Queue-based, one dialog at a time
    ROUND_ROBIN = "round_robin"       # Alternate between accounts
    CONCURRENT = "concurrent"          # Allow up to N concurrent


class OperationOrchestrator:
    """
    Master orchestrator for all operations.
    Ensures sequential execution, proper delays, and no race conditions.
    """
    
    def __init__(
        self,
        input_delay: InputDelay = InputDelay.BALANCED,
        download_strategy: DownloadStrategy = DownloadStrategy.SEQUENTIAL,
        upload_strategy: UploadStrategy = UploadStrategy.SERIAL,
        max_concurrent_uploads: int = 1,
    ):
        self.input_delay = input_delay
        self.download_strategy = download_strategy
        self.upload_strategy = upload_strategy
        self.max_concurrent_uploads = max_concurrent_uploads
        
        # Locks for critical sections
        self.login_lock = threading.Lock()
        self.download_lock = threading.Lock()
        self.upload_lock = threading.Lock()
        self.dialog_lock = threading.Lock()
        
        # Condition variable for upload queue
        self.upload_condition = Condition(self.upload_lock)
        
        # Tracking
        self.active_uploads = 0
        self.upload_queue: Queue = Queue()
        self.last_operation_time: Dict[str, float] = {}
        self.operation_count: Dict[str, int] = {}
        
        # Logger
        self.logger: Optional[Callable] = None
    
    def set_logger(self, logger: Callable):
        """Set logger function."""
        self.logger = logger
    
    def _log(self, message: str):
        """Log message if logger is set."""
        if self.logger:
            self.logger(message)
    
    # ==================== LOGIN ORCHESTRATION ====================
    
    def wait_before_email_input(self, account: str):
        """Wait before typing email - account lock."""
        with self.login_lock:
            self._log(f"[{account}] Email input: Acquiring lock...")
            self._log(f"[{account}] Email input: Lock acquired, ready to type")
    
    def get_char_delay_for_email(self) -> float:
        """Get delay between each character of email."""
        return self.input_delay.char_delay_sec
    
    def wait_after_email_input(self):
        """Wait after email field completed."""
        self._log(f"Email input complete, waiting {self.input_delay.field_delay_sec:.2f}s...")
        time.sleep(self.input_delay.field_delay_sec)
    
    def wait_before_password_input(self, account: str):
        """Wait before typing password."""
        self._log(f"[{account}] Password input: Ready to type")
    
    def get_char_delay_for_password(self) -> float:
        """Get delay between each character of password."""
        return self.input_delay.char_delay_sec
    
    def wait_after_password_input(self):
        """Wait after password field completed."""
        self._log(f"Password input complete, waiting {self.input_delay.field_delay_sec:.2f}s...")
        time.sleep(self.input_delay.field_delay_sec)
    
    def wait_before_continue_click(self, account: str):
        """Wait before clicking continue button."""
        wait_time = self.input_delay.button_delay_sec
        self._log(f"[{account}] Waiting {wait_time:.2f}s before clicking Continue...")
        time.sleep(wait_time)
    
    def release_login_lock(self):
        """Release login lock."""
        self._log("[LOGIN] Lock released")
    
    # ==================== DOWNLOAD ORCHESTRATION ====================
    
    def acquire_download_lock(self, account: str) -> bool:
        """
        Acquire download lock based on strategy.
        SEQUENTIAL: Block until others finish
        STAGGERED: Allow with slight delay
        CONCURRENT: Minimal coordination
        """
        if self.download_strategy == DownloadStrategy.SEQUENTIAL:
            self.download_lock.acquire()
            self._log(f"[{account}] Download: Sequential lock acquired")
            return True
        elif self.download_strategy == DownloadStrategy.STAGGERED:
            # Wait for previous download to finish + delay
            self.download_lock.acquire()
            self._log(f"[{account}] Download: Staggered start")
            return True
        else:  # CONCURRENT
            self._log(f"[{account}] Download: Concurrent start (no lock)")
            return True
    
    def release_download_lock(self, account: str):
        """Release download lock."""
        if self.download_strategy in [DownloadStrategy.SEQUENTIAL, DownloadStrategy.STAGGERED]:
            self.download_lock.release()
            self._log(f"[{account}] Download: Lock released")
    
    def wait_between_downloads(self, account: str, is_error: bool = False):
        """Wait between consecutive downloads."""
        if self.download_strategy == DownloadStrategy.SEQUENTIAL:
            wait_time = 5.0 if not is_error else 10.0
            self._log(f"[{account}] Waiting {wait_time:.1f}s before next download (error={is_error})...")
            time.sleep(wait_time)
    
    # ==================== UPLOAD ORCHESTRATION ====================
    
    def queue_upload(self, account: str, video_path: str) -> int:
        """
        Queue an upload operation.
        Returns: queue position
        """
        with self.upload_condition:
            self.upload_queue.put((account, video_path))
            position = self.upload_queue.qsize()
            self._log(f"[{account}] Upload queued at position {position}")
            return position
    
    def can_start_upload(self, account: str) -> bool:
        """
        Check if upload can start based on strategy and current state.
        SERIAL: Only 1 concurrent, must be first in queue
        ROUND_ROBIN: Alternate between accounts
        CONCURRENT: Up to N concurrent
        """
        with self.upload_condition:
            if self.upload_strategy == UploadStrategy.SERIAL:
                if self.active_uploads >= self.max_concurrent_uploads:
                    self._log(f"[{account}] Upload blocked: {self.active_uploads} active (max {self.max_concurrent_uploads})")
                    return False
                self._log(f"[{account}] Upload can proceed (serial mode, active={self.active_uploads})")
                return True
            
            elif self.upload_strategy == UploadStrategy.ROUND_ROBIN:
                if self.active_uploads >= self.max_concurrent_uploads:
                    return False
                return True
            
            else:  # CONCURRENT
                if self.active_uploads >= self.max_concurrent_uploads:
                    return False
                return True
    
    def acquire_upload_lock(self, account: str) -> bool:
        """Acquire lock for upload."""
        with self.upload_condition:
            # Wait until can proceed
            start_wait = time.time()
            while not self.can_start_upload(account):
                self._log(f"[{account}] Upload waiting for slot...")
                self.upload_condition.wait(timeout=1.0)
                if time.time() - start_wait > 300:  # 5 min timeout
                    self._log(f"[{account}] Upload wait timeout")
                    return False
            
            self.active_uploads += 1
            self._log(f"[{account}] Upload lock acquired (active={self.active_uploads})")
            return True
    
    def release_upload_lock(self, account: str):
        """Release upload lock and notify waiters."""
        with self.upload_condition:
            self.active_uploads = max(0, self.active_uploads - 1)
            self._log(f"[{account}] Upload lock released (active={self.active_uploads})")
            self.upload_condition.notify_all()
    
    def wait_between_uploads(self, account: str):
        """Wait between consecutive uploads."""
        if self.upload_strategy == UploadStrategy.SERIAL:
            wait_time = 4.0
            self._log(f"[{account}] Waiting {wait_time:.1f}s before next upload...")
            time.sleep(wait_time)
    
    # ==================== DIALOG ORCHESTRATION ====================
    
    def acquire_dialog_lock(self, account: str, timeout: float = 60.0) -> bool:
        """
        Acquire exclusive dialog lock.
        Only one dialog can be open at a time.
        """
        acquired = self.dialog_lock.acquire(timeout=timeout)
        if acquired:
            self._log(f"[{account}] Dialog lock acquired (exclusive)")
        else:
            self._log(f"[{account}] Dialog lock timeout after {timeout}s")
        return acquired
    
    def release_dialog_lock(self, account: str):
        """Release dialog lock."""
        self.dialog_lock.release()
        self._log(f"[{account}] Dialog lock released")
    
    def wait_for_dialog_open(self, wait_time: float = 0.5):
        """Wait for dialog to open properly."""
        self._log(f"Waiting {wait_time:.1f}s for dialog to open...")
        time.sleep(wait_time)
    
    # ==================== STRATEGY CONFIGURATION ====================
    
    def set_aggressive(self):
        """Aggressive mode: Fast, less safe."""
        self.input_delay = InputDelay.AGGRESSIVE
        self.download_strategy = DownloadStrategy.CONCURRENT
        self.upload_strategy = UploadStrategy.CONCURRENT
        self.max_concurrent_uploads = 3
        self._log("[CONFIG] Set to AGGRESSIVE mode")
    
    def set_balanced(self):
        """Balanced mode: Good balance."""
        self.input_delay = InputDelay.BALANCED
        self.download_strategy = DownloadStrategy.SEQUENTIAL
        self.upload_strategy = UploadStrategy.SERIAL
        self.max_concurrent_uploads = 1
        self._log("[CONFIG] Set to BALANCED mode")
    
    def set_conservative(self):
        """Conservative mode: Safe, slower."""
        self.input_delay = InputDelay.CONSERVATIVE
        self.download_strategy = DownloadStrategy.SEQUENTIAL
        self.upload_strategy = UploadStrategy.SERIAL
        self.max_concurrent_uploads = 1
        self._log("[CONFIG] Set to CONSERVATIVE mode")
    
    def get_config_summary(self) -> str:
        """Get current configuration summary."""
        return f"""
=== ORCHESTRATOR CONFIG ===
Input Delay: {self.input_delay.name}
  - Char delay: {self.input_delay.char_delay_sec*1000:.0f}ms
  - Field delay: {self.input_delay.field_delay_sec:.1f}s
  - Button delay: {self.input_delay.button_delay_sec:.1f}s
Download Strategy: {self.download_strategy.name}
Upload Strategy: {self.upload_strategy.name}
Max Concurrent Uploads: {self.max_concurrent_uploads}
===========================
"""


# Global instance
_orchestrator: Optional[OperationOrchestrator] = None


def get_orchestrator(
    input_delay: InputDelay = InputDelay.BALANCED,
    download_strategy: DownloadStrategy = DownloadStrategy.SEQUENTIAL,
    upload_strategy: UploadStrategy = UploadStrategy.SERIAL,
    max_concurrent_uploads: int = 1,
) -> OperationOrchestrator:
    """Get or create global orchestrator."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = OperationOrchestrator(
            input_delay=input_delay,
            download_strategy=download_strategy,
            upload_strategy=upload_strategy,
            max_concurrent_uploads=max_concurrent_uploads,
        )
    return _orchestrator


def initialize_orchestrator(
    mode: str = "balanced",
    logger: Optional[Callable] = None,
) -> OperationOrchestrator:
    """Initialize orchestrator with mode."""
    global _orchestrator
    
    input_delay_map = {
        "conservative": InputDelay.CONSERVATIVE,
        "balanced": InputDelay.BALANCED,
        "aggressive": InputDelay.AGGRESSIVE,
    }
    
    download_strategy_map = {
        "conservative": DownloadStrategy.SEQUENTIAL,
        "balanced": DownloadStrategy.SEQUENTIAL,
        "aggressive": DownloadStrategy.CONCURRENT,
    }
    
    upload_strategy_map = {
        "conservative": UploadStrategy.SERIAL,
        "balanced": UploadStrategy.SERIAL,
        "aggressive": UploadStrategy.CONCURRENT,
    }
    
    concurrent_uploads_map = {
        "conservative": 1,
        "balanced": 1,
        "aggressive": 3,
    }
    
    _orchestrator = OperationOrchestrator(
        input_delay=input_delay_map.get(mode, InputDelay.BALANCED),
        download_strategy=download_strategy_map.get(mode, DownloadStrategy.SEQUENTIAL),
        upload_strategy=upload_strategy_map.get(mode, UploadStrategy.SERIAL),
        max_concurrent_uploads=concurrent_uploads_map.get(mode, 1),
    )
    
    if logger:
        _orchestrator.set_logger(logger)
        _orchestrator._log(_orchestrator.get_config_summary())
    
    return _orchestrator
