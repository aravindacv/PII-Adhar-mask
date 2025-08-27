# app.py
"""
Requirements & Run
------------------
1) Create/activate venv (optional but recommended)
   - Windows PowerShell:
       python -m venv venv
       .\venv\Scripts\activate
   - macOS/Linux:
       python3 -m venv venv
       source venv/bin/activate

2) Install packages
   pip install --upgrade pip
   pip install streamlit pandas phonenumbers openpyxl pyarrow

3) Run
   streamlit run app.py
   (If PATH issues: python -m streamlit run app.py)

Notes:
- Parquet via pyarrow (optional); Excel via openpyxl (for .xlsx).
- Runs saved under ./runs with masked CSV/Parquet + meta.json + report.md.
- UI defaults to MASKED display; unmask requires explicit user action.
"""

from __future__ import annotations
import io
import os
import pandas as pd
import streamlit as st

# from validators.base import clean_series_text
# from validators.ind_aadhaar import (
#     validate_series as validate_aadhaar_series,
#     mask_aadhaar,
#     verhoeff_check_digit,  # exposed for transparency/help
# )
# from validators.phone import (
#     validate_series as validate_phone_series,
# )
# from storage.local_store import new_run_path, save_run, list_runs, load_run
# from reports.compliance import build_report

# replace package-style imports with flat imports
from base import clean_series_text
from ind_aadhaar import (
    validate_series as validate_aadhaar_series,
    mask_aadhaar,
    verhoeff_check_digit,
)
from phone import validate_series as validate_phone_series
from local_store import new_run_path, save_run, list_runs, load_run
from compliance import build_report

# ---------------- Page ----------------
st.set_page_config(page_title="PII Data Quality & Masking", page_icon="🛡️", layout="wide")
st.title("PII Data Quality & Masking — Aadhaar & Mobile")
st.caption("Clean, validate, and mask Aadhaar (Verhoeff) & mobile numbers with compliance-friendly reports. No database required.")

# ---------------- Sidebar: Upload & Options ----------------
st.sidebar.header("Upload & Options")
uploaded_file = st.sidebar.file_uploader("Upload CSV or Excel (.xlsx)", type=["csv", "xlsx"])

encoding = st.sidebar.selectbox("CSV Encoding (CSV only)", ["utf-8", "utf-8-sig", "latin-1", "cp1252"], index=0)
default_region = st.sidebar.text_input("Default region if no country column", value="IN")

dedup_mode = st.sidebar.selectbox("Deduplicate by", ["None", "Aadhaar", "Mobile", "Aadhaar+Mobile"], index=0)
mask_default = st.sidebar.checkbox("Mask values in UI (recommended)", value=True)
source_label = st.sidebar.text_input("Run label", value="pii_quality")

st.sidebar.markdown("---")
st.sidebar.subheader("Saved Runs")
_runs = list_runs()
if _runs:
    _name_to_root = {r["name"]: r["root"] for r in _runs}
    _chosen = st.sidebar.selectbox("Reload a previous run", ["-- select --"] + list(_name_to_root.keys()), index=0)
    if _chosen and _chosen != "-- select --":
        full_df, valid_df, inv_a_df, inv_m_df, meta, report_md = load_run(_name_to_root[_chosen])
        st.success(f"Loaded run: {_chosen}")
        with st.expander("Run metadata"):
            st.json(meta, expanded=False)
        with st.expander("Compliance report (preview)"):
            st.code(report_md or "(no report found)", language="markdown")
        st.subheader("Loaded: Processed (masked)")
        st.dataframe(full_df, height=400, width="stretch")
        st.stop()

st.markdown("---")

# ---------------- Ingest ----------------
df = None
read_err = None
if uploaded_file is not None:
    try:
        if uploaded_file.name.lower().endswith(".csv"):
            try:
                df = pd.read_csv(uploaded_file, encoding=encoding)
            except UnicodeDecodeError:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, encoding="latin-1")
        else:
            df = pd.read_excel(uploaded_file, engine="openpyxl")
    except Exception as e:
        read_err = str(e)

if read_err:
    st.error(f"Failed to read file: {read_err}")

if df is None:
    st.info("Upload a CSV or Excel file to begin.")
    st.stop()

st.success(f"Loaded file with **{len(df):,}** rows and **{len(df.columns)}** columns.")
with st.expander("Preview (first 20 rows)"):
    st.dataframe(df.head(20), width="stretch")

