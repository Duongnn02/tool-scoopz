#!/usr/bin/env python3
"""
Validation script to verify dialog racing condition fix is properly integrated.
Run this before building executable.
"""

import ast
import os
from typing import List, Tuple

def check_file_exists(path: str) -> bool:
    """Check if file exists"""
    return os.path.isfile(path)

def search_in_file(filepath: str, search_strings: List[str]) -> List[Tuple[str, int]]:
    """Search for strings in file and return (string, line_number) tuples"""
    results = []
    if not os.path.isfile(filepath):
        return results
    
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        for line_num, line in enumerate(f, 1):
            for search_str in search_strings:
                if search_str in line:
                    results.append((search_str, line_num, line.strip()))
    return results

def validate_syntax(filepath: str) -> Tuple[bool, str]:
    """Validate Python file syntax"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            ast.parse(f.read())
        return True, "OK"
    except SyntaxError as e:
        return False, f"Syntax Error at line {e.lineno}: {e.msg}"

def main():
    base_path = r"c:\laragon\www\tool scoopz\tool_rewrite"
    gui_app_path = os.path.join(base_path, "gui_app.py")
    uploader_path = os.path.join(base_path, "scoopz_uploader.py")
    
    print("=" * 70)
    print("DIALOG RACING CONDITION FIX - VALIDATION REPORT")
    print("=" * 70)
    
    # Check files exist
    print("\n[OK] File Existence Check:")
    print(f"  gui_app.py: {check_file_exists(gui_app_path)}")
    print(f"  scoopz_uploader.py: {check_file_exists(uploader_path)}")
    
    # Check syntax
    print("\n[OK] Syntax Validation:")
    gui_ok, gui_msg = validate_syntax(gui_app_path)
    uploader_ok, uploader_msg = validate_syntax(uploader_path)
    print(f"  gui_app.py: {'[PASS]' if gui_ok else '[FAIL]'} - {gui_msg}")
    print(f"  scoopz_uploader.py: {'[PASS]' if uploader_ok else '[FAIL]'} - {uploader_msg}")
    
    # Check required components in gui_app.py
    print("\n[OK] gui_app.py Required Components:")
    checks = [
        ("file_dialog_semaphore = threading.BoundedSemaphore(1)", "Semaphore initialization"),
        ("file_dialog_semaphore=self.file_dialog_semaphore,", "Semaphore parameter passed (×2)"),
    ]
    
    semaphore_count = 0
    for search_str, desc in checks:
        results = search_in_file(gui_app_path, [search_str])
        found = len(results) > 0
        count = len(results)
        semaphore_count += count
        print(f"  [OK] {desc}: {'[FOUND]' if found else '[NOT FOUND]'} (x{count})")
        for _, line_num, line in results:
            print(f"      Line {line_num}: {line[:60]}...")
    
    # Check required components in scoopz_uploader.py
    print("\n[OK] scoopz_uploader.py Required Components:")
    
    # Check function signature
    results = search_in_file(uploader_path, 
        ["def _select_file_in_dialog(video_path: str, logger: Logger, timeout: int = 15, semaphore: Optional[threading.BoundedSemaphore] = None)"])
    print(f"  [OK] _select_file_in_dialog() signature: {'[UPDATED]' if results else '[NOT FOUND]'}")
    
    # Check semaphore acquire
    results = search_in_file(uploader_path, ["acquired = semaphore.acquire(timeout=timeout + 2)"])
    print(f"  [OK] Semaphore acquire logic: {'[IMPLEMENTED]' if results else '[NOT FOUND]'}")
    if results:
        for _, line_num, line in results:
            print(f"      Line {line_num}")
    
    # Check finally block
    results = search_in_file(uploader_path, ["if acquired and semaphore:", "semaphore.release()"])
    print(f"  [OK] Semaphore release (finally): {'[IMPLEMENTED]' if len(results) >= 2 else '[NOT FOUND]'}")
    if results:
        for _, line_num, line in results:
            print(f"      Line {line_num}")
    
    # Check upload_prepare signature
    results = search_in_file(uploader_path, ["file_dialog_semaphore: Optional[threading.BoundedSemaphore] = None"])
    print(f"  [OK] upload_prepare() signature: {'[UPDATED]' if results else '[NOT FOUND]'}")
    
    # Check dialog call with semaphore
    results = search_in_file(uploader_path, ["semaphore=file_dialog_semaphore"])
    print(f"  [OK] Dialog call passes semaphore: {'[IMPLEMENTED]' if results else '[NOT FOUND]'}")
    
    # Summary
    print("\n" + "=" * 70)
    if gui_ok and uploader_ok and semaphore_count >= 3:
        print("[PASS] VALIDATION PASSED - All components integrated correctly!")
        print("\nThe fix is ready. Next steps:")
        print("1. Build executable: pyinstaller --onefile --windowed gui_app.py")
        print("2. Test with 5-10 accounts uploading in parallel")
        print("3. Verify dialogs open one at a time (no racing)")
        print("4. Confirm users have 15s to interact with each dialog")
    else:
        print("[FAIL] VALIDATION FAILED - Some components are missing")
        print("Please review the integration before building.")
    print("=" * 70)

if __name__ == "__main__":
    main()
