"""Grain Scanner — drop-to-grade workflow.

Drop an image → auto-process + auto-grade → certificate ready.
No wizard steps. Profile and vendor are set in the sidebar before scanning.
"""
from __future__ import annotations

import io
import os
from datetime import datetime

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from PIL import Image

# ── Config ────────────────────────────────────────────────────────────────────
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
API = f"{BACKEND_URL}/api/v1"
TIMEOUT = httpx.Timeout(120.0)

C_BG      = "#F9F7F4"
C_SIDEBAR = "#EFECE5"
C_CARD    = "#FFFFFF"
C_ACCENT  = "#CC7A3A"
C_ACCENTL = "#FDF1E6"
C_BORDER  = "#DDD8CF"
C_TEXT    = "#1A1A18"
C_MUTED   = "#6B6460"
C_SUCCESS = "#1F7A45"
C_WARN    = "#C47820"
C_ERROR   = "#C02020"

GRADE_COLORS = {"A": C_SUCCESS, "B": "#2563EB", "C": C_WARN, "Reject": C_ERROR}
PIE_COLORS   = [C_SUCCESS, "#3B82F6", C_WARN, "#F97316", C_ERROR]
PLOT_BASE    = dict(
    paper_bgcolor=C_CARD, plot_bgcolor=C_BG,
    font=dict(color=C_TEXT, family="Inter, system-ui, sans-serif", size=12),
    margin=dict(l=12, r=12, t=28, b=12),
    legend=dict(orientation="h", y=1.10, font_size=11),
)

st.set_page_config(page_title="Grain Scanner", page_icon="🌾",
                   layout="wide", initial_sidebar_state="expanded")

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html,body,[class*="css"]{{font-family:'Inter',system-ui,sans-serif!important}}
.stApp{{background:{C_BG};color:{C_TEXT}}}
p,span,div,li,label{{color:{C_TEXT}}}
.stMarkdown p,.stMarkdown span{{color:{C_TEXT}!important}}

/* Form labels */
.stSelectbox>label,.stTextInput>label,.stNumberInput>label,
.stTextArea>label,.stSlider>label,.stRadio>label,
.stCheckbox>label,.stToggle>label,.stFileUploader>label{{
  color:{C_TEXT}!important;font-size:.84rem;font-weight:500}}
input,textarea{{color:{C_TEXT}!important;background:{C_CARD}!important}}
input:focus,textarea:focus{{border-color:{C_ACCENT}!important;
  box-shadow:0 0 0 3px {C_ACCENTL}!important;outline:none!important}}

/* Selectbox */
[data-baseweb="select"]>div{{background:{C_CARD}!important;
  border-color:{C_BORDER}!important;border-radius:8px!important;color:{C_TEXT}!important}}
[data-baseweb="select"] span,[data-baseweb="select"] div{{color:{C_TEXT}!important}}
[data-baseweb="popover"]{{background-color:{C_CARD}!important;
  border:1px solid {C_BORDER}!important;border-radius:10px!important;
  box-shadow:0 4px 16px rgba(0,0,0,.12)!important}}
[data-baseweb="popover"] *{{background-color:{C_CARD}!important;color:{C_TEXT}!important}}
[data-baseweb="menu"],ul[data-baseweb="menu"]{{background-color:{C_CARD}!important;
  border-radius:10px!important;padding:4px!important}}
[data-baseweb="option"]{{background-color:{C_CARD}!important;color:{C_TEXT}!important;border-radius:6px!important}}
[data-baseweb="option"]:hover,li[role="option"]:hover{{background-color:{C_ACCENTL}!important}}
[role="listbox"]{{background-color:{C_CARD}!important}}
[role="option"],li[role="option"]{{background-color:{C_CARD}!important;color:{C_TEXT}!important}}
[aria-selected="true"][data-baseweb="option"]{{background-color:{C_ACCENTL}!important;
  color:{C_ACCENT}!important;font-weight:600!important}}
.stRadio div[role="radiogroup"] p,.stRadio label{{color:{C_TEXT}!important}}
.stCaption{{color:{C_MUTED}!important;font-size:.78rem!important}}

/* Sidebar */
[data-testid="stSidebar"]{{background-color:{C_SIDEBAR}!important;border-right:1px solid {C_BORDER}}}
[data-testid="stSidebar"] *{{color:{C_TEXT}!important}}
[data-testid="stSidebar"] hr{{border-color:{C_BORDER}!important}}

/* Sidebar nav buttons — ghost style */
[data-testid="stSidebar"] .nav-btn .stButton>button{{
  background:transparent!important;color:{C_TEXT}!important;
  border:none!important;border-radius:9px!important;box-shadow:none!important;
  font-weight:500!important;padding:8px 12px!important}}
[data-testid="stSidebar"] .nav-btn .stButton>button:hover{{background:rgba(204,122,58,.10)!important}}
[data-testid="stSidebar"] .nav-btn-active .stButton>button{{
  background:{C_ACCENTL}!important;color:{C_ACCENT}!important;
  border:none!important;border-radius:9px!important;box-shadow:none!important;font-weight:700!important}}

/* Primary buttons */
.stButton>button{{background:{C_ACCENT}!important;color:{C_CARD}!important;
  border:none!important;border-radius:8px!important;font-weight:600!important;
  font-size:.875rem!important;box-shadow:0 1px 3px rgba(0,0,0,.14)!important}}