# ---------------- Auto-detect likely columns & confirm via dropdowns ----------------
def _guess_aadhaar_col(columns) -> str | None:
    # Name hints
    name_hits = [c for c in columns if str(c).strip().lower() in {"aadhaar", "aadhar", "uidai"}]
    if name_hits:
        return name_hits[0]
    # Heuristic: columns where >50% rows have >=12 digits
    for c in columns:
        try:
            s = df[c].astype(str).str.replace(r"\D", "", regex=True)
            if (s.str.len() >= 12).mean() > 0.5:
                return c
        except Exception:
            continue
    return None

def _guess_mobile_col(columns) -> str | None:
    # Name hints
    name_hits = [c for c in columns if any(k in str(c).strip().lower() for k in ["mobile", "phone", "contact", "msisdn"])]
    if name_hits:
        return name_hits[0]
    # Heuristic: columns where many values are 10..15 digits
    for c in columns:
        try:
            s = df[c].astype(str).str.replace(r"\D", "", regex=True)
            if ((s.str.len() >= 10) & (s.str.len() <= 15)).mean() > 0.5:
                return c
        except Exception:
            continue
    return None

guessed_aadhaar = _guess_aadhaar_col(df.columns)
guessed_mobile  = _guess_mobile_col(df.columns)
guessed_country = None  # keep manual; users often pick this intentionally

st.subheader("Select columns")
aadhaar_col = st.selectbox(
    "Aadhaar column (optional)",
    options=["(none)"] + list(df.columns),
    index=(1 + list(df.columns).index(guessed_aadhaar)) if (guessed_aadhaar in df.columns) else 0,
)
mobile_col = st.selectbox(
    "Mobile column (optional)",
    options=["(none)"] + list(df.columns),
    index=(1 + list(df.columns).index(guessed_mobile)) if (guessed_mobile in df.columns) else 0,
)
country_col = st.selectbox(
    "Country/Region column (ISO-2, optional)",
    options=["(none)"] + list(df.columns),
    index=0,  # conservative default
)

aadhaar_col = None if aadhaar_col == "(none)" else aadhaar_col
mobile_col  = None if mobile_col  == "(none)"  else mobile_col
country_col = None if country_col == "(none)"  else country_col

if (aadhaar_col is None) and (mobile_col is None):
    st.error("Please select at least one of: Aadhaar column or Mobile column.")
    st.stop()

# ---------------- Build working frame ----------------
work = pd.DataFrame(index=df.index)
work["aadhaar_raw"] = df[aadhaar_col] if aadhaar_col else ""
work["mobile_raw"]  = df[mobile_col]  if mobile_col  else ""
work["country"]     = (
    df[country_col].astype(str).str.upper().fillna("") if country_col
    else default_region.strip().upper()
)

# Drop rows where both fields are empty after basic text clean
tmp_a = clean_series_text(work["aadhaar_raw"])
tmp_m = clean_series_text(work["mobile_raw"])
keep_mask = (tmp_a != "") | (tmp_m != "")
before = len(work)
work = work.loc[keep_mask].copy()
dropped_all_empty = before - len(work)

if work.empty:
    st.warning("All rows are empty for both Aadhaar and Mobile after cleaning. Nothing to process.")
    st.stop()

# ---------------- Validate Aadhaar ----------------
aadhaar_df = validate_aadhaar_series(work["aadhaar_raw"])
idx = work.index
work.loc[idx, "aadhaar_clean"]    = aadhaar_df["aadhaar"].to_numpy()
work.loc[idx, "aadhaar_valid"]    = aadhaar_df["valid"].to_numpy()
work.loc[idx, "aadhaar_reason"]   = aadhaar_df["reason"].to_numpy()
work.loc[idx, "aadhaar_category"] = aadhaar_df["category"].to_numpy()
work.loc[idx, "aadhaar_masked"]   = work["aadhaar_clean"].apply(mask_aadhaar)

