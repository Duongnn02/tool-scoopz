# -*- coding: utf-8 -*-
"""
Centralized logging configuration for the application.
Logs all errors and important events to file and optional console.
"""

import os
import logging
import logging.handlers
from datetime import datetime
from typing import Optional


class ErrorLogger:
    """
    Manages application-wide logging with rotation and formatting.
    Logs to both file and optional console output.
    """
    
    def __init__(self, log_dir: str = "logs", max_bytes: int = 10 * 1024 * 1024, backup_count: int = 5):
        """
        Initialize logger.
        
        Args:
            log_dir: Directory to store log files
            max_bytes: Max size of log file before rotation (10MB default)
            backup_count: Number of backup log files to keep
        """
        self.log_dir = log_dir
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        
        # Create log directory
        os.makedirs(log_dir, exist_ok=True)
        
        # Create loggers for different purposes
        self.main_logger = self._create_logger("main", "app.log")
        self.error_logger = self._create_logger("errors", "errors.log")
        self.upload_logger = self._create_logger("uploads", "uploads.log")
        self.download_logger = self._create_logger("downloads", "downloads.log")
        self.thread_logger = self._create_logger("threads", "threads.log")

    def _create_logger(self, name: str, filename: str) -> logging.Logger:
        """Create and configure a logger instance."""
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        
        # Remove existing handlers
        logger.handlers.clear()
        
        log_path = os.path.join(self.log_dir, filename)
        
        # Rotating file handler
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        
        # Formatter with detailed info
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        
        # Optional console handler for errors only
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        return logger

    def log_download_error(self, account: str, url: str, error: str, exception: Optional[Exception] = None):
        """Log download error."""
        msg = f"[{account}] URL: {url} | Error: {error}"
        if exception:
            self.error_logger.error(f"DOWNLOAD: {msg}", exc_info=exception)
        else:
            self.error_logger.error(f"DOWNLOAD: {msg}")
        self.download_logger.warning(msg)

    def log_upload_error(self, account: str, video_path: str, error: str, exception: Optional[Exception] = None):
        """Log upload error."""
        msg = f"[{account}] Video: {os.path.basename(video_path)} | Error: {error}"
        if exception:
            self.error_logger.error(f"UPLOAD: {msg}", exc_info=exception)
        else:
            self.error_logger.error(f"UPLOAD: {msg}")
        self.upload_logger.warning(msg)

    def log_thread_error(self, account: str, operation: str, error: str, exception: Optional[Exception] = None):
        """Log thread/concurrency error."""
        msg = f"[{account}] Operation: {operation} | Error: {error}"
        if exception:
            self.error_logger.error(f"THREAD: {msg}", exc_info=exception)
        else:
            self.error_logger.error(f"THREAD: {msg}")
        self.thread_logger.warning(msg)

    def log_info(self, account: str, operation: str, message: str):
        """Log general information."""
        msg = f"[{account}] {operation}: {message}"
        self.main_logger.info(msg)

    def log_warning(self, account: str, operation: str, message: str):
        """Log warning."""
        msg = f"[{account}] {operation}: {message}"
        self.main_logger.warning(msg)
        self.error_logger.warning(msg)

    def log_success(self, account: str, operation: str, message: str):
        """Log successful operation."""
        msg = f"[{account}] {operation}: {message}"
        self.main_logger.info(f"✓ {msg}")

    def get_error_summary(self) -> dict:
        """Get summary of errors from log files."""
        error_log = os.path.join(self.log_dir, "errors.log")
        if not os.path.exists(error_log):
            return {"total_errors": 0, "download_errors": 0, "upload_errors": 0, "thread_errors": 0}
        
        try:
            with open(error_log, 'r', encoding='utf-8') as f:
                content = f.read()
            
            total = content.count('\n')
            downloads = content.count('DOWNLOAD:')
            uploads = content.count('UPLOAD:')
            threads = content.count('THREAD:')
            
            return {
                "total_errors": total,
                "download_errors": downloads,
                "upload_errors": uploads,
                "thread_errors": threads,
            }
        except Exception:
            return {}

    def print_error_summary(self):
        """Print error summary to console."""
        summary = self.get_error_summary()
        if summary:
            print("\n" + "="*60)
            print("ERROR SUMMARY")
            print("="*60)
            print(f"Total Errors: {summary.get('total_errors', 0)}")
            print(f"  - Download: {summary.get('download_errors', 0)}")
            print(f"  - Upload: {summary.get('upload_errors', 0)}")
            print(f"  - Thread: {summary.get('thread_errors', 0)}")
            print(f"Log files: {self.log_dir}")
            print("="*60 + "\n")


# Global logger instance
_logger_instance: Optional[ErrorLogger] = None


def get_error_logger() -> ErrorLogger:
    """Get or create global error logger instance."""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = ErrorLogger()
    return _logger_instance


def initialize_logger(log_dir: str = "logs") -> ErrorLogger:
    """Initialize the global logger."""
    global _logger_instance
    _logger_instance = ErrorLogger(log_dir=log_dir)
    return _logger_instance