.stButton>button:hover{{background:#B5622A!important;box-shadow:0 2px 8px rgba(0,0,0,.20)!important}}
.stButton>button:disabled{{background:{C_BORDER}!important;color:{C_MUTED}!important;box-shadow:none!important}}

/* Download buttons */
.stDownloadButton>button{{background:{C_CARD}!important;color:{C_ACCENT}!important;
  border:1.5px solid {C_ACCENT}!important;border-radius:8px!important;font-weight:600!important}}
.stDownloadButton>button:hover{{background:{C_ACCENTL}!important}}

/* Metrics */
[data-testid="metric-container"]{{background:{C_CARD}!important;border:1px solid {C_BORDER}!important;
  border-radius:10px!important;padding:14px 16px!important;box-shadow:0 1px 3px rgba(0,0,0,.06)!important}}
[data-testid="metric-container"] [data-testid="stMetricLabel"] p{{color:{C_MUTED}!important;
  font-size:.7rem!important;font-weight:600!important;text-transform:uppercase;letter-spacing:.05em}}
[data-testid="metric-container"] [data-testid="stMetricValue"]{{color:{C_TEXT}!important;
  font-weight:700!important;font-size:1.4rem!important}}

/* Expander (details only) */
[data-testid="stExpander"]{{background:{C_CARD}!important;border:1px solid {C_BORDER}!important;
  border-radius:12px!important;box-shadow:0 1px 4px rgba(0,0,0,.05)!important;overflow:hidden}}
[data-testid="stExpander"] summary p{{color:{C_TEXT}!important;font-weight:600!important;font-size:.95rem!important}}
.streamlit-expanderContent{{background:{C_CARD}!important;padding:0 20px 20px!important}}

h1{{font-size:1.3rem!important;font-weight:700!important;color:{C_TEXT}!important;
  letter-spacing:-.02em!important;margin-bottom:0!important}}
h2{{font-size:1rem!important;font-weight:600!important;color:{C_TEXT}!important;
  border-bottom:1px solid {C_BORDER};padding-bottom:6px}}
hr{{border-color:{C_BORDER}!important;margin:16px 0!important}}
.stDataFrame{{border:1px solid {C_BORDER}!important;border-radius:10px!important;overflow:hidden}}
[data-testid="stAlert"]{{border-radius:10px!important}}
[data-testid="stAlert"] p{{color:{C_TEXT}!important}}
.stProgress>div>div{{background-color:{C_ACCENT}!important}}

/* Drop zone */
[data-testid="stFileUploader"] section{{background:{C_CARD}!important;
  border:2px dashed {C_BORDER}!important;border-radius:16px!important;
  padding:40px!important;transition:border-color .15s}}
[data-testid="stFileUploader"] section:hover{{border-color:{C_ACCENT}!important}}
[data-testid="stFileUploaderDropzoneInstructions"] p{{color:{C_MUTED}!important;font-size:1rem!important}}
[data-testid="stFileUploader"] span,[data-testid="stFileUploader"] small{{color:{C_MUTED}!important}}
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
_D: dict = {
    "view": "main",
    "scan_id": None, "result": None, "measurements_df": None, "annotated_image": None,
    "quality_report": None, "coa_bytes": None, "coa_filename": "certificate.pdf",
    "scan_devices": [],
    "vendors": [], "selected_vendor_id": None, "vendor_history": None,
    "lot_history": None,
    "last_profile": "Rice Standard", "last_lot_id": "",
    "last_file_id": None,
    "batch_results": None,
    "cal_profiles": None,
}
for _k, _v in _D.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── API helpers ───────────────────────────────────────────────────────────────
def _get(path: str, **kw):
    try:
        r = httpx.get(f"{API}{path}", timeout=TIMEOUT, **kw)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        st.error(f"API error: {e}")
        return None

def _post(path: str, **kw):
    try:
        r = httpx.post(f"{API}{path}", timeout=TIMEOUT, **kw)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            pass
        # Show the human-readable detail rather than the raw HTTP status line
        msg = detail or str(e)
        st.error(msg)
        return None
    except httpx.HTTPError as e:
        st.error(f"Connection error: {e}")
        return None

def _backend_ok() -> bool:
    try: return httpx.get(f"{API}/health", timeout=httpx.Timeout(3.0)).status_code == 200
    except Exception: return False

@st.cache_data(ttl=60)
def _fetch_profiles() -> list[str]:
    r = _get("/quality/profiles")
    return [p["name"] for p in (r or {}).get("profiles", [])] or ["Rice Standard"]

def _load_vendors():
    data = _get("/vendors/")
    if data:
        st.session_state.vendors = data
    return st.session_state.vendors

def _delete(path: str, **kw):
    try:
        r = httpx.delete(f"{API}{path}", timeout=TIMEOUT, **kw)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        st.error(f"API error: {e}")
        return None

def _put(path: str, **kw):
    try:
        r = httpx.put(f"{API}{path}", timeout=TIMEOUT, **kw)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        st.error(f"API error: {e}")
        return None

def _reset():
    for k in ("scan_id","result","measurements_df","annotated_image",
              "quality_report","coa_bytes","coa_filename","last_file_id"):
        st.session_state[k] = _D.get(k)
    st.session_state.coa_filename = "certificate.pdf"


def _batch_process_one(f, lot_id: str, profile: str, dpi: int, vendor_id) -> dict:
    """Call upload → process → grade for one file. Returns result dict."""
    try:
        data: dict = {"dpi": str(dpi)}
        if vendor_id: data["vendor_id"] = str(vendor_id)
        if lot_id:    data["lot_id"] = lot_id

        r1 = httpx.post(f"{API}/scans/upload",
                        files={"file": (f.name, f.getvalue(), f.type)},
                        data=data, timeout=TIMEOUT)
        if r1.status_code != 200:
            return {"filename": f.name, "lot_id": lot_id, "status": "error",
                    "error": r1.text[:200]}
        sid = r1.json()["scan_id"]

        r2 = httpx.post(f"{API}/scans/{sid}/process", timeout=TIMEOUT)
        if r2.status_code != 200:
            return {"filename": f.name, "lot_id": lot_id, "scan_id": sid,
                    "status": "error", "error": r2.text[:200]}
        res = r2.json()

        qp: dict = {"profile_name": profile}
        if lot_id: qp["lot_id"] = lot_id
        r3 = httpx.get(f"{API}/quality/assess/{sid}", params=qp, timeout=TIMEOUT)
        qr = r3.json() if r3.status_code == 200 else {}

        return {
            "filename": f.name,
            "lot_id": lot_id or "—",
            "scan_id": sid,
            "status": "done",
            "grain_count": res.get("grain_count", 0),
            "grade": qr.get("grade", "?"),
            "score": qr.get("total_score", 0),
            "head_rice_pct": round(qr.get("head_rice_pct", 0), 1),
            "broken_pct": round(qr.get("total_broken_pct", 0), 1),
            "decision": qr.get("decision", ""),
        }
    except Exception as e:
        return {"filename": f.name, "lot_id": lot_id or "—",
                "status": "error", "error": str(e)}


def _run_full_pipeline(file_bytes: bytes, filename: str, filetype: str,
                       profile: str, lot_id: str, dpi: int, params: dict):
    """Upload → process → grade → CoA in one call. Returns True on success."""
    # 1. Upload
    upload_data: dict = {"dpi": str(dpi)}
    if st.session_state.selected_vendor_id:
        upload_data["vendor_id"] = str(st.session_state.selected_vendor_id)
    if lot_id:
        upload_data["lot_id"] = lot_id

    up = _post("/scans/upload",
               files={"file": (filename, file_bytes, filetype)},
               data=upload_data)
    if not up:
        return False

    sid = up["scan_id"]
    st.session_state.scan_id = sid

    # 2. Process — send params body only when explicit; empty dict means auto-detect
    if params:
        result = _post(f"/scans/{sid}/process", json=params)
    else:
        result = _post(f"/scans/{sid}/process")
    if not result:
        return False
    st.session_state.result = result

    # 3. Load annotated image + measurements
    try:
        r = httpx.get(f"{API}/scans/{sid}/annotated-image", timeout=TIMEOUT)
        if r.status_code == 200:
            st.session_state.annotated_image = Image.open(io.BytesIO(r.content))
    except Exception:
        pass
    ms = _get(f"/scans/{sid}/measurements")
    if ms:
        st.session_state.measurements_df = pd.DataFrame([{
            "ID": m["grain_index"],
            "Length (mm)": round(m["major_axis_mm"], 3),
            "Width (mm)": round(m["minor_axis_mm"], 3),
            "Area (mm²)": round(m["area_mm2"], 4),
            "Perimeter (mm)": round(m["perimeter_mm"], 3),
            "Aspect Ratio": round(m["aspect_ratio"], 3),
            "Angle (°)": round(m["orientation_deg"], 1),
            "Anomaly": ", ".join(m.get("anomaly_flags", [])),
            "Recovered": "↩ Recovered" if m.get("recovered_from_cluster") else "",
        } for m in ms])

    # 4. Grade
    qp: dict = {"profile_name": profile}
    if lot_id: qp["lot_id"] = lot_id
    qr = _get(f"/quality/assess/{sid}", params=qp)
    if qr:
        st.session_state.quality_report = qr
        # 5. CoA
        try:
            coa_r = httpx.get(f"{API}/quality/coa/{sid}", params=qp, timeout=TIMEOUT)
            if coa_r.status_code == 200:
                lot_sfx = f"_{lot_id}" if lot_id else ""
                st.session_state.coa_bytes    = coa_r.content
                st.session_state.coa_filename = f"coa_{sid}{lot_sfx}.pdf"
        except Exception:
            pass

    return True


# ══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    ok = _backend_ok()
    st.markdown(f"""
    <div style="padding:6px 0 12px">
      <span style="font-size:1.1rem;font-weight:700;color:{C_TEXT}">🌾 Grain Scanner</span>
    </div>
    <p style="font-size:.75rem;color:{C_MUTED};margin:-4px 0 12px">
      <span style="display:inline-block;width:7px;height:7px;border-radius:50%;
        background:{'#1F7A45' if ok else '#C02020'};margin-right:5px;vertical-align:middle"></span>
      {'Connected' if ok else 'Backend offline'}
    </p>""", unsafe_allow_html=True)

    st.divider()

    # ── Advanced scan settings (sidebar only) ────────────────────────────────
    view = st.session_state.view
    if view in ("main", "Batch"):
        with st.expander("⚙  Advanced", expanded=False):
            dpi = st.number_input("DPI", 72, 9600, 300, 50, key="adv_dpi")
            auto_mode = st.toggle("Auto-detect params", value=True, key="adv_auto")
            if not auto_mode:
                invert       = st.checkbox("Invert", value=True, key="adv_invert")
                blur_k       = st.slider("Blur kernel", 1, 31, 5, step=2, key="adv_blur")
                thresh_block = st.slider("Adaptive block", 3, 255, 51, step=2, key="adv_block")
                thresh_c     = st.slider("Threshold C", 0, 50, 10, key="adv_c")
                morph_k      = st.slider("Morph kernel", 1, 21, 3, step=2, key="adv_morph")
                morph_iter   = st.slider("Morph iterations", 1, 5, 2, key="adv_iter")
                ws_dist      = st.slider("Watershed dist", 5, 200, 20, key="adv_ws")
                min_area     = st.number_input("Min area px", 1, value=50, key="adv_mina")
                max_area     = st.number_input("Max area px", 100, value=5_000_000, key="adv_maxa")
            else:
                invert, blur_k, thresh_block, thresh_c = True, 5, 51, 10
                morph_k, morph_iter, ws_dist = 3, 2, 20
                min_area, max_area = 50, 5_000_000
        # Auto mode: send empty params so the server calls auto_detect_params().
        # Manual mode: send explicit params to override auto-detection.
        if auto_mode:
            params_payload = {}
        else:
            params_payload = {
                "dpi": dpi, "gaussian_blur_kernel": blur_k,
                "adaptive_block_size": thresh_block, "adaptive_c": thresh_c,
                "morph_kernel_size": morph_k, "morph_iterations": morph_iter,
                "watershed_min_distance": ws_dist,
                "min_grain_area_px": int(min_area), "max_grain_area_px": int(max_area),
                "invert_threshold": invert,
            }
        # input_mode is controlled by tabs in the main content area (set via session_state)
        input_mode = st.session_state.get("input_mode", "Upload File") if view == "main" else "Upload File"
    else:
        dpi = 300
        params_payload = {}
        input_mode = "Upload File"

    # Fallback values used by result view (read from session_state, set by context row)
    sel_profile = st.session_state.last_profile
    lot_id      = st.session_state.last_lot_id

    st.divider()

    # ── Secondary navigation ──────────────────────────────────────────────────
    for icon, label, target in [("🌾","Scan & Grade","main"),
                                  ("📦","Batch","Batch"),
                                  ("🏭","Vendors","Vendors"),
                                  ("📊","Analytics","Analytics"),
                                  ("⚖️","Calibration","Calibration")]:
        cls = "nav-btn-active" if view == target else "nav-btn"
        st.markdown(f'<div class="{cls}">', unsafe_allow_html=True)
        if st.button(f"{icon}  {label}", key=f"_nav_{target}", use_container_width=True):
            st.session_state.view = target
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN VIEW
# ══════════════════════════════════════════════════════════════════════════════
view     = st.session_state.view
has_scan = st.session_state.result is not None

if view == "main":

    # ── No result yet → context row + drop zone ──────────────────────────────
    if not has_scan:
        st.markdown(
            f'<h1 style="margin-bottom:4px">🌾 Grain Scanner</h1>'
            f'<p style="color:{C_MUTED};font-size:.9rem;margin-bottom:20px">'
            f'Drop a scan to measure grains and get an instant quality grade.</p>',
            unsafe_allow_html=True,
        )

        if not ok:
            st.error("**Backend offline.** Run `uvicorn main:app --reload` to start it.")
            st.stop()

        # ── Scan context row ──────────────────────────────────────────────────
        if not st.session_state.vendors:
            _load_vendors()
        vendors_list = st.session_state.vendors
        profile_names = _fetch_profiles()

        cx1, cx2, cx3, cx4, cx5 = st.columns([2, 2, 2, 2, 1])

        # Vendor
        if vendors_list:
            names_v = [v["name"] for v in vendors_list]
            sel_v = cx1.selectbox("Vendor", ["— None —"] + names_v, key="main_vendor")
            if sel_v != "— None —":
                vobj = next(v for v in vendors_list if v["name"] == sel_v)
                st.session_state.selected_vendor_id = vobj["id"]
            else:
                st.session_state.selected_vendor_id = None
        else:
            cx1.caption("No vendors — add one in Vendors tab")

        # Lot ID
        lot_id = cx2.text_input("Lot ID", value=st.session_state.last_lot_id,
                                placeholder="e.g. LOT-2024-001", key="main_lot")
        st.session_state.last_lot_id = lot_id

        # Quality Profile
        default_idx = (profile_names.index(st.session_state.last_profile)
                       if st.session_state.last_profile in profile_names else 0)
        sel_profile = cx3.selectbox("Quality Profile", profile_names,
                                    index=default_idx, key="main_profile")
        st.session_state.last_profile = sel_profile

        # Reference card
        _REF_OPTIONS = {"— No reference —": None, "Credit / Aadhaar card": "credit"}
        ref_label = cx4.selectbox("Reference card", list(_REF_OPTIONS.keys()),
                                  key="main_ref_card",
                                  help="Place the card next to the grains before scanning. "
                                       "The system detects it and calibrates scale automatically.")
        ref_card = _REF_OPTIONS[ref_label]

        # Refresh vendors
        if cx5.button("↻", key="main_v_ref", help="Refresh vendor list",
                      use_container_width=True):
            _load_vendors()
            st.rerun()

        st.write("")  # breathing room before drop zone

        tab_upload, tab_scanner = st.tabs(["📁 Upload File", "🖨 Flatbed Scanner"])

        with tab_upload:
            uploaded = st.file_uploader(
                "PNG · JPEG · TIFF  —  up to 50 MB",
                type=["png","jpg","jpeg","tif","tiff"],
                key="file_uploader",
                label_visibility="visible",
            )
            if uploaded:
                st.session_state.input_mode = "Upload File"
                file_id = getattr(uploaded, "file_id", uploaded.name)
                if file_id != st.session_state.last_file_id:
                    st.session_state.last_file_id = file_id
                    if not lot_id:
                        lot_id = datetime.now().strftime("LOT-%Y%m%d-%H%M%S")
                        st.session_state.last_lot_id = lot_id
                    scan_params = {**params_payload}
                    if ref_card:
                        scan_params["reference_card"] = ref_card
                    with st.spinner("Processing…  this takes a few seconds"):
                        ok_pipeline = _run_full_pipeline(
                            uploaded.getvalue(), uploaded.name, uploaded.type,
                            sel_profile, lot_id, dpi, scan_params,
                        )
                    if ok_pipeline:
                        st.rerun()

        with tab_scanner:
            st.session_state.input_mode = "Scanner"
            if st.button("Detect Scanners", key="btn_detect"):
                with st.spinner("Scanning network…"):
                    resp = _get("/scanner/devices")
                if resp:
                    st.session_state.scan_devices      = resp.get("devices", [])
                    st.session_state.scanner_backend   = resp.get("backend")
                    st.session_state.scanner_hint      = resp.get("install_hint")
                    st.session_state.scanner_available = resp.get("backend_available", False)

            devices   = st.session_state.get("scan_devices", [])
            s_avail   = st.session_state.get("scanner_available", None)
            valid_dev = [d for d in devices if isinstance(d, dict) and "name" in d]

            if s_avail is None:
                st.caption("Click **Detect Scanners** to find flatbed scanners on this machine or network.")
            elif s_avail is False:
                st.info(f"No scanner driver found.\n```\n{st.session_state.get('scanner_hint', '')}\n```")
            elif not valid_dev:
                st.warning("Scanner driver found but no devices detected. Make sure the scanner is powered on.")
            else:
                dev_map      = {d["name"]: d["id"] for d in valid_dev}
                sel_dev_name = st.selectbox("Scanner device", list(dev_map.keys()), key="scanner_sel")
                selected_dev = dev_map[sel_dev_name]
                sc1, sc2 = st.columns(2)
                color_mode  = sc1.radio("Colour mode", ["gray", "color", "lineart"], horizontal=True, key="sc_color")
                scan_source = sc2.radio("Paper source", ["Flatbed", "ADF"], horizontal=True, key="sc_src")
                if st.button("⬛ Scan Now", key="btn_scan", use_container_width=True, disabled=not ok):
                    with st.spinner("Scanning…  keep the scanner lid closed"):
                        result = _post("/scanner/scan-and-process",
                                       params={"device_id": selected_dev, "dpi": dpi,
                                               "color_mode": color_mode, "source": scan_source})
                    if result:
                        sid = result.get("scan_id")
                        st.session_state.scan_id        = sid
                        st.session_state.result         = result
                        st.session_state.quality_report = None
                        st.session_state.coa_bytes      = None
                        if not lot_id:
                            lot_id = datetime.now().strftime("LOT-%Y%m%d-%H%M%S")
                            st.session_state.last_lot_id = lot_id

                        # Fetch annotated image + measurements (same as upload pipeline)
                        try:
                            r_img = httpx.get(f"{API}/scans/{sid}/annotated-image", timeout=TIMEOUT)
                            if r_img.status_code == 200:
                                st.session_state.annotated_image = Image.open(io.BytesIO(r_img.content))
                        except Exception:
                            pass
                        ms = _get(f"/scans/{sid}/measurements")
                        if ms:
                            st.session_state.measurements_df = pd.DataFrame([{
                                "ID": m["grain_index"],
                                "Length (mm)": round(m["major_axis_mm"], 3),
                                "Width (mm)": round(m["minor_axis_mm"], 3),
                                "Area (mm²)": round(m["area_mm2"], 4),
                                "Perimeter (mm)": round(m["perimeter_mm"], 3),
                                "Aspect Ratio": round(m["aspect_ratio"], 3),
                                "Angle (°)": round(m["orientation_deg"], 1),
                                "Anomaly": ", ".join(m.get("anomaly_flags", [])),
                                "Recovered": "↩ Recovered" if m.get("recovered_from_cluster") else "",
                            } for m in ms])

                        # Grade + CoA
                        qp = {"profile_name": sel_profile}
                        if lot_id:
                            qp["lot_id"] = lot_id
                        qr = _get(f"/quality/assess/{sid}", params=qp)
                        if qr:
                            st.session_state.quality_report = qr
                            try:
                                coa_r = httpx.get(f"{API}/quality/coa/{sid}", params=qp, timeout=TIMEOUT)
                                if coa_r.status_code == 200:
                                    st.session_state.coa_bytes    = coa_r.content
                                    st.session_state.coa_filename = f"coa_{sid}.pdf"
                            except Exception:
                                pass
                        st.rerun()

    # ── Result view ───────────────────────────────────────────────────────────
    else:
        result  = st.session_state.result
        qr      = st.session_state.quality_report
        scan_id = st.session_state.scan_id
        stats   = result.get("statistics", {})

        grade    = qr.get("grade","?")    if qr else "—"
        score    = qr.get("total_score",0) if qr else 0
        decision = qr.get("decision","")   if qr else ""
        gc       = GRADE_COLORS.get(grade, C_MUTED)
        detected_count = result.get("detected_count", 0) or stats.get("grain_count", 0)
        cluster_est    = result.get("cluster_estimated_count", 0)
        n_grains       = result.get("grain_count", detected_count + cluster_est)
        df_now = st.session_state.measurements_df
        n_recovered = (int((df_now["Recovered"] != "").sum())
                       if df_now is not None and "Recovered" in df_now.columns else 0)
        # Read profile/lot from the graded report (not sidebar, which isn't rendered now)
        sel_profile  = (qr.get("profile_name") or st.session_state.last_profile) if qr else st.session_state.last_profile
        lot_id       = (qr.get("lot_id") or "") if qr else ""
        result_dpi   = result.get("dpi", 300)
        cal_note     = (f"  ·  📐 card-calibrated ({result_dpi} eff. DPI)"
                        if st.session_state.get("main_ref_card","— No reference —") != "— No reference —"
                        else "")

        # ── Result header ─────────────────────────────────────────────────────
        st.markdown(f"""
        <div style="background:{C_CARD};border:1px solid {C_BORDER};border-radius:14px;
                    padding:24px 28px;margin-bottom:20px;
                    box-shadow:0 2px 8px rgba(0,0,0,.06)">
          <div style="display:flex;align-items:center;gap:20px;flex-wrap:wrap">
            <div>
              <div style="font-size:.72rem;font-weight:700;text-transform:uppercase;
                          letter-spacing:.07em;color:{C_MUTED};margin-bottom:4px">Grade</div>
              <div style="font-size:3.2rem;font-weight:800;color:{gc};
                          letter-spacing:-.03em;line-height:1">{grade}</div>
            </div>
            <div style="width:1px;height:56px;background:{C_BORDER}"></div>
            <div>
              <div style="font-size:.72rem;font-weight:700;text-transform:uppercase;
                          letter-spacing:.07em;color:{C_MUTED};margin-bottom:4px">Score</div>
              <div style="font-size:2rem;font-weight:700;color:{C_TEXT}">{score}<span style="font-size:1rem;color:{C_MUTED}">/100</span></div>
            </div>
            <div style="width:1px;height:56px;background:{C_BORDER}"></div>
            <div title="Individually measured grains — basis of quality report">
              <div style="font-size:.72rem;font-weight:700;text-transform:uppercase;
                          letter-spacing:.07em;color:{C_MUTED};margin-bottom:4px">Detected</div>
              <div style="font-size:2rem;font-weight:700;color:{C_TEXT}">{detected_count}</div>
              <div style="font-size:.68rem;color:{C_MUTED}">100% measured</div>
            </div>
            <div style="width:1px;height:56px;background:{C_BORDER}"></div>
            <div title="Grains estimated inside touching clusters (red regions) — excluded from quality">
              <div style="font-size:.72rem;font-weight:700;text-transform:uppercase;
                          letter-spacing:.07em;color:{C_MUTED};margin-bottom:4px">Estimated</div>
              <div style="font-size:2rem;font-weight:700;color:{'#C47820' if cluster_est else C_TEXT}">{cluster_est}</div>
              <div style="font-size:.68rem;color:{C_MUTED}">in clusters</div>
            </div>
            <div style="width:1px;height:56px;background:{C_BORDER}"></div>
            <div title="Total grain count (detected + estimated)">
              <div style="font-size:.72rem;font-weight:700;text-transform:uppercase;
                          letter-spacing:.07em;color:{C_MUTED};margin-bottom:4px">Total</div>
              <div style="font-size:2rem;font-weight:700;color:{C_TEXT}">{n_grains}</div>
              <div style="font-size:.68rem;color:{C_MUTED}">overall</div>
            </div>
            <div style="flex:1;min-width:180px">
              <div style="font-size:.72rem;font-weight:700;text-transform:uppercase;
                          letter-spacing:.07em;color:{C_MUTED};margin-bottom:4px">Decision</div>
              <div style="font-size:1rem;font-weight:600;color:{gc}">{decision}</div>
              <div style="font-size:.82rem;color:{C_MUTED}">{sel_profile}{"  ·  "+lot_id if lot_id else ""}{cal_note}</div>
            </div>
          </div>
        </div>""", unsafe_allow_html=True)

        # ── Download row ──────────────────────────────────────────────────────
        d1,d2,d3,d4 = st.columns([2,2,2,2])
        coa_bytes = st.session_state.coa_bytes
        if coa_bytes:
            d1.download_button("⬇ Certificate of Analysis", data=coa_bytes,
                               file_name=st.session_state.coa_filename,
                               mime="application/pdf", use_container_width=True,
                               key="btn_coa")
        if scan_id:
            cr = httpx.get(f"{API}/scans/{scan_id}/export/csv", timeout=TIMEOUT)
            if cr.status_code == 200:
                d2.download_button("⬇ Grain CSV", data=cr.content,
                                   file_name=f"scan_{scan_id}_grains.csv",
                                   mime="text/csv", use_container_width=True, key="btn_csv")
            pr = httpx.get(f"{API}/scans/{scan_id}/export/pdf", timeout=TIMEOUT)
            if pr.status_code == 200:
                d3.download_button("⬇ PDF Report", data=pr.content,
                                   file_name=f"scan_{scan_id}_report.pdf",
                                   mime="application/pdf", use_container_width=True, key="btn_pdf")
        if d4.button("New Scan", use_container_width=True, key="btn_new"):
            _reset()
            st.rerun()

        st.divider()

        # ── Image + key metrics ───────────────────────────────────────────────
        img_col, info_col = st.columns([3, 2])

        with img_col:
            if st.session_state.annotated_image:
                st.image(st.session_state.annotated_image, use_container_width=True,
                         caption="Annotated scan")
            else:
                st.info("No annotated image.")

        with info_col:
            # Quality basis note
            if cluster_est:
                st.markdown(
                    f'<div style="font-size:.75rem;color:{C_MUTED};margin-bottom:8px;'
                    f'padding:6px 10px;background:#FDF1E6;border-left:3px solid {C_ACCENT};'
                    f'border-radius:4px">'
                    f'Quality report based on <b>{detected_count}</b> detected grains. '
                    f'<b>{cluster_est}</b> grains in red cluster regions are excluded.</div>',
                    unsafe_allow_html=True,
                )
            # Quality scorecards
            if qr and qr.get("parameters"):
                STATUS_CLR = {"pass":C_SUCCESS,"warn":C_WARN,"fail":C_ERROR}
                STATUS_LBL = {"pass":"Pass","warn":"Caution","fail":"Fail"}
                for p in qr["parameters"]:
                    sc    = STATUS_CLR.get(p["status"],C_MUTED)
                    is_min = p["name"] == "Head Rice (Whole)"
                    tgt   = f"≥{p['target']}{p['unit']}" if is_min else f"≤{p['target']}{p['unit']}"
                    note  = (f"<div style='font-size:.72rem;color:{C_MUTED};margin-top:4px'>"
                             f"{p.get('note','')}</div>") if p.get("note") else ""
                    st.markdown(f"""
                    <div style="background:{C_CARD};border:1px solid {sc}30;
                                border-left:3px solid {sc};border-radius:8px;
                                padding:10px 14px;margin-bottom:8px">
                      <div style="display:flex;align-items:center;justify-content:space-between">
                        <span style="font-size:.8rem;font-weight:600;color:{C_TEXT}">{p['name']}</span>
                        <span style="background:{sc}18;color:{sc};border-radius:5px;
                                     padding:2px 8px;font-size:.72rem;font-weight:700">
                          {STATUS_LBL.get(p['status'],p['status'].title())}</span>
                      </div>
                      <div style="font-size:1.4rem;font-weight:700;color:{C_TEXT};margin:4px 0 2px">
                        {p['measured']}{p['unit']}</div>
                      <div style="font-size:.75rem;color:{C_MUTED}">
                        target {tgt}  ·  {p['score']}/10</div>
                      {note}
                    </div>""", unsafe_allow_html=True)

            st.divider()
            # Grain size summary
            m1,m2 = st.columns(2)
            m1.metric("Avg Length", f"{stats.get('mean_major_axis_mm',0):.2f} mm")
            m2.metric("Avg Width",  f"{stats.get('mean_minor_axis_mm',0):.2f} mm")
            m3,m4 = st.columns(2)
            m3.metric("Avg Area",   f"{stats.get('mean_area_mm2',0):.3f} mm²")
            m4.metric("Avg Aspect", f"{stats.get('mean_aspect_ratio',0):.2f}")

            # Re-grade
            if qr:
                st.divider()
                st.caption("Re-grade with a different profile:")
                rg1,rg2 = st.columns([2,1])
                rg_profile = rg1.selectbox("Profile", _fetch_profiles(),
                                            index=0, key="rg_profile",
                                            label_visibility="collapsed")
                if rg2.button("Re-grade", use_container_width=True, key="btn_regrade"):
                    with st.spinner("Re-grading…"):
                        qp2 = {"profile_name": rg_profile}
                        if lot_id: qp2["lot_id"] = lot_id
                        new_qr = _get(f"/quality/assess/{scan_id}", params=qp2)
                        if new_qr:
                            st.session_state.quality_report = new_qr
                            st.session_state.last_profile   = rg_profile
                            try:
                                coa_r2 = httpx.get(f"{API}/quality/coa/{scan_id}",
                                                   params=qp2, timeout=TIMEOUT)
                                if coa_r2.status_code == 200:
                                    st.session_state.coa_bytes    = coa_r2.content
                                    st.session_state.coa_filename = f"coa_{scan_id}.pdf"
                            except Exception: pass
                    st.rerun()

        # ── Details (collapsible) ─────────────────────────────────────────────
        st.write("")
        with st.expander("Grain Details", expanded=False):
            det1, det2 = st.tabs(["Measurements", "Charts"])
            df = st.session_state.measurements_df

            with det1:
                if df is not None and not df.empty:
                    st.dataframe(df, use_container_width=True, height=300, column_config={
                        "ID":             st.column_config.NumberColumn(format="%d"),
                        "Length (mm)":    st.column_config.NumberColumn(format="%.3f mm"),
                        "Width (mm)":     st.column_config.NumberColumn(format="%.3f mm"),
                        "Area (mm²)":     st.column_config.NumberColumn(format="%.4f mm²"),
                        "Perimeter (mm)": st.column_config.NumberColumn(format="%.3f mm"),
                        "Aspect Ratio":   st.column_config.NumberColumn(format="%.3f"),
                        "Angle (°)":      st.column_config.NumberColumn(format="%.1f°"),
                    })

            with det2:
                if df is not None and not df.empty:
                    c_hist, c_scatter = st.columns(2)
                    with c_hist:
                        fig = px.histogram(df, x="Length (mm)", nbins=20,
                                           color_discrete_sequence=[C_ACCENT],
                                           title="Length distribution")
                        fig.update_traces(marker_line_width=0.5, marker_line_color="white")
                        fig.update_layout(**PLOT_BASE, height=280,
                                          yaxis=dict(gridcolor=C_BORDER,title="Count"),
                                          xaxis=dict(showgrid=False))
                        st.plotly_chart(fig, use_container_width=True)
                    with c_scatter:
                        fig2 = px.scatter(df, x="Length (mm)", y="Width (mm)",
                                          color="Aspect Ratio",
                                          color_continuous_scale=[[0,C_ACCENTL],[.5,C_ACCENT],[1,"#7A3A0A"]],
                                          title="Length vs Width")
                        fig2.update_layout(**PLOT_BASE, height=280,
                                           xaxis=dict(gridcolor=C_BORDER),
                                           yaxis=dict(gridcolor=C_BORDER))
                        st.plotly_chart(fig2, use_container_width=True)

                if qr:
                    pie = go.Figure(go.Pie(
                        labels=["Whole","Lg Broken","Sm Broken","Broken","FM"],
                        values=[qr["whole_count"],qr["large_broken_count"],
                                qr["small_broken_count"],qr["broken_count"],
                                qr["foreign_matter_count"]],
                        marker_colors=PIE_COLORS, hole=0.45, textinfo="percent",
                        hovertemplate="<b>%{label}</b><br>%{value} grains (%{percent})<extra></extra>",
                    ))
                    pie.update_layout(**{**PLOT_BASE,
                                        "height":260,"showlegend":True,
                                        "legend":dict(orientation="v",x=1,y=0.5,font_size=11),
                                        "margin":dict(l=0,r=0,t=20,b=0),
                                        "title":"Grain classification"})
                    st.plotly_chart(pie, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
#  VENDORS VIEW
# ══════════════════════════════════════════════════════════════════════════════
elif view == "Vendors":
    st.markdown(f'<h1>🏭&nbsp; Vendors</h1>'
                f'<p style="color:{C_MUTED};font-size:.85rem;margin:-2px 0 20px">'
                f'Manage suppliers and track quality history.</p>', unsafe_allow_html=True)

    vendors = st.session_state.vendors
    if not vendors:
        _load_vendors(); vendors = st.session_state.vendors

    left_v, right_v = st.columns([1, 2])

    with left_v:
        st.subheader("Vendor List")
        if st.button("Refresh", key="v_refresh"):
            _load_vendors(); vendors = st.session_state.vendors
        if vendors:
            for v in vendors:
                parts_v = [p for p in [v.get("commodity","").title(),
                    f"₹{v['price_per_kg']}/kg" if v.get("price_per_kg") else None] if p]
                contact = (f'<div style="font-size:.77rem;color:{C_MUTED};margin-top:2px">'
                           + v.get("contact_name","")
                           + (f"  ·  {v['phone']}" if v.get("phone") else "")
                           + "</div>") if (v.get("contact_name") or v.get("phone")) else ""
                st.markdown(f"""
                <div style="background:{C_CARD};border:1px solid {C_BORDER};border-radius:10px;
                            padding:12px 14px;margin-bottom:8px;box-shadow:0 1px 3px rgba(0,0,0,.05)">
                  <div style="font-size:.9rem;font-weight:700;color:{C_TEXT}">{v['name']}</div>
                  <div style="font-size:.78rem;color:{C_MUTED}">{'  ·  '.join(parts_v)}</div>
                  {contact}
                </div>""", unsafe_allow_html=True)
        else:
            st.caption("No vendors yet.")

    with right_v:
        with st.expander("Add Vendor", expanded=not bool(vendors)):
            with st.form("add_vendor", clear_on_submit=True):
                f1,f2 = st.columns(2)
                v_name  = f1.text_input("Company name *")
                v_comm  = f2.selectbox("Commodity",["rice","wheat","maize","sorghum","other"])
                f3,f4  = st.columns(2)
                v_cont  = f3.text_input("Contact name")
                v_phone = f4.text_input("Phone")
                f5,f6  = st.columns(2)
                v_email = f5.text_input("Email")
                v_price = f6.number_input("Price/kg (₹)",min_value=0.0,step=0.5,value=0.0)
                v_notes = st.text_area("Notes",height=60)
                if st.form_submit_button("Add Vendor") and v_name:
                    payload = {"name":v_name,"commodity":v_comm}
                    if v_cont:  payload["contact_name"] = v_cont
                    if v_phone: payload["phone"] = v_phone
                    if v_email: payload["email"] = v_email
                    if v_price > 0: payload["price_per_kg"] = v_price
                    if v_notes: payload["contract_notes"] = v_notes
                    resp = _post("/vendors/", json=payload)
                    if resp:
                        st.success(f"'{v_name}' added.")
                        _load_vendors(); st.rerun()

        st.subheader("Quality History")
        if vendors:
            vmap   = {v["name"]:v["id"] for v in vendors}
            vc     = st.columns([2,2,1])
            sel_vn = vc[0].selectbox("Vendor",list(vmap.keys()),key="vh_sel")
            sel_vp = vc[1].selectbox("Profile",_fetch_profiles(),key="vh_profile")
            if vc[2].button("Load",use_container_width=True,key="vh_load"):
                data = _get(f"/vendors/{vmap[sel_vn]}/history",params={"profile_name":sel_vp})
                if data: st.session_state.vendor_history = data

            vh = st.session_state.vendor_history
            if vh:
                vi = vh.get("vendor",{}); summaries = vh.get("summaries",[])
                meta = "  ·  ".join(filter(None,[vi.get("commodity","").title(),
                    f"{vh['scan_count']} lots", f"Avg {vh.get('avg_quality_score',0)}/100"]))
                st.markdown(f"""
                <div style="background:{C_CARD};border:1px solid {C_BORDER};border-radius:10px;
                            padding:12px 16px;margin-bottom:12px">
                  <div style="font-weight:700;color:{C_TEXT}">{vi.get('name','')}</div>
                  <div style="font-size:.8rem;color:{C_MUTED}">{meta}</div>
                </div>""", unsafe_allow_html=True)
                if summaries:
                    df_v = pd.DataFrame(summaries)
                    if "processed_at" in df_v.columns:
                        df_v["processed_at"] = pd.to_datetime(df_v["processed_at"],errors="coerce")
                        df_v = df_v.sort_values("processed_at")
                    t1,t2 = st.tabs(["Trend","Lots"])
                    with t1:
                        if not df_v.get("processed_at",pd.Series()).isna().all():
                            fv = go.Figure()
                            fv.add_trace(go.Scatter(x=df_v["processed_at"],y=df_v["total_score"],
                                mode="lines+markers",name="Score",
                                line=dict(color=C_ACCENT,width=2.5),marker=dict(size=7)))
                            fv.add_trace(go.Scatter(x=df_v["processed_at"],y=df_v["total_broken_pct"],
                                mode="lines+markers",name="Broken %",yaxis="y2",
                                line=dict(color=C_ERROR,width=2,dash="dot"),marker=dict(size=5)))
                            fv.update_layout(**{**PLOT_BASE,"height":260,
                                "yaxis":dict(title="Score",range=[0,100],gridcolor=C_BORDER),
                                "yaxis2":dict(title="Broken %",overlaying="y",side="right",showgrid=False)})
                            st.plotly_chart(fv,use_container_width=True)
                    with t2:
                        disp=[c for c in["scan_id","lot_id","processed_at","grain_count",
                            "grade","total_score","head_rice_pct","total_broken_pct","decision"]
                            if c in df_v.columns]
                        st.dataframe(df_v[disp],use_container_width=True)
                else:
                    st.info("No processed scans linked to this vendor.")


# ══════════════════════════════════════════════════════════════════════════════
#  ANALYTICS VIEW
# ══════════════════════════════════════════════════════════════════════════════
elif view == "Analytics":
    st.markdown(f'<h1>📊&nbsp; Analytics</h1>'
                f'<p style="color:{C_MUTED};font-size:.85rem;margin:-2px 0 20px">'
                f'Quality trends across all lots.</p>', unsafe_allow_html=True)

    ac = st.columns([2,1,1])
    hist_profile = ac[0].selectbox("Profile", _fetch_profiles(), key="an_profile")
    hist_limit   = ac[1].number_input("Max scans", 5, 200, 50, key="an_limit")
    if ac[2].button("Load", use_container_width=True, key="an_load"):
        data = _get("/quality/history",
                    params={"profile_name":hist_profile,"limit":int(hist_limit)})
        if data: st.session_state.lot_history = data

    hist = st.session_state.lot_history
    if not hist or not hist.get("summaries"):
        st.info("No history yet — process and grade some scans first, then click Load.")
    else:
        df_h = pd.DataFrame(hist["summaries"])
        if "processed_at" in df_h.columns:
            df_h["processed_at"] = pd.to_datetime(df_h["processed_at"],errors="coerce")
            df_h = df_h.sort_values("processed_at")

        k1,k2,k3,k4 = st.columns(4)
        k1.metric("Total Lots",        len(df_h))
        k2.metric("Avg Score",         f"{df_h['total_score'].mean():.1f}/100")
        k3.metric("Most Common Grade", df_h["grade"].value_counts().idxmax())
        k4.metric("Avg Broken %",      f"{df_h['total_broken_pct'].mean():.1f}%")
        st.divider()

        t1,t2,t3 = st.tabs(["Score Trend","Grade Distribution","All Lots"])
        with t1:
            if not df_h["processed_at"].isna().all():
                fig_t = go.Figure()
                fig_t.add_trace(go.Scatter(x=df_h["processed_at"],y=df_h["total_score"],
                    mode="lines+markers",name="Quality Score",fill="tozeroy",
                    line=dict(color=C_ACCENT,width=2.5),marker=dict(size=7,color=C_ACCENT),
                    fillcolor=C_ACCENTL))
                fig_t.add_trace(go.Scatter(x=df_h["processed_at"],y=df_h["total_broken_pct"],
                    mode="lines+markers",name="Broken %",yaxis="y2",
                    line=dict(color=C_ERROR,width=1.8,dash="dot"),marker=dict(size=5,color=C_ERROR)))
                fig_t.update_layout(**{**PLOT_BASE,"height":340,
                    "yaxis":dict(title="Score (0–100)",range=[0,100],gridcolor=C_BORDER),
                    "yaxis2":dict(title="Broken %",overlaying="y",side="right",showgrid=False)})
                st.plotly_chart(fig_t,use_container_width=True)
        with t2:
            gc_d = df_h["grade"].value_counts().reset_index()
            gc_d.columns = ["Grade","Count"]
            fig_b = px.bar(gc_d,x="Grade",y="Count",color="Grade",
                           color_discrete_map=GRADE_COLORS,text="Count")
            fig_b.update_traces(textposition="outside",marker_line_width=0)
            fig_b.update_layout(**PLOT_BASE,height=300,showlegend=False,
                                yaxis=dict(gridcolor=C_BORDER),xaxis=dict(showgrid=False))
            st.plotly_chart(fig_b,use_container_width=True)
        with t3:
            disp=[c for c in["scan_id","filename","processed_at","grade","total_score",
                "head_rice_pct","total_broken_pct","foreign_matter_pct","decision"]
                if c in df_h.columns]
            st.dataframe(df_h[disp],use_container_width=True,
                column_config={
                    "total_score":st.column_config.NumberColumn("Score",format="%.1f"),
                    "head_rice_pct":st.column_config.NumberColumn("Head Rice %",format="%.1f%%"),
                    "total_broken_pct":st.column_config.NumberColumn("Broken %",format="%.1f%%"),
                    "foreign_matter_pct":st.column_config.NumberColumn("FM %",format="%.1f%%"),
                })


# ══════════════════════════════════════════════════════════════════════════════
#  BATCH VIEW
# ══════════════════════════════════════════════════════════════════════════════
elif view == "Batch":
    st.markdown(f'<h1>📦&nbsp; Batch Processing</h1>'
                f'<p style="color:{C_MUTED};font-size:.85rem;margin:-2px 0 20px">'
                f'Upload multiple images and grade them all at once.</p>',
                unsafe_allow_html=True)

    if not ok:
        st.error("**Backend offline.** Run `uvicorn main:app --reload` to start it.")
        st.stop()

    # ── Batch context row ─────────────────────────────────────────────────────
    if not st.session_state.vendors:
        _load_vendors()
    b_vendors = st.session_state.vendors
    b_profiles = _fetch_profiles()

    bx1, bx2, bx3, bx4 = st.columns([2, 2, 2, 1])

    if b_vendors:
        bnames_v = [v["name"] for v in b_vendors]
        b_sel_v  = bx1.selectbox("Vendor", ["— None —"] + bnames_v, key="batch_vendor")
        if b_sel_v != "— None —":
            bvobj = next(v for v in b_vendors if v["name"] == b_sel_v)
            st.session_state.selected_vendor_id = bvobj["id"]
        else:
            st.session_state.selected_vendor_id = None
    else:
        bx1.caption("No vendors yet")

    b_lot = bx2.text_input("Lot prefix", value=st.session_state.last_lot_id,
                            placeholder="LOT-2024  → LOT-2024-1, -2 …", key="batch_lot_inline")

    b_default_idx = (b_profiles.index(st.session_state.last_profile)
                     if st.session_state.last_profile in b_profiles else 0)
    b_profile = bx3.selectbox("Quality Profile", b_profiles,
                               index=b_default_idx, key="batch_profile_inline")

    if bx4.button("↻", key="batch_v_ref", help="Refresh vendor list",
                  use_container_width=True):
        _load_vendors()
        st.rerun()

    st.write("")

    batch_files = st.file_uploader(
        "Select image files  (PNG · JPEG · TIFF)",
        type=["png","jpg","jpeg","tif","tiff"],
        accept_multiple_files=True,
        key="batch_uploader",
    )

    if batch_files:
        st.caption(f"{len(batch_files)} file(s) selected.")
        batch_col1, batch_col2 = st.columns([1, 1])
        if batch_col1.button("▶  Process All", use_container_width=True, key="btn_batch_run"):
            b_dpi       = st.session_state.get("adv_dpi", 300)
            b_vendor_id = st.session_state.selected_vendor_id

            results: list[dict] = []
            prog = st.progress(0.0, text="Starting…")
            status_cell = st.empty()
            n = len(batch_files)
            b_lot_base = b_lot if b_lot else datetime.now().strftime("LOT-%Y%m%d")
            for i, f in enumerate(batch_files):
                lot_i = f"{b_lot_base}-{i+1}"
                prog.progress(i / n, text=f"Processing {f.name}  ({i+1}/{n})…")
                status_cell.info(f"**{f.name}**  —  uploading & measuring…")
                r = _batch_process_one(f, lot_i, b_profile, b_dpi, b_vendor_id)
                results.append(r)
            prog.progress(1.0, text="All done!")
            status_cell.empty()
            st.session_state.batch_results = results
            st.rerun()

        if batch_col2.button("Clear results", use_container_width=True, key="btn_batch_clear"):
            st.session_state.batch_results = None
            st.rerun()

    bres = st.session_state.batch_results
    if bres:
        st.divider()
        done  = [r for r in bres if r.get("status") == "done"]
        errs  = [r for r in bres if r.get("status") == "error"]

        k1,k2,k3,k4 = st.columns(4)
        k1.metric("Files processed", len(done))
        k2.metric("Errors",          len(errs))
        if done:
            avg_score = sum(r.get("score",0) for r in done) / len(done)
            k3.metric("Avg Score", f"{avg_score:.1f}/100")
            from collections import Counter
            top_grade = Counter(r.get("grade","?") for r in done).most_common(1)[0][0]
            k4.metric("Most Common Grade", top_grade)

        if done:
            df_b = pd.DataFrame(done)
            disp_cols = [c for c in ["filename","lot_id","grain_count","grade","score",
                                     "head_rice_pct","broken_pct","decision"]
                         if c in df_b.columns]
            st.dataframe(df_b[disp_cols], use_container_width=True, column_config={
                "score":          st.column_config.NumberColumn("Score",format="%.1f"),
                "head_rice_pct":  st.column_config.NumberColumn("Head Rice %",format="%.1f%%"),
                "broken_pct":     st.column_config.NumberColumn("Broken %",format="%.1f%%"),
                "grain_count":    st.column_config.NumberColumn("Grains",format="%d"),
            })

            csv_buf = io.StringIO()
            df_b[disp_cols].to_csv(csv_buf, index=False)
            st.download_button("⬇ Download batch CSV", data=csv_buf.getvalue().encode(),
                               file_name="batch_results.csv", mime="text/csv",
                               use_container_width=False, key="btn_batch_csv")

        if errs:
            with st.expander(f"⚠ {len(errs)} error(s)", expanded=True):
                for r in errs:
                    st.error(f"**{r['filename']}**: {r.get('error','Unknown error')}")


# ══════════════════════════════════════════════════════════════════════════════
#  CALIBRATION VIEW
# ══════════════════════════════════════════════════════════════════════════════
elif view == "Calibration":
    st.markdown(f'<h1>⚖️&nbsp; Calibration</h1>'
                f'<p style="color:{C_MUTED};font-size:.85rem;margin:-2px 0 20px">'
                f'Manage DPI-to-mm conversion profiles for accurate measurements.</p>',
                unsafe_allow_html=True)

    def _load_cal_profiles():
        data = _get("/calibration/profiles")
        st.session_state.cal_profiles = data or []

    if st.session_state.cal_profiles is None:
        _load_cal_profiles()

    cal_left, cal_right = st.columns([1, 2])

    with cal_left:
        st.subheader("Profiles")
        if st.button("Refresh", key="cal_refresh"):
            _load_cal_profiles()

        profiles_list = st.session_state.cal_profiles or []
        if not profiles_list:
            st.caption("No profiles yet. Create one on the right.")
        else:
            for p in profiles_list:
                active = p.get("is_active", False)
                badge = (f'<span style="background:{C_SUCCESS}22;color:{C_SUCCESS};'
                         f'border-radius:4px;padding:1px 7px;font-size:.7rem;font-weight:700">'
                         f'ACTIVE</span>') if active else ""
                st.markdown(f"""
                <div style="background:{C_CARD};border:1px solid {C_BORDER};
                            border-radius:10px;padding:12px 14px;margin-bottom:8px">
                  <div style="display:flex;align-items:center;justify-content:space-between">
                    <span style="font-weight:700;color:{C_TEXT}">{p['name']}</span>
                    {badge}
                  </div>
                  <div style="font-size:.8rem;color:{C_MUTED};margin-top:4px">
                    {p['dpi']} DPI &nbsp;·&nbsp; {p['px_per_mm']:.3f} px/mm
                    &nbsp;·&nbsp; {p.get('reference_type','dpi')}
                  </div>
                </div>""", unsafe_allow_html=True)
                a1, a2 = st.columns(2)
                if not active:
                    if a1.button("Set active", key=f"cal_act_{p['id']}", use_container_width=True):
                        _put(f"/calibration/profiles/{p['id']}/activate")
                        _load_cal_profiles(); st.rerun()
                if a2.button("Delete", key=f"cal_del_{p['id']}", use_container_width=True):
                    _delete(f"/calibration/profiles/{p['id']}")
                    _load_cal_profiles(); st.rerun()

    with cal_right:
        tab_dpi, tab_img = st.tabs(["Create from DPI", "Create from Reference Image"])

        with tab_dpi:
            st.markdown(
                f'<p style="color:{C_MUTED};font-size:.85rem">'
                f'Use when you know the scanner DPI exactly. '
                f'Converts DPI to px/mm (px/mm = DPI ÷ 25.4).</p>',
                unsafe_allow_html=True)
            with st.form("cal_dpi_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                cal_dpi  = c1.number_input("Scanner DPI", 72, 9600, 300, 50)
                cal_name = c2.text_input("Profile name", value=f"Scanner {300} DPI")
                if st.form_submit_button("Create Profile"):
                    resp = httpx.post(f"{API}/calibration/profiles/from-dpi",
                                      data={"dpi": str(cal_dpi), "name": cal_name},
                                      timeout=TIMEOUT)
                    if resp.status_code in (200, 201):
                        st.success(f"Profile '{cal_name}' created.")
                        _load_cal_profiles(); st.rerun()
                    else:
                        st.error(f"Error: {resp.text}")

        with tab_img:
            st.markdown(
                f'<p style="color:{C_MUTED};font-size:.85rem">'
                f'Upload an image containing a square or circle of known size. '
                f'The system auto-detects the marker and computes px/mm.</p>',
                unsafe_allow_html=True)
            with st.form("cal_img_form", clear_on_submit=True):
                ref_file  = st.file_uploader("Reference image", type=["png","jpg","jpeg","tif"],
                                             key="cal_ref_img")
                ci1, ci2, ci3 = st.columns(3)
                known_mm  = ci1.number_input("Known size (mm)", 1.0, 500.0, 25.0, 0.5)
                ref_shape = ci2.selectbox("Shape", ["square","circle"])
                ref_name  = ci3.text_input("Profile name", value="Custom calibration")
                if st.form_submit_button("Calibrate & Save") and ref_file:
                    resp = httpx.post(
                        f"{API}/calibration/profiles/from-image",
                        files={"file": (ref_file.name, ref_file.getvalue(), ref_file.type)},
                        data={"known_size_mm": str(known_mm),
                              "reference_shape": ref_shape,
                              "name": ref_name},
                        timeout=TIMEOUT,
                    )
                    if resp.status_code in (200, 201):
                        st.success(f"Profile '{ref_name}' created from image.")
                        _load_cal_profiles(); st.rerun()
                    else:
                        try:
                            err = resp.json().get("detail","")
                        except Exception:
                            err = resp.text
                        st.error(f"Calibration failed: {err}")
