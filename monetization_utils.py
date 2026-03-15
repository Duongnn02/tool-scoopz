# -*- coding: utf-8 -*-
"""Helpers for monetization status normalization and summary formatting."""


def normalize_payment_status(status: str) -> str:
    text = (status or "").strip().upper()
    if text == "SETUP":
        return "SETUP"
    if text == "CHECK_ERR":
        return "CHECK_ERR"
    # UNKNOWN/empty/legacy statuses are treated as NOT_SETUP.
    return "NOT_SETUP"


def format_stats_count_map(counts: dict, preferred_order: list | None = None) -> str:
    if not counts:
        return "-"
    parts = []
    used = set()
    for key in preferred_order or []:
        if key in counts:
            parts.append(f"{key}:{counts[key]}")
            used.add(key)
    for key in sorted(k for k in counts.keys() if k not in used):
        parts.append(f"{key}:{counts[key]}")
    return " | ".join(parts)
