# -*- coding: utf-8 -*-
"""
Professional threading utilities for managing concurrent operations.
Handles resource management, locks, and proper cleanup.
"""

import threading
import time
import logging
from typing import Callable, Optional, Any, Dict
from contextlib import contextmanager
from queue import Queue, Empty

logger = logging.getLogger(__name__)


class ResourcePool:
    """
    Manages a pool of named locks for per-resource synchronization.
    Prevents deadlocks from global locks.
    """
    def __init__(self):
        self._locks: Dict[str, threading.RLock] = {}
        self._master_lock = threading.Lock()

    @contextmanager
    def acquire(self, resource_id: str, timeout: float = 30.0):
        """Acquire lock for specific resource."""
        with self._master_lock:
            if resource_id not in self._locks:
                self._locks[resource_id] = threading.RLock()
            lock = self._locks[resource_id]
        
        acquired = lock.acquire(timeout=timeout)
        if not acquired:
            raise TimeoutError(f"Could not acquire lock for {resource_id} within {timeout}s")
        
        try:
            yield
        finally:
            lock.release()

    def cleanup(self, resource_id: str):
        """Remove lock for resource."""
        with self._master_lock:
            self._locks.pop(resource_id, None)


class RetryHelper:
    """Implements exponential backoff retry logic."""
    
    @staticmethod
    def retry_with_backoff(
        func: Callable,
        max_attempts: int = 3,
        base_wait: float = 1.0,
        max_wait: float = 30.0,
        backoff_multiplier: float = 2.0,
        logger_func: Optional[Callable] = None,
    ) -> tuple:
        """
        Execute function with exponential backoff retry.
        
        Returns: (success: bool, result: Any, error: Optional[str])
        """
        last_error = None
        
        for attempt in range(1, max_attempts + 1):
            try:
                result = func()
                if logger_func:
                    logger_func(f"✓ Success on attempt {attempt}")
                return True, result, None
            except Exception as e:
                last_error = str(e)
                if attempt < max_attempts:
                    wait_time = min(base_wait * (backoff_multiplier ** (attempt - 1)), max_wait)
                    if logger_func:
                        logger_func(f"✗ Attempt {attempt} failed: {e}. Retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                else:
                    if logger_func:
                        logger_func(f"✗ All {max_attempts} attempts failed: {e}")
        
        return False, None, last_error


class ThreadSafeCounter:
    """Thread-safe counter for tracking operations."""
    
    def __init__(self, initial: int = 0):
        self._value = initial
        self._lock = threading.Lock()

    def increment(self, delta: int = 1) -> int:
        with self._lock:
            self._value += delta
            return self._value

    def decrement(self, delta: int = 1) -> int:
        with self._lock:
            self._value -= delta
            return self._value

    def get(self) -> int:
        with self._lock:
            return self._value

    def reset(self) -> None:
        with self._lock:
            self._value = 0


class DriverManager:
    """
    Manages driver lifecycle safely across threads.
    Ensures proper cleanup and prevents resource leaks.
    """
    def __init__(self, driver_path: str, remote_addr: str):
        self.driver_path = driver_path
        self.remote_addr = remote_addr
        self._driver = None
        self._lock = threading.RLock()
        self._usage_count = 0
        self._last_access = time.time()

    def get_driver(self):
        """Get driver instance."""
        with self._lock:
            self._usage_count += 1
            self._last_access = time.time()
            if self._driver is None:
                self._create_driver()
            return self._driver

    def _create_driver(self):
        """Create driver instance (override in subclass)."""
        # To be implemented by subclass
        pass

    def is_idle(self, timeout_s: float = 60.0) -> bool:
        """Check if driver is idle."""
        with self._lock:
            return (time.time() - self._last_access) > timeout_s and self._usage_count == 0

    def cleanup(self):
        """Cleanup driver resources."""
        with self._lock:
            if self._driver:
                try:
                    self._driver.quit()
                except Exception:
                    pass
                self._driver = None
            self._usage_count = 0


class BoundedThreadPool:
    """
    Custom thread pool with bounded resource management.
    Prevents resource exhaustion from unlimited threads.
    """
    def __init__(self, max_workers: int, max_queue: int = 100):
        self.max_workers = max_workers
        self.task_queue: Queue = Queue(maxsize=max_queue)
        self.workers = []
        self._running = False
        self._shutdown_lock = threading.Lock()

    def start(self):
        """Start worker threads."""
        with self._shutdown_lock:
            if self._running:
                return
            self._running = True
            
        for _ in range(self.max_workers):
            worker = threading.Thread(target=self._worker, daemon=False)
            worker.start()
            self.workers.append(worker)

    def _worker(self):
        """Worker thread main loop."""
        while self._running:
            try:
                task_func, args, kwargs = self.task_queue.get(timeout=1)
                if task_func is None:  # Sentinel value for shutdown
                    break
                try:
                    task_func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Task failed: {e}")
            except Empty:
                continue

    def submit(self, func: Callable, *args, **kwargs):
        """Submit task to pool."""
        if not self._running:
            raise RuntimeError("Thread pool not started")
        self.task_queue.put((func, args, kwargs))

    def shutdown(self, wait: bool = True):
        """Shutdown thread pool."""
        with self._shutdown_lock:
            self._running = False
            
        if wait:
            # Send sentinel values to workers
            for _ in range(self.max_workers):
                self.task_queue.put((None, (), {}))
            
            for worker in self.workers:
                worker.join(timeout=10)
