# -*- coding: utf-8 -*-
"""
CSV storage management for Scoopz video shorts.
Handles reading, updating, and tracking video upload status.
Thread-safe operations for concurrent access.
"""

import os
import csv
import threading
from typing import Tuple, Dict, Any

# Global lock for CSV operations
_CSV_LOCK = threading.Lock()


def _get_csv_path(email: str) -> str:
    """Get the CSV file path for an email account."""
    email_safe = (
        (email or "unknown")
        .strip()
        .replace("@", "_at_")
        .replace(".", "_")
        .replace(":", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )
    this_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(this_dir, "video", email_safe, "shorts.csv")
    return csv_path


def get_next_unuploaded(email: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Get the next unuploaded video from the CSV file.
    
    Returns:
        (success, row_or_error_dict)
        - If success: (True, row_dict with keys: video_id, title, url, status)
        - If no unuploaded video: (False, {"msg": "error message"})
    """
    csv_path = _get_csv_path(email)
    
    if not os.path.exists(csv_path):
        return False, {"msg": f"CSV file not found: {csv_path}"}
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if not reader:
                return False, {"msg": "CSV file is empty"}
            
            for row in reader:
                # Skip already uploaded videos
                status = (row.get("status") or "").strip().lower()
                if status != "true":
                    return True, row
            
            # No unuploaded videos found
            return False, {"msg": "All videos uploaded"}
    except Exception as e:
        return False, {"msg": f"Error reading CSV: {e}"}


def mark_uploaded(email: str, video_id: str) -> bool:
    """
    Mark a video as uploaded (status=true) in the CSV file.
    Thread-safe operation.
    
    Args:
        email: Account email
        video_id: Video ID to mark as uploaded
    
    Returns:
        True if successful, False otherwise
    """
    csv_path = _get_csv_path(email)
    
    if not os.path.exists(csv_path):
        return False
    
    with _CSV_LOCK:  # Atomic operation
        try:
            # Read all rows
            rows = []
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                for row in reader:
                    rows.append(row)
            
            # Update the matching row
            updated = False
            for row in rows:
                vid = (row.get("video_id") or "").strip()
                if vid == video_id:
                    row["status"] = "true"
                    updated = True
                    break
            
            # Write back if updated
            if updated:
                with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                return True
            
            return False
        except Exception:
            return False


def update_title_if_empty(email: str, video_id: str, title: str) -> bool:
    """
    Update video title in CSV if it's empty.
    
    Args:
        email: Account email
        video_id: Video ID to update
        title: New title to set if empty
    
    Returns:
        True if successful or no update needed, False on error
    """
    csv_path = _get_csv_path(email)
    
    if not os.path.exists(csv_path):
        return False
    
    try:
        # Read all rows
        rows = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                rows.append(row)
        
        # Update the matching row if title is empty
        updated = False
        for row in rows:
            vid = (row.get("video_id") or "").strip()
            if vid == video_id:
                current_title = (row.get("title") or "").strip()
                if not current_title and title:
                    row["title"] = title
                    updated = True
                break
        
        # Write back if updated
        if updated:
            with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            return True
        
        return True  # Success even if no update needed
    except Exception:
        return False




def load_shorts(email: str):
    csv_path = _get_csv_path(email)
    rows = []
    if not os.path.exists(csv_path):
        return rows
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except Exception:
        return []
    return rows


def prepend_new_shorts(email: str, videos):
    """Prepend new videos to CSV, thread-safe."""
    csv_path = _get_csv_path(email)
    
    with _CSV_LOCK:  # Atomic operation
        existing = load_shorts(email)
        index = {row.get("video_id"): row for row in existing if row.get("video_id")}

        new_rows = []
        added = 0
        for v in videos:
            if not v.get("video_id"):
                continue
            vid = (v.get("video_id") or "").strip()
            if not vid:
                continue
            if vid in index:
                if v.get("title"):
                    index[vid]["title"] = v["title"]
                if v.get("url"):
                    index[vid]["url"] = v["url"]
                continue
            new_rows.append(
                {
                    "video_id": vid,
                    "title": v.get("title", ""),
                    "url": v.get("url", ""),
                    "status": "false",
                }
            )
            added += 1

        existing_updated = []
        for row in existing:
            vid = row.get("video_id")
            if vid in index:
                existing_updated.append(index[vid])
            else:
                existing_updated.append(row)

        final_rows = new_rows + existing_updated

        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        fieldnames = ["video_id", "title", "url", "status"]
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in final_rows:
                writer.writerow(row)

        return len(final_rows), added
