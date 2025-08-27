# validators/base.py
# Generic normalization and quality-signal utilities (pure Python; no Streamlit).

from __future__ import annotations
import re
import typing as t
import pandas as pd

DIGITS = "0123456789"
ALPHANUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
CHAR_TO_VAL = {c: i for i, c in enumerate(ALPHANUM)}

def normalize_text(value: t.Any) -> str:
    """
    General text normalizer:
    - Convert None/NaN to ""
    - Strip outer spaces
    - Collapse internal whitespace
    """
    if value is None:
        return ""
    s = str(value)
    if s.strip() == "" or s.lower() == "nan":
        return ""
    return " ".join(s.split()).strip()

def normalize_digits(value: t.Any) -> str:
    """
    Keep digits only. Return "" if no digits or input is empty-like.
    """
    s = normalize_text(value)
    if not s:
        return ""
    return re.sub(r"\D+", "", s)

def clean_series_text(series: pd.Series) -> pd.Series:
    """Vectorized normalize_text for a Series."""
    return series.astype(object).apply(normalize_text)

def clean_series_digits(series: pd.Series) -> pd.Series:
    """Vectorized normalize_digits for a Series."""
    return series.astype(object).apply(normalize_digits)

def has_adjacent_repetition(s: str, min_run: int = 3) -> bool:
    """True if any character repeats consecutively at least min_run times."""
    if not s or min_run <= 1:
        return False
    run = 1
    for i in range(1, len(s)):
        if s[i] == s[i - 1]:
            run += 1
            if run >= min_run:
                return True
        else:
            run = 1
    return False

def _has_sequential_run_digits(seq: str, min_run: int = 3) -> bool:
    """Ascending/descending runs in digits with length >= min_run."""
    if len(seq) < min_run:
        return False
    run_up = run_down = 1
    for i in range(1, len(seq)):
        cur = ord(seq[i]) - 48
        prev = ord(seq[i - 1]) - 48
        if 0 <= cur <= 9 and 0 <= prev <= 9:
            if cur == prev + 1:
                run_up += 1; run_down = 1
            elif cur == prev - 1:
                run_down += 1; run_up = 1
            else:
                run_up = run_down = 1
            if run_up >= min_run or run_down >= min_run:
                return True
        else:
            run_up = run_down = 1
    return False

def has_sequential_digits(s: str, min_run: int = 3) -> bool:
    """Check digit-only sequential runs; ignores non-digits."""
    digits = re.sub(r"\D+", "", s or "")
    return _has_sequential_run_digits(digits, min_run=min_run)

def all_same_digit(s: str) -> bool:
    """True if all digits are the same (e.g., 000000000000)."""
    d = re.sub(r"\D+", "", s or "")
    return len(d) > 0 and len(set(d)) == 1

def improbable_pattern(s: str) -> bool:
    """
    Flag a few improbable patterns:
    - all zeros/one repeated digit
    - run like 123456... or 987654...
    """
    d = re.sub(r"\D+", "", s or "")
    if not d:
        return False
    if all_same_digit(d):
        return True
    if has_sequential_digits(d, min_run=max(3, min(6, len(d)))):
        return True
    return False

# Category helpers (field-specific precedence)
def category_aadhaar(reason: str) -> str:
    """
    Map Aadhaar reason -> primary category precedence:
    MISSING → NON_NUMERIC → LENGTH_NEQ_12 → CHECKSUM_FAIL → VALID
    """
    if reason == "": return "VALID"
    order = ["MISSING", "NON_NUMERIC", "LENGTH_NEQ_12", "CHECKSUM_FAIL"]
    return reason if reason in order else "INVALID"

def category_mobile(reason: str) -> str:
    """
    Mobile precedence:
    MISSING → PARSE_FAIL → NOT_VALID → NOT_MOBILE_TYPE → VALID
    """
    if reason == "": return "VALID"
    order = ["MISSING", "PARSE_FAIL", "NOT_VALID", "NOT_MOBILE_TYPE"]
    return reason if reason in order else "INVALID"

def add_quality_flags_digits(df: pd.DataFrame, col: str, prefix: str = "q_") -> pd.DataFrame:
    """Add digit-based quality flags for a column with numeric strings."""
    out = df.copy()
    out[f"{prefix}adjacent_repetition"] = out[col].astype(str).apply(has_adjacent_repetition)
    out[f"{prefix}sequential_digits"] = out[col].astype(str).apply(has_sequential_digits)
    out[f"{prefix}improbable"] = out[col].astype(str).apply(improbable_pattern)
    return out
