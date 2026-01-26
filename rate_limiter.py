# -*- coding: utf-8 -*-
"""
Rate limiting and delay management for safe operations.
Prevents server overload and browser automation detection.
"""

import time
from typing import Callable, Optional
from collections import defaultdict
from threading import Lock


class RateLimiter:
    """
    Rate limiter per account to prevent server rate limiting.
    Uses exponential backoff on consecutive failures.
    """
    
    def __init__(self):
        self.last_request_time = defaultdict(float)
        self.failure_count = defaultdict(int)
        self.lock = Lock()
    
    def wait_before_request(self, account_id: str, min_delay: float = 2.0):
        """
        Wait appropriate time before next request for account.
        Implements exponential backoff on failures.
        """
        with self.lock:
            now = time.time()
            last_time = self.last_request_time.get(account_id, 0)
            failures = self.failure_count.get(account_id, 0)
            
            # Calculate delay with exponential backoff
            # failures=0: 2s, failures=1: 4s, failures=2: 8s, failures=3+: 15s
            backoff = min(2 ** failures, 15)
            required_delay = max(min_delay, backoff)
            
            elapsed = now - last_time
            wait_time = required_delay - elapsed
            
            if wait_time > 0:
                return wait_time
            return 0
    
    def record_request(self, account_id: str):
        """Record that request was made."""
        with self.lock:
            self.last_request_time[account_id] = time.time()
    
    def record_success(self, account_id: str):
        """Record successful operation - reset failure count."""
        with self.lock:
            self.failure_count[account_id] = 0
    
    def record_failure(self, account_id: str):
        """Record failure - increase backoff."""
        with self.lock:
            self.failure_count[account_id] += 1
    
    def reset(self, account_id: str):
        """Reset rate limiter for account."""
        with self.lock:
            self.last_request_time.pop(account_id, None)
            self.failure_count.pop(account_id, None)


class OperationDelayer:
    """
    Smart delayer for operations with configurable strategies.
    """
    
    # Delay strategy constants
    STRATEGY_CONSERVATIVE = "conservative"  # Max delays, very safe
    STRATEGY_BALANCED = "balanced"          # Medium delays, balanced
    STRATEGY_AGGRESSIVE = "aggressive"      # Minimal delays, faster
    
    def __init__(self, strategy: str = STRATEGY_BALANCED):
        self.strategy = strategy
        self.rate_limiter = RateLimiter()
        self._configure_delays()
    
    def _configure_delays(self):
        """Configure delays based on strategy."""
        if self.strategy == self.STRATEGY_CONSERVATIVE:
            self.delay_between_downloads = 5.0    # Wait 5s between downloads
            self.delay_between_uploads = 8.0      # Wait 8s between uploads
            self.delay_between_accounts = 3.0     # Wait 3s between switching accounts
            self.delay_on_error = 10.0            # Wait 10s on error
        elif self.strategy == self.STRATEGY_AGGRESSIVE:
            self.delay_between_downloads = 1.0
            self.delay_between_uploads = 2.0
            self.delay_between_accounts = 0.5
            self.delay_on_error = 3.0
        else:  # BALANCED
            self.delay_between_downloads = 3.0
            self.delay_between_uploads = 5.0
            self.delay_between_accounts = 1.5
            self.delay_on_error = 6.0
    
    def delay_before_download(self, account_id: str, logger: Optional[Callable] = None):
        """Smart delay before downloading."""
        wait_time = self.rate_limiter.wait_before_request(account_id, self.delay_between_downloads)
        if wait_time > 0.1:
            if logger:
                logger(f"[{account_id}] Waiting {wait_time:.1f}s before download...")
            time.sleep(wait_time)
        self.rate_limiter.record_request(account_id)
    
    def delay_before_upload(self, account_id: str, logger: Optional[Callable] = None):
        """Smart delay before uploading."""
        wait_time = self.rate_limiter.wait_before_request(account_id, self.delay_between_uploads)
        if wait_time > 0.1:
            if logger:
                logger(f"[{account_id}] Waiting {wait_time:.1f}s before upload...")
            time.sleep(wait_time)
        self.rate_limiter.record_request(account_id)
    
    def delay_before_next_account(self, logger: Optional[Callable] = None):
        """Delay between switching to next account."""
        if self.delay_between_accounts > 0.1:
            if logger:
                logger(f"Switching account in {self.delay_between_accounts:.1f}s...")
            time.sleep(self.delay_between_accounts)
    
    def delay_on_error(self, account_id: str, error_type: str, logger: Optional[Callable] = None):
        """Extended delay on error."""
        self.rate_limiter.record_failure(account_id)
        wait_time = self.delay_on_error
        if logger:
            logger(f"[{account_id}] Error ({error_type}). Waiting {wait_time:.1f}s...")
        time.sleep(wait_time)
    
    def set_strategy(self, strategy: str):
        """Change delay strategy."""
        if strategy in [self.STRATEGY_CONSERVATIVE, self.STRATEGY_BALANCED, self.STRATEGY_AGGRESSIVE]:
            self.strategy = strategy
            self._configure_delays()


class SequentialProcessor:
    """
    Process items sequentially per account to prevent concurrent access issues.
    """
    
    def __init__(self):
        self.processing_account = {}  # Track which thread is processing which account
        self.lock = Lock()
    
    def can_process_account(self, account_id: str, thread_id: int) -> bool:
        """Check if this thread can process this account."""
        with self.lock:
            if account_id not in self.processing_account:
                self.processing_account[account_id] = thread_id
                return True
            return self.processing_account[account_id] == thread_id
    
    def release_account(self, account_id: str):
        """Release account after processing."""
        with self.lock:
            self.processing_account.pop(account_id, None)
    
    def wait_for_account(self, account_id: str, timeout: float = 300.0) -> bool:
        """Wait until account is available."""
        import threading
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self.lock:
                if account_id not in self.processing_account:
                    return True
            time.sleep(0.5)
        return False


# Global instances
_rate_limiter: Optional[RateLimiter] = None
_operation_delayer: Optional[OperationDelayer] = None
_sequential_processor: Optional[SequentialProcessor] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create global rate limiter."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


def get_operation_delayer(strategy: str = OperationDelayer.STRATEGY_BALANCED) -> OperationDelayer:
    """Get or create global operation delayer."""
    global _operation_delayer
    if _operation_delayer is None:
        _operation_delayer = OperationDelayer(strategy)
    return _operation_delayer


def get_sequential_processor() -> SequentialProcessor:
    """Get or create global sequential processor."""
    global _sequential_processor
    if _sequential_processor is None:
        _sequential_processor = SequentialProcessor()
    return _sequential_processor


def initialize_rate_limiting(strategy: str = OperationDelayer.STRATEGY_BALANCED):
    """Initialize rate limiting system."""
    global _rate_limiter, _operation_delayer, _sequential_processor
    _rate_limiter = RateLimiter()
    _operation_delayer = OperationDelayer(strategy)
    _sequential_processor = SequentialProcessor()
