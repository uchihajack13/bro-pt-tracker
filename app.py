import os
import json
import time
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ==============================================================================
# 0. KONFIGURASI HALAMAN & JEMBATAN KREDENSIAL CLOUD (SECRET BRIDGE)
# ==============================================================================
st.set_page_config(
    page_title="Bro PT — Personal Trainer & Konsultan Nutrisi Derry",
    page_icon="💪",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Jembatan otomatis: Menyalin Streamlit Cloud Secrets ke os.environ
# agar firestore_db.py dan gemini_engine.py berjalan 100% tanpa perlu diubah!
try:
    if "GEMINI_API_KEY" in st.secrets:
        os.environ["GEMINI_API_KEY"] = str(st.secrets["GEMINI_API_KEY"])
    if "GEMINI_MODEL" in st.secrets:
        os.environ["GEMINI_MODEL"] = str(st.secrets["GEMINI_MODEL"])
    if "FIREBASE_SERVICE_ACCOUNT_JSON" in st.secrets:
        os.environ["FIREBASE_SERVICE_ACCOUNT_JSON"] = str(st.secrets["FIREBASE_SERVICE_ACCOUNT_JSON"])
    elif "firebase" in st.secrets:
        os.environ["FIREBASE_SERVICE_ACCOUNT_JSON"] = json.dumps(dict(st.secrets["firebase"]))
except Exception:
    # Jika dijalankan di laptop lokal tanpa secrets.toml, otomatis memakai .env & firebase-key.json
    pass

# Import mesin utama setelah jembatan kredensial siap
import firestore_db as db
import gemini_engine as ai


def render_html(html_str: str):
    """
    Membersihkan indentasi spasi di setiap baris agar parser Markdown Streamlit
    TIDAK PERNAH salah menganggap tag HTML sebagai blok kode (<pre><code>).
    """
    cleaned = "\n".join(line.strip() for line in html_str.splitlines() if line.strip())
    st.markdown(cleaned, unsafe_allow_html=True)


# ==============================================================================
# 1. DESAIN VISUAL: CUSTOM CSS BENTO GLASSMORPHISM (IDENTIK DENGAN INDEX.HTML)
# ==============================================================================
render_html("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-variant-numeric: tabular-nums;
}

.block-container {
    max-width: 520px !important;
    padding-top: 1.2rem !important;
    padding-bottom: 4rem !important;
}

.bento-card {
    background: rgba(22, 32, 48, 0.72);
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 1.15rem;
    padding: 1rem;
    margin-bottom: 0.75rem;
    box-shadow: 0 10px 30px -5px rgba(0, 0, 0, 0.35);
}

.bento-subcard {
    background: rgba(11, 17, 28, 0.75);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 0.9rem;
    padding: 0.8rem;
}

.badge-pro {
    font-size: 0.65rem;
    padding: 0.15rem 0.5rem;
    border-radius: 9999px;
    background: rgba(16, 185, 129, 0.15);
    color: #6ee7b7;
    border: 1px solid rgba(16, 185, 129, 0.3);
    font-weight: 800;
    vertical-align: middle;
}

.badge-delta-down {
    font-size: 0.68rem;
    padding: 0.15rem 0.45rem;
    background: rgba(16, 185, 129, 0.2);
    color: #6ee7b7;
    border: 1px solid rgba(16, 185, 129, 0.3);
    border-radius: 0.4rem;
    font-weight: 700;
}

.badge-delta-up {
    font-size: 0.68rem;
    padding: 0.15rem 0.45rem;
    background: rgba(245, 158, 11, 0.2);
    color: #fcd34d;
    border: 1px solid rgba(245, 158, 11, 0.3);
    border-radius: 0.4rem;
    font-weight: 700;
}

.macro-bar-bg {
    width: 100%;
    height: 10px;
    background: #0f172a;
    border-radius: 9999px;
    overflow: hidden;
    border: 1px solid #1e293b;
    margin-top: 4px;
    margin-bottom: 12px;
}

.fat-alert-box {
    font-size: 0.75rem;
    color: #fb7185;
    font-weight: 600;
    background: rgba(244, 63, 94, 0.12);
    border: 1px solid rgba(244, 63, 94, 0.25);
    border-radius: 0.65rem;
    padding: 0.6rem;
    margin-top: 0.3rem;
}

div[data-baseweb="tab-list"] {
    gap: 4px;
    background-color: rgba(15, 23, 42, 0.8);
    padding: 4px;
    border-radius: 0.85rem;
    border: 1px solid rgba(255, 255, 255, 0.08);
}

button[data-baseweb="tab"] {
    flex: 1;
    border-radius: 0.65rem !important;
    padding: 0.45rem 0.2rem !important;
    font-size: 0.78rem !important;
    font-weight: 700 !important;
}
</style>
""")

# ==============================================================================
# 2. SMART SESSION-STATE CACHE & AUTO-RETRY ENGINE (ANTI-LEMOT & ANTI-503)
# ==============================================================================
def refresh_all_data():
    """Mengambil data terbaru dari Firestore dan menyimpannya ke cache sesi."""
    st.session_state.dashboard_data = db.get_daily_dashboard_summary()
    st.session_state.analytics_data = {
        "body_composition": db.get_body_composition_logs(),
        "daily_nutrition": db.get_nutrition_logs(limit=100),
        "workout_logs": db.get_workout_logs(limit=60)
    }
    st.session_state.chat_history = db.get_chat_history(limit=40)

if "dashboard_data" not in st.session_state:
    with st.spinner("⚡ Menghubungkan ke Firestore & memuat Single Source of Truth..."):
        refresh_all_data()

if "last_scan_result" not in st.session_state:
    st.session_state.last_scan_result = None

if "scan_uploader_key" not in st.session_state:
    st.session_state.scan_uploader_key = 0

if "chat_uploader_key" not in st.session_state:
    st.session_state.chat_uploader_key = 0

def call_ai_with_retry(func, *args, **kwargs):
    """Menjalankan fungsi Gemini dengan Auto-Retry 3x jika server Google 503 Overload."""
    last_err = None
    for attempt in range(3):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_err = e
            if ("503" in str(e) or "UNAVAILABLE" in str(e).upper()) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise e
    raise last_err

def save_ai_extracted_record(ai_result: dict):
    """Menyimpan hasil ekstraksi Vision/Teks ke koleksi Firestore yang sesuai."""
    scan_type = ai_result.get("scan_type")
    saved_record = None

    if scan_type == "nutrition" and ai_result.get("nutrition_data"):
        saved_record = db.add_nutrition_log(ai_result["nutrition_data"])
    elif scan_type == "workout" and ai_result.get("workout_data"):
        saved_record = db.add_workout_log(ai_result["workout_data"])
    elif scan_type == "garmin_daily_summary" and ai_result.get("garmin_summary_data"):
        g_data = ai_result["garmin_summary_data"]
        saved_record = db.sync_garmin_daily_active(
            active_kcal=g_data.get("active_kcal", 0),
            resting_kcal=g_data.get("resting_kcal", 0),
            total_kcal=g_data.get("total_kcal", 0)
        )
    elif scan_type == "body_composition" and ai_result.get("body_data"):
        saved_record = db.add_body_composition(ai_result["body_data"])

    refresh_all_data()
    return saved_record

# ==============================================================================
# 3. HEADER UTAMA & TOMBOL REFRESH REAL-TIME
# ==============================================================================
d = st.session_state.dashboard_data
energy = d.get("energy", {})
targets = d.get("adaptive_targets", {})
deltas = d.get("body_deltas", {})
latest_body = d.get("latest_body", {})
nutri = d.get("nutrition", {})
workout = d.get("workout", {})

col_hdr1, col_hdr2 = st.columns([3.4, 1.2])
with col_hdr1:
    render_html(f"""
    <div style="margin-bottom: 4px;">
        <span style="font-size:1.2rem; font-weight:800; background: linear-gradient(to right, #34d399, #5eead4, #22d3ee); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
            BRO PT TRACKER
        </span>
        <span class="badge-pro">PRO v2</span>
        <div style="font-size:0.72rem; color:#94a3b8; font-weight:500; margin-top:2px;">
            📅 {d.get('date')} • Pukul {energy.get('current_time_wib', '--:--')} WIB
        </div>
    </div>
    """)

with col_hdr2:
    if st.button("🔄 Refresh", use_container_width=True):
        with st.spinner("Menyegarkan..."):
            refresh_all_data()
            st.rerun()

# ==============================================================================
# 4. NAVIGASI 4 TAB UTAMA
# ==============================================================================
tab_dash, tab_scan, tab_chat, tab_analytics = st.tabs([
    "📊 Dashboard",
    "📸 Scanner",
    "💬 Bro PT",
    "📈 Analitik"
])

# ==============================================================================
# TAB 1: MINI DASHBOARD HARIAN (COMFORT-FIRST & DUAL-METRIC)
# ==============================================================================
with tab_dash:
    # --- BARIS 1: MODE PUASA & JENDELA MAKAN ---
    fasting_options = [
        "IF (Buka 13.00 WIB)",
        "Puasa Sunah Senin-Kamis",
        "Maintenance / Non-Puasa"
    ]
    current_mode = d.get("profile", {}).get("current_fasting_mode", "IF (Buka 13.00 WIB)")
    if current_mode not in fasting_options:
        fasting_options.insert(0, current_mode)

    c_fast1, c_fast2 = st.columns([1.5, 1.5])
    with c_fast1:
        render_html(f"""
        <div style="padding-top:4px;">
            <span style="font-size:0.65rem; text-transform:uppercase; letter-spacing:0.05em; color:#94a3b8; font-weight:700; display:block;">
                Fase Metabolisme & Puasa
            </span>
            <span style="font-size:0.82rem; font-weight:800; color:#fbbf24;">
                {current_mode}
            </span>
        </div>
        """)
    with c_fast2:
        selected_mode = st.selectbox(
            "Ubah Mode Puasa",
            options=fasting_options,
            index=fasting_options.index(current_mode),
            label_visibility="collapsed"
        )
        if selected_mode != current_mode:
            db.update_fasting_mode(selected_mode)
            refresh_all_data()
            st.rerun()

    # --- BARIS 2: BENTO GRID 2 KOLOM (KOMPOSISI TUBUH BIA & WORKOUT + GARMIN) ---
    w_diff = deltas.get("weight_diff_start", 0)
    if w_diff < 0:
        delta_html = f'<span class="badge-delta-down">▼ {w_diff} kg</span>'
    elif w_diff > 0:
        delta_html = f'<span class="badge-delta-up">▲ +{w_diff} kg</span>'
    else:
        delta_html = '<span class="badge-delta-down">Target 80kg</span>'

    vf_diff = deltas.get("vf_diff_start", 0)
    vf_diff_str = f" ({'+' if vf_diff > 0 else ''}{vf_diff})" if vf_diff != 0 else ""

    workout_burn = workout.get("active_kcal", 0)
    total_sessions = len(workout.get("logs", []))
    total_active_live = energy.get("total_active_live_kcal", workout_burn)

    col_bento1, col_bento2 = st.columns(2)
    with col_bento1:
        render_html(f"""
        <div class="bento-card">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:0.72rem; color:#94a3b8; font-weight:700;">BB & Visceral</span>
                {delta_html}
            </div>
            <div style="margin: 10px 0;">
                <span style="font-size:1.65rem; font-weight:800; color:#ffffff;">{latest_body.get('weight_kg', 91.8)}</span>
                <span style="font-size:0.75rem; color:#94a3b8; font-weight:600;">kg</span>
            </div>
            <div style="padding-top:8px; border-top:1px solid rgba(255,255,255,0.08); display:flex; justify-content:space-between; font-size:0.72rem; color:#cbd5e1;">
                <span>VF: <strong style="color:#fbbf24;">{latest_body.get('visceral_fat', 15.0)}{vf_diff_str}</strong></span>
                <span>BF: <strong style="color:#f8fafc;">{latest_body.get('body_fat_pct', 27.0)}%</strong></span>
            </div>
        </div>
        """)

    with col_bento2:
        render_html(f"""
        <div class="bento-card">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:0.72rem; color:#94a3b8; font-weight:700;">Workout Today</span>
                <span style="font-size:0.68rem; color:#67e8f9; font-weight:700;">{total_sessions} Sesi</span>
            </div>
            <div style="margin: 10px 0;">
                <span style="font-size:1.65rem; font-weight:800; color:#22d3ee;">{workout_burn}</span>
                <span style="font-size:0.75rem; color:#94a3b8; font-weight:600;">kcal</span>
            </div>
            <div style="padding-top:8px; border-top:1px solid rgba(255,255,255,0.08); display:flex; justify-content:space-between; font-size:0.72rem; color:#cbd5e1;">
                <span>Durasi: <strong style="color:#f8fafc;">{workout.get('duration_min', 0)}m</strong></span>
                <span>Aktif+NEAT: <strong style="color:#67e8f9;">{total_active_live}</strong></span>
            </div>
        </div>
        """)

    # Tombol Expander Cepat untuk Sync Garmin Forerunner 55 (Anti-Double Counting)
    with st.expander("⌚ Quick Sync Kalori Aktif Garmin Forerunner 55 (Anti-Dobel Log Latihan)"):
        with st.form("garmin_sync_form", clear_on_submit=False):
            st.caption("Masukkan angka **Kalori Aktif** (warna merah) yang tertera di layar jam Garmin Forerunner 55 kamu saat ini:")
            g_col1, g_col2 = st.columns([2, 1])
            with g_col1:
                garmin_active_input = st.number_input(
                    "Kalori Aktif Garmin (kcal)",
                    min_value=0,
                    max_value=5000,
                    value=int(energy.get("garmin_synced_active_kcal", 0)),
                    step=10,
                    label_visibility="collapsed"
                )
            with g_col2:
                sync_btn = st.form_submit_button("⌚ Sync Sekarang", use_container_width=True)
            if sync_btn:
                db.sync_garmin_daily_active(active_kcal=int(garmin_active_input))
                refresh_all_data()
                st.success(f"Kalori aktif Garmin ({garmin_active_input} kcal) berhasil disinkronkan!")
                st.rerun()

    # --- BARIS 3: DUAL-METRIC ENERGY MONITOR (LIVE BURN vs PROYEKSI 24 JAM) ---
    live_tdee = energy.get("live_tdee_kcal", 0)
    bmr_live = energy.get("bmr_live", 0)
    proj_tdee_24 = energy.get("projected_tdee_24h_kcal", 0)
    proj_def_24 = energy.get("projected_deficit_24h_kcal", 0)

    clock_badge = (
        f"⌚ Synced Garmin ({energy.get('garmin_sync_time')})"
        if energy.get("garmin_synced_active_kcal", 0) > 0
        else f"⚡ Auto-NEAT Aktif ({energy.get('current_time_wib')} WIB)"
    )

    def_str = f"-{proj_def_24:,}".replace(",", ".") if proj_def_24 >= 0 else f"+{abs(proj_def_24):,}".replace(",", ".")
    def_color = "#34d399" if proj_def_24 >= 0 else "#fb7185"
    live_tdee_str = f"{live_tdee:,}".replace(",", ".")
    proj_tdee_str = f"{proj_tdee_24:,}".replace(",", ".")

    render_html(f"""
    <div class="bento-card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
            <span style="font-size:0.72rem; font-weight:800; text-transform:uppercase; letter-spacing:0.05em; color:#e2e8f0;">
                ⚡ Monitor Pembakaran & Defisit
            </span>
            <span style="font-size:0.66rem; color:#94a3b8; font-weight:600;">{clock_badge}</span>
        </div>
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px;">
            <div class="bento-subcard">
                <div style="font-size:0.65rem; font-weight:700; color:#22d3ee; text-transform:uppercase;">🔥 Live s.d Jam Ini</div>
                <div style="margin-top:4px;">
                    <span style="font-size:1.35rem; font-weight:800; color:#ffffff;">{live_tdee_str}</span>
                    <span style="font-size:0.7rem; color:#94a3b8;">kcal</span>
                </div>
                <div style="font-size:0.65rem; color:#94a3b8; margin-top:4px;">
                    BMR {bmr_live} + Aktif {total_active_live} kcal
                </div>
            </div>
            <div class="bento-subcard">
                <div style="font-size:0.65rem; font-weight:700; color:#34d399; text-transform:uppercase;">🎯 Defisit 24 Jam</div>
                <div style="margin-top:4px;">
                    <span style="font-size:1.35rem; font-weight:800; color:{def_color};">{def_str}</span>
                    <span style="font-size:0.7rem; color:#94a3b8;">kcal</span>
                </div>
                <div style="font-size:0.65rem; color:#94a3b8; margin-top:4px;">
                    Proyeksi TDEE 24h: {proj_tdee_str} kcal
                </div>
            </div>
        </div>
    </div>
    """)

    # --- BARIS 4: PROGRESS BAR MAKRO ADAPTIF & ALARM KUOTA LEMAK ---
    cal_in = nutri.get("calories_in", 0)
    prot_g = nutri.get("protein_g", 0)
    fat_g = nutri.get("fat_g", 0)
    carb_g = nutri.get("carbs_g", 0)

    target_cal = targets.get("calories_target", 2050)
    target_prot = targets.get("protein_g", 170)
    target_fat = targets.get("fat_g", 65)
    target_carb = targets.get("carbs_g", 190)
    lbm_kg = targets.get("lbm_kg", 67.0)

    sisa_cal = target_cal - cal_in
    cal_pct = min(100, round((cal_in / max(1, target_cal)) * 100))
    cal_status_str = f"Sisa: {sisa_cal}" if sisa_cal >= 0 else f"Lebih: +{abs(sisa_cal)}"

    sisa_prot = max(0.0, round(target_prot - prot_g, 1))
    prot_pct = min(100, round((prot_g / max(1, target_prot)) * 100))

    sisa_fat = round(target_fat - fat_g, 1)
    fat_pct = min(100, round((fat_g / max(1, target_fat)) * 100))
    is_fat_danger = fat_g >= (target_fat * 0.8)
    fat_bar_color = "#f43f5e" if is_fat_danger else "#10b981"
    fat_alert_html = (
        '<div class="fat-alert-box">🚨 AWAS BRO! Kuota lemak harianmu hampir habis/jebol. Stop gorengan, santan, & minyak malam ini!</div>'
        if is_fat_danger else ""
    )

    render_html(f"""
    <div class="bento-card">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:14px;">
            <div>
                <div style="font-size:0.75rem; font-weight:800; text-transform:uppercase; color:#e2e8f0;">Kuota Makro Adaptif</div>
                <div style="font-size:0.65rem; color:#94a3b8;">BMR 24h: {energy.get('bmr_24h', 1937)} kcal • Target Kalori & Protein Adaptif</div>
            </div>
            <span style="font-size:0.68rem; padding:2px 8px; border-radius:8px; background:#1e293b; color:#cbd5e1; font-weight:700; border:1px solid #334155; white-space:nowrap;">
                LBM: {lbm_kg} kg
            </span>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:0.75rem;">
            <span style="font-weight:600; color:#e2e8f0;">🍽️ Kalori Makan</span>
            <span style="font-weight:700; color:#e2e8f0;">{cal_in} / {target_cal} kcal ({cal_status_str})</span>
        </div>
        <div class="macro-bar-bg">
            <div style="width:{cal_pct}%; height:100%; background:linear-gradient(to right, #10b981, #2dd4bf);"></div>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:0.75rem;">
            <span style="font-weight:600; color:#e2e8f0;">💪 Protein (Jaga Otot)</span>
            <span style="font-weight:700; color:#22d3ee;">{prot_g} / {target_prot} g (Kurang: {sisa_prot}g)</span>
        </div>
        <div class="macro-bar-bg">
            <div style="width:{prot_pct}%; height:100%; background:linear-gradient(to right, #06b6d4, #3b82f6);"></div>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:0.75rem;">
            <span style="font-weight:600; color:#e2e8f0;">⚠️ Batas Lemak (Gorengan/Minyak)</span>
            <span style="font-weight:700; color:#fbbf24;">{fat_g} / {target_fat} g (Sisa: {sisa_fat}g)</span>
        </div>
        <div class="macro-bar-bg">
            <div style="width:{fat_pct}%; height:100%; background:{fat_bar_color};"></div>
        </div>
        {fat_alert_html}
        <div style="padding-top:10px; margin-top:6px; border-top:1px solid rgba(255,255,255,0.08); display:flex; justify-content:space-between; font-size:0.75rem; color:#94a3b8;">
            <span>🥗 Karbohidrat Kompleks (Anti-Nasi Putih):</span>
            <strong style="color:#e2e8f0;">{carb_g} / {target_carb} g</strong>
        </div>
    </div>
    """)

    # --- BARIS 5: DAFTAR LOG HARI INI + TOMBOL HAPUS CEPAT (✕) ---
    render_html("""
    <div style="display:flex; justify-content:space-between; align-items:center; margin: 12px 0 6px 0;">
        <span style="font-size:0.75rem; font-weight:800; text-transform:uppercase; color:#cbd5e1;">📋 Log Masuk Hari Ini</span>
        <span style="font-size:0.65rem; color:#64748b;">Klik ✕ jika salah input</span>
    </div>
    """)

    today_workouts = workout.get("logs", [])
    today_meals = nutri.get("logs", [])

    if not today_workouts and not today_meals:
        st.caption("_Belum ada log makanan atau sesi latihan tercatat hari ini._")
    else:
        for w_item in today_workouts:
            c_log1, c_log2 = st.columns([5.2, 1])
            with c_log1:
                render_html(f"""
                <div class="bento-subcard" style="margin-bottom:6px; border-left: 3px solid #22d3ee;">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
                        <strong style="font-size:0.78rem; color:#22d3ee; flex:1;">🏃 {w_item.get('workout_type')} ({w_item.get('duration_min')} mnt)</strong>
                        <strong style="font-size:0.78rem; color:#67e8f9; white-space:nowrap; flex-shrink:0;">-{w_item.get('active_kcal')} kcal</strong>
                    </div>
                    <div style="font-size:0.68rem; color:#94a3b8; margin-top:2px;">
                        Max HR: {w_item.get('max_hr') or '-'} bpm • Keringat: {w_item.get('sweat_ml') or '-'} ml
                    </div>
                </div>
                """)
            with c_log2:
                if st.button("✕", key=f"del_w_{w_item.get('doc_id')}", help="Hapus log latihan ini", use_container_width=True):
                    db.delete_document("workout_logs", w_item.get("doc_id"))
                    refresh_all_data()
                    st.rerun()

        for m_item in today_meals:
            c_log1, c_log2 = st.columns([5.2, 1])
            with c_log1:
                render_html(f"""
                <div class="bento-subcard" style="margin-bottom:6px; border-left: 3px solid #10b981;">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
                        <strong style="font-size:0.78rem; color:#ffffff; flex:1;">🍽️ [{m_item.get('time')}] {m_item.get('meal_name')}</strong>
                        <strong style="font-size:0.78rem; color:#34d399; white-space:nowrap; flex-shrink:0;">+{m_item.get('calories')} kcal</strong>
                    </div>
                    <div style="font-size:0.68rem; color:#94a3b8; margin-top:2px;">
                        P: {m_item.get('protein_g')}g • F: {m_item.get('fat_g')}g • C: {m_item.get('carbs_g')}g
                    </div>
                </div>
                """)
            with c_log2:
                if st.button("✕", key=f"del_m_{m_item.get('doc_id')}", help="Hapus log makanan ini", use_container_width=True):
                    db.delete_document("daily_nutrition", m_item.get("doc_id"))
                    refresh_all_data()
                    st.rerun()

# ==============================================================================
# TAB 2: SMART VISION SCANNER (4-IN-1 AUTO-LOGGER)
# ==============================================================================
with tab_scan:
    render_html("""
    <div class="bento-card">
        <div style="font-size:0.9rem; font-weight:800; color:#ffffff;">📸 Smart Vision Scanner (4-in-1)</div>
        <div style="font-size:0.74rem; color:#94a3b8; margin-top:4px; line-height:1.45;">
            Unggah <strong>Foto Makanan</strong>, <strong>Rincian Sesi Latihan Garmin</strong>, <strong>Lingkaran Kalori Harian Garmin</strong>, atau <strong>Timbangan BIA HYD-1801</strong>. Otomatis dibedakan tanpa <em>double-counting</em>!
        </div>
    </div>
    """)

    uploaded_scan_file = st.file_uploader(
        "📷 Pilih Foto / Ambil Gambar dari Kamera HP",
        type=["jpg", "jpeg", "png", "webp"],
        key=f"scanner_uploader_{st.session_state.scan_uploader_key}"
    )

    if uploaded_scan_file is not None:
        st.image(uploaded_scan_file, caption="Preview Gambar Siap Scan", use_container_width=True)

    scan_note = st.text_area(
        "Catatan Singkat (Opsional untuk Foto / Wajib untuk Log Teks Saja):",
        placeholder="Contoh: Dada ayam bakar 200gr + tahu kukus 2 potong, atau Pull-up 2x, Chin-up 3x, Push-up 5 set x 10 reps...",
        height=85
    )

    col_btn_scan1, col_btn_scan2 = st.columns(2)
    with col_btn_scan1:
        if st.button("🚀 Scan Foto & Simpan", type="primary", use_container_width=True):
            if uploaded_scan_file is None:
                st.warning("Pilih foto makanan / screenshot Garmin / timbangan dulu, Bro!")
            else:
                with st.spinner("⏳ Bro PT sedang membedah gambar & menyimpan ke Firestore..."):
                    try:
                        img_bytes = uploaded_scan_file.getvalue()
                        mime_type = uploaded_scan_file.type or "image/jpeg"
                        ai_res = call_ai_with_retry(
                            ai.analyze_image_and_extract,
                            image_bytes=img_bytes,
                            mime_type=mime_type,
                            user_note=scan_note,
                            daily_summary=st.session_state.dashboard_data
                        )
                        saved_rec = save_ai_extracted_record(ai_res)
                        st.session_state.last_scan_result = {
                            "scan_type": ai_res.get("scan_type"),
                            "coach_evaluation": ai_res.get("coach_evaluation", ""),
                            "saved_record": saved_rec
                        }
                        st.session_state.scan_uploader_key += 1
                        st.success("✅ Berhasil dianalisis dan disimpan ke Firestore!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal menganalisis gambar: {e}")

    with col_btn_scan2:
        if st.button("✍️ Log Teks Saja", use_container_width=True):
            if not scan_note.strip():
                st.warning("Ketik dulu makanan atau latihan yang mau dicatat di kotak catatan, Bro!")
            else:
                with st.spinner("⏳ Bro PT sedang menghitung makro/kalori & menyimpan..."):
                    try:
                        ai_res = call_ai_with_retry(
                            ai.analyze_text_log_and_extract,
                            user_text=scan_note.strip(),
                            daily_summary=st.session_state.dashboard_data
                        )
                        saved_rec = save_ai_extracted_record(ai_res)
                        st.session_state.last_scan_result = {
                            "scan_type": ai_res.get("scan_type"),
                            "coach_evaluation": ai_res.get("coach_evaluation", ""),
                            "saved_record": saved_rec
                        }
                        st.success("✅ Log teks berhasil dianalisis dan disimpan ke Firestore!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal mencatat teks: {e}")

    if st.session_state.last_scan_result:
        res_data = st.session_state.last_scan_result
        labels_map = {
            "nutrition": "🍽️ Log Nutrisi",
            "workout": "🏃 Workout Today",
            "garmin_daily_summary": "⌚ Sync Aktif Garmin (Anti-Dobel)",
            "body_composition": "⚖️ Timbangan BIA & Target Adaptif"
        }
        badge_label = labels_map.get(res_data.get("scan_type"), res_data.get("scan_type"))
        render_html(f"""
        <div class="bento-card" style="border-color: rgba(16, 185, 129, 0.35);">
            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(255,255,255,0.08); padding-bottom:8px; margin-bottom:10px;">
                <span style="font-size:0.78rem; font-weight:800; color:#34d399; text-transform:uppercase;">⚡ Evaluasi Kritis Bro PT</span>
                <span class="badge-pro">{badge_label}</span>
            </div>
        </div>
        """)
        st.markdown(res_data.get("coach_evaluation", ""))
        if res_data.get("saved_record"):
            with st.expander("🔍 Lihat Rincian Angka JSON yang Tersimpan di Firestore"):
                st.json(res_data["saved_record"])

# ==============================================================================
# TAB 3: TANYA BRO PT (SINGLE SOURCE OF TRUTH + MULTIMODAL FOTO)
# ==============================================================================
with tab_chat:
    render_html("""
    <div class="bento-card" style="display:flex; justify-content:space-between; align-items:center;">
        <div>
            <div style="font-size:0.88rem; font-weight:800; color:#ffffff;">💬 Konsultasi Taktis Bro PT</div>
            <div style="font-size:0.7rem; color:#94a3b8;">100% sinkron dengan Live Burn & Kuota Makro Dashboard</div>
        </div>
        <span class="badge-pro">1 Suara Aktif</span>
    </div>
    """)

    # Tombol Prompt Cepat (1-Tap Chips) Persis Seperti index.html
    q_col1, q_col2, q_col3 = st.columns(3)
    quick_prompt_triggered = None

    with q_col1:
        if st.button("🍽️ Ide Makan", use_container_width=True, help="Rekomendasi menu sesuai sisa kuota makro"):
            quick_prompt_triggered = "Bro, cek sisa kuota kalori & protein gue hari ini. Kasih rekomendasi menu makan berikutnya yang tinggi protein tapi aman di lemak!"
    with q_col2:
        if st.button("🔥 Cek Defisit", use_container_width=True, help="Evaluasi Live Burn & Proyeksi 24 Jam"):
            quick_prompt_triggered = "Bro, bedah status Live Burn dan Proyeksi Defisit 24 Jam gue detik ini, apakah progres pembakaran lemak visceral gue hari ini sudah on track?"
    with q_col3:
        if st.button("💪 Recovery", use_container_width=True, help="Evaluasi latihan & hidrasi"):
            quick_prompt_triggered = "Bro, evaluasi latihan gue hari ini dan kasih saran recovery serta hidrasi terbaik buat jaga massa otot!"

    # Lampiran Foto Opsional untuk Diskusi di Chat (Tanpa Masuk Auto-Logger)
    with st.expander("📷 Lampirkan Foto Rencana Makanan / Screenshot Garmin untuk Dikritisi"):
        chat_uploaded_img = st.file_uploader(
            "Unggah gambar untuk didiskusikan dengan Bro PT",
            type=["jpg", "jpeg", "png", "webp"],
            key=f"chat_img_uploader_{st.session_state.chat_uploader_key}"
        )
        if chat_uploaded_img is not None:
            st.image(chat_uploaded_img, width=180, caption="Foto siap dikirim bersama pesanmu")

    # Kotak Riwayat Percakapan
    chat_container = st.container(height=380)
    with chat_container:
        if not st.session_state.chat_history:
            st.info("Belum ada obrolan. Kirim foto makanan (misal kepiting/ayam) atau tanyakan strategi latihanmu hari ini, Bro!")
        for msg in st.session_state.chat_history:
            role_ui = "user" if msg.get("role") == "user" else "assistant"
            avatar_ui = "💪" if role_ui == "user" else "🤖"
            with st.chat_message(role_ui, avatar=avatar_ui):
                st.markdown(msg.get("message", ""))

    # Input Chat Bawah
    user_chat_input = st.chat_input("Curhat makanan / tanya takaran porsi / evaluasi Garmin...")
    final_chat_prompt = quick_prompt_triggered or user_chat_input

    if final_chat_prompt:
        img_bytes_chat = None
        mime_type_chat = "image/jpeg"
        if chat_uploaded_img is not None and not quick_prompt_triggered:
            img_bytes_chat = chat_uploaded_img.getvalue()
            mime_type_chat = chat_uploaded_img.type or "image/jpeg"

        user_log_msg = f"[📷 Foto] {final_chat_prompt}".strip() if img_bytes_chat else final_chat_prompt

        with chat_container:
            with st.chat_message("user", avatar="💪"):
                st.markdown(user_log_msg)
            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("⚡ Bro PT sedang menghitung & menganalisis..."):
                    try:
                        history_context = st.session_state.chat_history[-15:]
                        db.add_chat_message("user", user_log_msg)
                        reply_text = call_ai_with_retry(
                            ai.chat_with_bro_pt,
                            user_message=final_chat_prompt,
                            daily_summary=st.session_state.dashboard_data,
                            chat_history=history_context,
                            image_bytes=img_bytes_chat,
                            mime_type=mime_type_chat
                        )
                        db.add_chat_message("model", reply_text)
                        if img_bytes_chat:
                            st.session_state.chat_uploader_key += 1
                        st.markdown(reply_text)
                        refresh_all_data()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal menghubungi Gemini API: {e}")

# ==============================================================================
# TAB 4: ANALITIK TREN PLOTLY & DATA EDITOR FIRESTORE INTERAKTIF
# ==============================================================================
with tab_analytics:
    body_logs = st.session_state.analytics_data.get("body_composition", [])

    # --- GRAFIK 1: TREN PENURUNAN BB (KG) & VISCERAL FAT (DUAL-AXIS) ---
    render_html("""
    <div class="bento-card" style="padding-bottom:0.4rem;">
        <div style="font-size:0.78rem; font-weight:800; text-transform:uppercase; color:#34d399; margin-bottom:2px;">
            📉 Tren Penurunan BB (kg) & Visceral Fat
        </div>
    </div>
    """)

    if body_logs:
        dates = [x.get("date") for x in body_logs]
        weights = [x.get("weight_kg") for x in body_logs]
        vfs = [x.get("visceral_fat") for x in body_logs]
        muscle_pcts = [x.get("muscle_pct") for x in body_logs]
        water_pcts = [x.get("water_pct") for x in body_logs]

        fig_w_vf = make_subplots(specs=[[{"secondary_y": True}]])
        fig_w_vf.add_trace(
            go.Scatter(x=dates, y=weights, name="BB (kg)", mode="lines+markers", line=dict(color="#10b981", width=3)),
            secondary_y=False
        )
        fig_w_vf.add_trace(
            go.Scatter(x=dates, y=vfs, name="Visceral Fat", mode="lines+markers", line=dict(color="#f59e0b", width=2, dash="dot")),
            secondary_y=True
        )
        fig_w_vf.update_layout(
            height=240,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#94a3b8", size=10),
            margin=dict(l=10, r=10, t=30, b=10),
            legend=dict(orientation="h", y=1.18, x=0)
        )
        fig_w_vf.update_yaxes(title_text="kg", gridcolor="rgba(255,255,255,0.05)", secondary_y=False)
        fig_w_vf.update_yaxes(title_text="VF", showgrid=False, secondary_y=True)
        st.plotly_chart(fig_w_vf, use_container_width=True, config={"displayModeBar": False})

        # --- GRAFIK 2: OTOT (%) VS KADAR AIR (%) ---
        render_html("""
        <div class="bento-card" style="padding-bottom:0.4rem;">
            <div style="font-size:0.78rem; font-weight:800; text-transform:uppercase; color:#22d3ee;">
                💧 Otot (%) vs Kadar Air (%)
            </div>
            <div style="font-size:0.68rem; color:#94a3b8; margin-bottom:2px;">
                Memisahkan kurva otot dan fluktuasi hidrasi intraseluler HYD-1801
            </div>
        </div>
        """)

        fig_m_w = go.Figure()
        fig_m_w.add_trace(go.Scatter(x=dates, y=muscle_pcts, name="Total Otot (%)", mode="lines+markers", line=dict(color="#06b6d4", width=3)))
        fig_m_w.add_trace(go.Scatter(x=dates, y=water_pcts, name="Kadar Air (%)", mode="lines+markers", line=dict(color="#818cf8", width=2)))
        fig_m_w.update_layout(
            height=240,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#94a3b8", size=10),
            margin=dict(l=10, r=10, t=30, b=10),
            legend=dict(orientation="h", y=1.18, x=0),
            yaxis=dict(title="%", gridcolor="rgba(255,255,255,0.05)")
        )
        st.plotly_chart(fig_m_w, use_container_width=True, config={"displayModeBar": False})
    else:
        st.info("Belum ada data timbangan BIA tercatat.")

    # --- DATA EDITOR FIRESTORE INTERAKTIF ---
    render_html("""
    <div class="bento-card">
        <div style="font-size:0.82rem; font-weight:800; text-transform:uppercase; color:#ffffff;">✏️ Data Editor Firestore</div>
        <div style="font-size:0.7rem; color:#94a3b8;">Klik dua kali pada sel tabel untuk mengoreksi angka, atau centang kolom Hapus di sebelah kiri lalu tekan tombol Simpan.</div>
    </div>
    """)

    col_map = {
        "🍽️ Log Nutrisi (daily_nutrition)": ("daily_nutrition", ["date", "meal_name", "calories", "protein_g", "fat_g", "carbs_g"]),
        "🏃 Log Latihan (workout_logs)": ("workout_logs", ["date", "workout_type", "duration_min", "active_kcal", "total_kcal"]),
        "⚖️ Log Timbangan (body_composition)": ("body_composition", ["date", "weight_kg", "body_fat_pct", "visceral_fat", "muscle_pct", "water_pct", "bmr_kcal"])
    }

    selected_label = st.selectbox("Pilih Koleksi Database:", list(col_map.keys()))
    col_name, fields_list = col_map[selected_label]
    raw_rows = st.session_state.analytics_data.get(col_name, [])

    if not raw_rows:
        st.caption("_Belum ada data di koleksi ini._")
    else:
        df_source = pd.DataFrame(raw_rows)
        for f in fields_list:
            if f not in df_source.columns:
                df_source[f] = None

        df_display = df_source[["doc_id"] + fields_list].copy().reset_index(drop=True)
        df_display.insert(0, "Hapus?", False)

        edited_df = st.data_editor(
            df_display,
            hide_index=True,
            disabled=["doc_id"],
            column_config={"doc_id": None},
            use_container_width=True,
            key=f"editor_{col_name}"
        )

        if st.button("💾 Terapkan Perubahan / Hapus Baris Terpilih ke Firestore", type="primary", use_container_width=True):
            with st.spinner("Menyinkronkan perubahan ke Firestore..."):
                changes_count = 0
                for idx, row in edited_df.iterrows():
                    doc_id = row["doc_id"]
                    if row["Hapus?"]:
                        db.delete_document(col_name, doc_id)
                        changes_count += 1
                    else:
                        orig_row = df_display.loc[idx]
                        updated_fields = {}
                        for f in fields_list:
                            if str(row[f]) != str(orig_row[f]):
                                val = row[f]
                                if pd.notna(val) and f not in ("date", "meal_name", "workout_type"):
                                    try:
                                        val = float(val) if "." in str(val) else int(val)
                                    except Exception:
                                        pass
                                updated_fields[f] = val
                        if updated_fields:
                            db.update_document(col_name, doc_id, updated_fields)
                            changes_count += 1

                if changes_count > 0:
                    refresh_all_data()
                    st.success(f"✅ {changes_count} baris data berhasil diperbarui di Firestore!")
                    st.rerun()
                else:
                    st.info("Tidak ada perubahan angka atau baris yang dicentang untuk dihapus.")