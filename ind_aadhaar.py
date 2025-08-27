# validators/ind_aadhaar.py
# Aadhaar validation & masking with Verhoeff checksum (pure functions).

from __future__ import annotations
import typing as t
import pandas as pd
from validators.base import clean_series_digits, normalize_digits, add_quality_flags_digits, category_aadhaar

# Verhoeff tables (multiplication d, permutation p, inverse inv)
_d = [
    [0,1,2,3,4,5,6,7,8,9],
    [1,2,3,4,0,6,7,8,9,5],
    [2,3,4,0,1,7,8,9,5,6],
    [3,4,0,1,2,8,9,5,6,7],
    [4,0,1,2,3,9,5,6,7,8],
    [5,9,8,7,6,0,4,3,2,1],
    [6,5,9,8,7,1,0,4,3,2],
    [7,6,5,9,8,2,1,0,4,3],
    [8,7,6,5,9,3,2,1,0,4],
    [9,8,7,6,5,4,3,2,1,0],
]
_p = [
    [0,1,2,3,4,5,6,7,8,9],
    [1,5,7,6,2,8,3,0,9,4],
    [5,8,0,3,7,9,6,1,4,2],
    [8,9,1,6,0,4,3,5,2,7],
    [9,4,5,3,1,2,6,8,7,0],
    [4,2,8,6,5,7,3,9,0,1],
    [2,7,9,3,8,0,6,4,1,5],
    [7,0,4,6,9,1,3,2,5,8],
]
_inv = [0,4,3,2,1,5,6,7,8,9]

def verhoeff_check_digit(number_without_check: str) -> str:
    """
    Compute Verhoeff check digit for the numeric string (no check digit included).
    """
    c = 0
    rev = list(map(int, reversed(number_without_check)))
    for i, item in enumerate(rev):
        c = _d[c][_p[(i + 1) % 8][item]]
    return str(_inv[c])

def verhoeff_validate(number_with_check: str) -> bool:
    """Validate a full number with its Verhoeff check digit."""
    c = 0
    rev = list(map(int, reversed(number_with_check)))
    for i, item in enumerate(rev):
        c = _d[c][_p[i % 8][item]]
    return c == 0

def mask_aadhaar(a12: str) -> str:
    """
    Mask Aadhaar as XXXX-XXXX-#### (last 4 visible).
    Input is expected to be 12 digits; if shorter, still mask conservatively.
    """
    digits = normalize_digits(a12)
    if not digits:
        return ""
    last4 = digits[-4:] if len(digits) >= 4 else digits
    return f"XXXX-XXXX-{last4:>4}"

def validate_single(aadhaar_like: str) -> dict:
    """
    Validate one Aadhaar-like value. Returns:
    {
      'aadhaar': clean 12-digit or '',
      'valid': bool,
      'reason': '' | MISSING | NON_NUMERIC | LENGTH_NEQ_12 | CHECKSUM_FAIL
    }
    """
    digits = normalize_digits(aadhaar_like)
    out = {"aadhaar": digits, "valid": False, "reason": ""}
    if digits == "":
        out["reason"] = "MISSING"; return out
    if not digits.isdigit():
        out["reason"] = "NON_NUMERIC"; return out
    if len(digits) != 12:
        out["reason"] = "LENGTH_NEQ_12"; return out
    if not verhoeff_validate(digits):
        out["reason"] = "CHECKSUM_FAIL"; return out
    out["valid"] = True
    return out

def validate_series(series: pd.Series) -> pd.DataFrame:
    """
    Vectorized-ish: normalize to digits, row-map validate_single, add quality flags.
    Output columns: ['aadhaar','valid','reason','q_adjacent_repetition','q_sequential_digits','q_improbable']
    """
    s = clean_series_digits(series)
    rows = [validate_single(x) for x in s.tolist()]
    df = pd.DataFrame(rows)
    df = add_quality_flags_digits(df, col="aadhaar", prefix="q_")
    df["category"] = df["reason"].apply(category_aadhaar)
    return df
