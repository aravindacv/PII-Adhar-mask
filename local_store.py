# storage/local_store.py
# Local persistence for processed runs (no external DB).

from __future__ import annotations
import os
import json
import re
import time
import typing as t
import pandas as pd

try:
    import pyarrow  # noqa: F401
    _HAS_PARQUET = True
except Exception:
    _HAS_PARQUET = False

RUNS_DIR = "runs"

def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _slug(s: str) -> str:
    s = (s or "run").strip().replace(" ", "_")
    return re.sub(r"[^a-zA-Z0-9_\-\.]", "", s)

def new_run_path(label: str) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    root = os.path.join(RUNS_DIR, f"{ts}_{_slug(label)}")
    _ensure_dir(root)
    return root

def save_run(root: str,
             full_df: pd.DataFrame,
             valid_df: pd.DataFrame,
             invalid_a_df: pd.DataFrame,
             invalid_m_df: pd.DataFrame,
             meta: dict,
             report_md: str) -> dict:
    _ensure_dir(root)
    with open(os.path.join(root, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    with open(os.path.join(root, "report.md"), "w", encoding="utf-8") as f:
        f.write(report_md)

    # Save masked-only CSV/Parquet for safety
    def _masked_only(df: pd.DataFrame) -> pd.DataFrame:
        keep = [c for c in df.columns if ("masked" in c) or ("reason" in c) or ("category" in c) or (c in [
            "country", "region", "overall_valid", "aadhaar_valid", "mobile_valid"
        ])]
        # Always include these identifiers in masked form if present
        for col in ("aadhaar_masked", "mobile_masked"):
            if col not in keep and col in df.columns:
                keep.append(col)
        # Also include non-PII meta columns if present
        for col in ("source_row_index",):
            if col in df.columns and col not in keep:
                keep.append(col)
        # Add high-level columns for debug/usefulness
        for col in ("aadhaar_reason", "mobile_reason", "aadhaar_category", "mobile_category"):
            if col in df.columns and col not in keep:
                keep.append(col)
        return df[keep].copy()

    masked_full = _masked_only(full_df)
    masked_valid = _masked_only(valid_df)
    masked_invalid_a = _masked_only(invalid_a_df)
    masked_invalid_m = _masked_only(invalid_m_df)

    if _HAS_PARQUET:
        masked_full.to_parquet(os.path.join(root, "processed.parquet"), index=False)
        masked_valid.to_parquet(os.path.join(root, "valid.parquet"), index=False)
        masked_invalid_a.to_parquet(os.path.join(root, "invalid_aadhaar.parquet"), index=False)
        masked_invalid_m.to_parquet(os.path.join(root, "invalid_mobile.parquet"), index=False)

    masked_full.to_csv(os.path.join(root, "processed.csv"), index=False)
    masked_valid.to_csv(os.path.join(root, "valid.csv"), index=False)
    masked_invalid_a.to_csv(os.path.join(root, "invalid_aadhaar.csv"), index=False)
    masked_invalid_m.to_csv(os.path.join(root, "invalid_mobile.csv"), index=False)

    return {"root": root, "saved": True}

def list_runs() -> list[dict]:
    if not os.path.isdir(RUNS_DIR):
        return []
    items = []
    for name in os.listdir(RUNS_DIR):
        root = os.path.join(RUNS_DIR, name)
        if not os.path.isdir(root):
            continue
        meta = {}
        mp = os.path.join(root, "meta.json")
        if os.path.isfile(mp):
            try:
                meta = json.load(open(mp, "r", encoding="utf-8"))
            except Exception:
                meta = {}
        items.append({"name": name, "root": root, "meta": meta})
    return sorted(items, key=lambda x: x["name"], reverse=True)

def load_run(root: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict, str]:
    meta = {}
    mp = os.path.join(root, "meta.json")
    if os.path.isfile(mp):
        try:
            meta = json.load(open(mp, "r", encoding="utf-8"))
        except Exception:
            meta = {}
    report_md = ""
    rp = os.path.join(root, "report.md")
    if os.path.isfile(rp):
        report_md = open(rp, "r", encoding="utf-8").read()

    def _read_df(base: str) -> pd.DataFrame:
        pq = os.path.join(root, f"{base}.parquet")
        if _HAS_PARQUET and os.path.isfile(pq):
            return pd.read_parquet(pq)
        csvp = os.path.join(root, f"{base}.csv")
        if os.path.isfile(csvp):
            return pd.read_csv(csvp)
        return pd.DataFrame()

    full = _read_df("processed")
    valid = _read_df("valid")
    inv_a = _read_df("invalid_aadhaar")
    inv_m = _read_df("invalid_mobile")
    return full, valid, inv_a, inv_m, meta, report_md