# ---------------- Validate Mobile ----------------
region_series = work["country"]
phone_df = validate_phone_series(
    work["mobile_raw"],
    region_series=region_series,
    default_region=default_region.strip().upper()
)
work.loc[idx, "mobile_e164"]   = phone_df["e164"].to_numpy()
work.loc[idx, "mobile_valid"]  = phone_df["valid"].to_numpy()
work.loc[idx, "mobile_reason"] = phone_df["reason"].to_numpy()
work.loc[idx, "mobile_region"] = phone_df["region"].to_numpy()
work.loc[idx, "mobile_type"]   = phone_df["type"].to_numpy()
work.loc[idx, "mobile_masked"] = phone_df["masked"].to_numpy()

# ---------------- Deduplication ----------------
dedup_applied = 0
if dedup_mode == "Aadhaar":
    before_d = len(work); work = work.drop_duplicates(subset=["aadhaar_clean"]).copy(); dedup_applied = before_d - len(work)
elif dedup_mode == "Mobile":
    before_d = len(work); work = work.drop_duplicates(subset=["mobile_e164"]).copy();  dedup_applied = before_d - len(work)
elif dedup_mode == "Aadhaar+Mobile":
    before_d = len(work); work = work.drop_duplicates(subset=["aadhaar_clean", "mobile_e164"]).copy(); dedup_applied = before_d - len(work)

# ---------------- Overall validity ----------------
aadhaar_present = work["aadhaar_clean"].astype(str) != ""
mobile_present  = work["mobile_e164"].astype(str)  != ""
both_present    = aadhaar_present & mobile_present
only_a          = aadhaar_present & (~mobile_present)
only_m          = mobile_present & (~aadhaar_present)

overall_valid = (
    (both_present & (work["aadhaar_valid"] & work["mobile_valid"])) |
    (only_a & work["aadhaar_valid"]) |
    (only_m & work["mobile_valid"])
)
work["overall_valid"] = overall_valid

# ---------------- Summary ----------------
total_rows = len(df)
processed  = len(work)
distinct_after = processed
aadhaar_valid_count  = int(work["aadhaar_valid"].sum())
aadhaar_invalid_count = int(((~work["aadhaar_valid"]) & (work["aadhaar_clean"] != "")).sum())
mobile_valid_count   = int(work["mobile_valid"].sum())
mobile_invalid_count = int(((~work["mobile_valid"]) & (work["mobile_e164"] != "")).sum())
overall_valid_count  = int(work["overall_valid"].sum())

st.subheader("📊 Summary")
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Rows in file", f"{total_rows:,}")
c2.metric("Processed after cleaning", f"{processed:,}")
c3.metric("Distinct after dedup", f"{distinct_after:,}")
c4.metric("Aadhaar valid", f"{aadhaar_valid_count:,}")
c5.metric("Mobile valid", f"{mobile_valid_count:,}")
c6.metric("Overall valid records", f"{overall_valid_count:,}")
st.caption(f"Dropped rows empty for both fields: {dropped_all_empty:,} | Duplicates dropped: {dedup_applied:,}")

# ---------------- Insights ----------------
st.subheader("Insights")
left, right = st.columns(2)
with left:
    st.write("Top invalid reasons — Aadhaar")
    inv_a = work[(work["aadhaar_clean"] != "") & (~work["aadhaar_valid"])]
    if not inv_a.empty:
        st.bar_chart(inv_a["aadhaar_reason"].replace("", "OTHER").value_counts().head(10))
    else:
        st.info("No invalid Aadhaar.")
with right:
    st.write("Top regions — Mobile")
    if (work["mobile_region"].astype(str) != "").any():
        st.bar_chart(work["mobile_region"].replace("", "UNKNOWN").value_counts().head(10))
    else:
        st.info("No parsed mobile regions.")

# ---------------- Results ----------------
st.subheader("Results")
show_unmasked = st.checkbox("Show UNMASKED values in tables (sensitive!)", value=not mask_default)

def _pick_cols(masked: bool) -> list[str]:
    cols = ["country", "mobile_region", "overall_valid",
            "aadhaar_category", "aadhaar_reason",
            "mobile_reason", "mobile_type"]
    if masked:
        cols = ["aadhaar_masked", "mobile_masked"] + cols
    else:
        cols = ["aadhaar_clean", "mobile_e164"] + cols
    return [c for c in cols if c in work.columns]

tab_valid, tab_inv_a, tab_inv_m, tab_all = st.tabs(["✅ Valid records", "❌ Invalid Aadhaar", "❌ Invalid Mobile", "📄 Full (processed)"])

