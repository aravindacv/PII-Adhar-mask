# reports/compliance.py
# Build a Markdown compliance report for a run.

from __future__ import annotations
from datetime import datetime

def build_report(meta: dict, stats: dict) -> str:
    """
    Return a Markdown string with data quality summary and compliance notes.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""# PII Data Quality & Masking Report

**Generated:** {ts}

## Run Metadata
- Label: **{meta.get('label','')}**
- Aadhaar column: `{meta.get('aadhaar_column','')}`
- Mobile column: `{meta.get('mobile_column','')}`
- Country column: `{meta.get('country_column','') or '(none, used default region)'}`
- Default region: `{meta.get('default_region','IN')}`
- Dedup mode: `{meta.get('dedup_mode','None')}`
- Mask by default: `{meta.get('mask_default', True)}`

## Summary
- Rows in file: **{stats.get('total_rows',0):,}**
- Processed after cleaning: **{stats.get('processed',0):,}**
- Distinct after dedup: **{stats.get('distinct_after',0):,}**
- Aadhaar valid: **{stats.get('aadhaar_valid',0):,}**
- Aadhaar invalid: **{stats.get('aadhaar_invalid',0):,}**
- Mobile valid: **{stats.get('mobile_valid',0):,}**
- Mobile invalid: **{stats.get('mobile_invalid',0):,}**
- Overall valid records: **{stats.get('overall_valid',0):,}**

## Rules & Algorithms
- **Aadhaar**: 12 digits with Verhoeff checksum. Reasons: `MISSING`, `NON_NUMERIC`, `LENGTH_NEQ_12`, `CHECKSUM_FAIL`.
- **Mobile**: Parsed with Google libphonenumber. Reasons: `MISSING`, `PARSE_FAIL`, `NOT_VALID`, `NOT_MOBILE_TYPE`.
- **Masking**:
  - Aadhaar: `XXXX-XXXX-####` (last 4 visible)
  - Mobile (E.164): `+CC-XXX-XXX-####` (last 4 visible)
- **Quality signals**: adjacent repetition (≥3), sequential runs (≥3), improbable patterns (e.g., all same digit, long sequences).

## Handling & Compliance Notes
> ⚠️ **Sensitive PII** — Exercise strict controls. Store masked outputs. Unmasked exports should be limited, access-controlled, and logged.

- This tool masks by default in the UI and saved artifacts.
- Unmasked downloads are available only via explicit user action during a session.
- Consider enabling encryption/tokenization at rest if you must persist unmasked data.

## How to Extend
- Add custom business rules (e.g., country-specific mobile constraints).
- Add encryption/tokenization: place keys in environment variables, use AES-GCM, rotate keys regularly.
"""
