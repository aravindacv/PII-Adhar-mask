# validators/phone.py
# Phone parsing/validation & masking using 'phonenumbers' (Google lib).

from __future__ import annotations
import typing as t
import re
import pandas as pd
import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberType

from validators.base import normalize_text

E164_RE = re.compile(r"^\+(\d{1,3})(\d{3})(\d{3})(\d+)$")  # for masking fallback

def mask_e164(e164: str) -> str:
    """
    Mask a phone in E.164 as +CC-XXX-XXX-####, keeping last 4.
    If not enough digits for that grouping, fall back to generic last-4.
    """
    if not e164 or not e164.startswith("+"):
        return ""
    m = E164_RE.match(e164)
    if m:
        cc, a, b, rest = m.groups()
        last4 = rest[-4:] if len(rest) >= 4 else rest
        return f"+{cc}-XXX-XXX-{last4}"
    # Fallback: keep country code and last 4 of the remainder
    cc = ""
    rest = e164
    if e164.startswith("+"):
        # split country code heuristically: up to 3 digits after '+'
        cc = e164[1:4] if e164[1:4].isdigit() else ""
    digits = re.sub(r"\D+", "", e164)
    last4 = digits[-4:] if len(digits) >= 4 else digits
    return f"+{cc}-****-****-{last4}" if cc else f"***-***-{last4}"

def validate_single_phone(raw: str, default_region: str = "IN") -> dict:
    """
    Validate/standardize one phone number.
    Returns:
    {
      'raw': original,
      'e164': '+CCXXXXXXXXX' | '',
      'valid': bool,
      'reason': '' | MISSING | PARSE_FAIL | NOT_VALID | NOT_MOBILE_TYPE,
      'region': 'IN'/'US'/... where parsable,
      'type': 'MOBILE'/'FIXED_LINE_OR_MOBILE'/other
    }
    """
    s = normalize_text(raw)
    out = {"raw": s, "e164": "", "valid": False, "reason": "", "region": "", "type": ""}
    if s == "":
        out["reason"] = "MISSING"; return out
    try:
        num = phonenumbers.parse(s, default_region or "IN")
    except NumberParseException:
        out["reason"] = "PARSE_FAIL"; return out

    if not phonenumbers.is_possible_number(num):
        out["reason"] = "NOT_VALID"; return out
    if not phonenumbers.is_valid_number(num):
        out["reason"] = "NOT_VALID"; return out

    ntype = phonenumbers.number_type(num)
    out["type"] = PhoneNumberType.to_string(ntype) if hasattr(PhoneNumberType, "to_string") else str(ntype)
    # Accept MOBILE or FIXED_LINE_OR_MOBILE as "mobile"
    if ntype not in (PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE):
        out["reason"] = "NOT_MOBILE_TYPE"; return out

    out["e164"] = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    out["region"] = phonenumbers.region_code_for_number(num) or (default_region or "")
    out["valid"] = True
    return out

def validate_series(phone_series: pd.Series, region_series: t.Optional[pd.Series] = None, default_region: str = "IN") -> pd.DataFrame:
    """
    Apply validate_single_phone row-wise. Region per row if provided, else fallback to default_region.
    Output columns: ['raw','e164','valid','reason','region','type','masked']
    """
    raw = phone_series.astype(object)
    if region_series is not None:
        reg = region_series.fillna("").astype(str).str.upper()
    else:
        reg = pd.Series([default_region] * len(raw), index=raw.index)

    rows = [validate_single_phone(r, default_region=(rr or default_region)) for r, rr in zip(raw.tolist(), reg.tolist())]
    df = pd.DataFrame(rows)
    df["masked"] = df["e164"].apply(mask_e164)
    return df