with tab_valid:
    v = work[work["overall_valid"]].copy()
    st.dataframe(v[_pick_cols(masked=mask_default and not show_unmasked)], height=360, width="stretch")
    if not v.empty:
        b = io.StringIO(); v.to_csv(b, index=False)
        st.download_button("Download VALID (masked) CSV", b.getvalue().encode("utf-8"), "valid_masked.csv", "text/csv")

with tab_inv_a:
    ia = work[(work["aadhaar_clean"] != "") & (~work["aadhaar_valid"])].copy()
    st.dataframe(ia[_pick_cols(masked=mask_default and not show_unmasked)], height=360, width="stretch")
    if not ia.empty:
        b2 = io.StringIO(); ia.to_csv(b2, index=False)
        st.download_button("Download Invalid Aadhaar (masked) CSV", b2.getvalue().encode("utf-8"), "invalid_aadhaar_masked.csv", "text/csv")

with tab_inv_m:
    im = work[(work["mobile_e164"] != "") & (~work["mobile_valid"])].copy()
    st.dataframe(im[_pick_cols(masked=mask_default and not show_unmasked)], height=360, width="stretch")
    if not im.empty:
        b3 = io.StringIO(); im.to_csv(b3, index=False)
        st.download_button("Download Invalid Mobile (masked) CSV", b3.getvalue().encode("utf-8"), "invalid_mobile_masked.csv", "text/csv")

with tab_all:
    st.dataframe(work[_pick_cols(masked=mask_default and not show_unmasked)], height=420, width="stretch")
    b4 = io.StringIO(); work.to_csv(b4, index=False)
    st.download_button("Download FULL (masked) CSV", b4.getvalue().encode("utf-8"), "processed_masked.csv", "text/csv")

# ---------------- Unmasked exports (explicit action) ----------------
st.markdown("—")
st.markdown("**Unmasked exports** (handle with care):")
colU1, colU2, colU3 = st.columns(3)
with colU1:
    if st.button("Prepare VALID (unmasked) CSV"):
        bu = io.StringIO(); work[work["overall_valid"]].to_csv(bu, index=False)
        st.download_button("Save VALID (unmasked).csv", bu.getvalue().encode("utf-8"), "valid_unmasked.csv", "text/csv")
with colU2:
    if st.button("Prepare Invalid Aadhaar (unmasked) CSV"):
        bu2 = io.StringIO(); work[(work["aadhaar_clean"] != "") & (~work["aadhaar_valid"])].to_csv(bu2, index=False)
        st.download_button("Save invalid_aadhaar_unmasked.csv", bu2.getvalue().encode("utf-8"), "invalid_aadhaar_unmasked.csv", "text/csv")
with colU3:
    if st.button("Prepare Invalid Mobile (unmasked) CSV"):
        bu3 = io.StringIO(); work[(work["mobile_e164"] != "") & (~work["mobile_valid"])].to_csv(bu3, index=False)
        st.download_button("Save invalid_mobile_unmasked.csv", bu3.getvalue().encode("utf-8"), "invalid_mobile_unmasked.csv", "text/csv")

# ---------------- Save run (masked artifacts + report) ----------------
st.subheader("💾 Save Run (masked artifacts)")
if st.button("Save to ./runs"):
    meta = {
        "label": source_label,
        "aadhaar_column": aadhaar_col or "",
        "mobile_column": mobile_col or "",
        "country_column": country_col or "",
        "default_region": default_region.strip().upper(),
        "dedup_mode": dedup_mode,
        "mask_default": bool(mask_default),
    }
    stats = {
        "total_rows": total_rows,
        "processed": processed,
        "distinct_after": distinct_after,
        "aadhaar_valid": aadhaar_valid_count,
        "aadhaar_invalid": aadhaar_invalid_count,
        "mobile_valid": mobile_valid_count,
        "mobile_invalid": mobile_invalid_count,
        "overall_valid": overall_valid_count,
    }
    report_md = build_report(meta, stats)
    root = new_run_path(source_label)
    valid_records = work[work["overall_valid"]].copy()
    invalid_a = work[(work["aadhaar_clean"] != "") & (~work["aadhaar_valid"])].copy()
    invalid_m = work[(work["mobile_e164"] != "") & (~work["mobile_valid"])].copy()
    save_run(root, work, valid_records, invalid_a, invalid_m, meta, report_md)
    st.success(f"Saved run at: {root}")
