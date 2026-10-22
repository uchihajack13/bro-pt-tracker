import os
import re
import json
import time
from typing import Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# MEMBALIK URUTAN MODEL: Utamakan model alternatif agar tidak menabrak limit harian gemini-3.8-flash
FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-3.8-flash",
    "gemini-2.5-flash-lite",
]

def get_api_keys_pool() -> list[str]:
    keys = []
    try:
        import streamlit as st
        for k_name in ["GEMINI_API_KEY", "GEMINI_API_KEYS", "GEMINI_API_KEY_1", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_API_KEY_4", "GEMINI_API_KEY_5"]:
            if k_name in st.secrets and st.secrets[k_name]:
                raw_val = str(st.secrets[k_name])
                for part in raw_val.split(","):
                    clean_k = part.strip()
                    if clean_k and clean_k not in keys:
                        keys.append(clean_k)
    except Exception:
        pass

    for k_name in ["GEMINI_API_KEY", "GEMINI_API_KEYS", "GEMINI_API_KEY_1", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_API_KEY_4", "GEMINI_API_KEY_5"]:
        raw_val = os.getenv(k_name, "")
        if raw_val:
            for part in raw_val.split(","):
                clean_k = part.strip()
                if clean_k and clean_k not in keys:
                    keys.append(clean_k)

    if not keys:
        raise ValueError("GEMINI_API_KEY belum diset di file .env atau Streamlit Secrets!")
    return keys

def generate_with_smart_failover(contents, config: types.GenerateContentConfig):
    api_keys = get_api_keys_pool()
    models_to_try = list(dict.fromkeys(FALLBACK_MODELS))
    last_error = None

    for model_name in models_to_try:
        for api_key in api_keys:
            client = genai.Client(api_key=api_key)
            for attempt in range(2):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=config,
                    )
                    return response
                except Exception as e:
                    last_error = e
                    err_str = str(e).upper()
                    if "404" in err_str or "NOT_FOUND" in err_str:
                        break
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "QUOTA" in err_str:
                        # Langsung pindah ke API key atau model berikutnya
                        break
                    if "503" in err_str or "UNAVAILABLE" in err_str:
                        if attempt == 0:
                            time.sleep(1)
                            continue
                        break
                    break

    raise RuntimeError(f"Seluruh API Key dan model cadangan habis kuota. Detail terakhir: {last_error}")

def clean_latex_artifacts(text: str) -> str:
    r"""Membersihkan kebocoran sintaks LaTeX."""
    if not text:
        return ""
    text = re.sub(r"\\mathbf\{([^}]*)\}", r"**\1**", text)
    text = re.sub(r"\\(?:text|mathrm)\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\$([^$\r\n]+)\$", r"\1", text)
    text = text.replace(r"\times", "x").replace(r"\approx", "~").replace(r"\cdot", "·")
    return text.strip()

BASE_SYSTEM_PROMPT = r"""
Kamu adalah "Bro PT", Personal Trainer, Ahli Fisiologi Olahraga, & Konsultan Nutrisi Pribadi tingkat tinggi untuk sahabatmu, Bro Derry (Pria, 31 tahun, tinggi 180 cm).

ATURAN EMAS INTERAKSI & KONSISTENSI DATA (WAJIB DIPATUHI):
1. GAYA BAHASA: Santai, akrab ("bro", "lu/gue" atau "kamu/aku" yang tegas dan suportif), tajam secara sains, objektif, dan TIDAK people-pleaser. Kalau pilihan makanan terlalu berlemak/gorengan atau melebihi kuota, tegur dengan dasar fisiologis yang jelas.
2. SINGLE SOURCE OF TRUTH (SATU SUARA DENGAN DASHBOARD):
   - Kamu DILARANG KERAS mengarang perhitungan BMR, NEAT, TDEE, atau Defisit sendiri di luar kepala!
   - Gunakan PERSIS angka dari blok [DATA RESMI DASHBOARD HARI INI (SINGLE SOURCE OF TRUTH)] yang disuplai oleh sistem Python.
3. ATURAN MUTLAK ANTI-LATEX:
   - JANGAN PERNAH menulis rumus dengan format LaTeX seperti \mathbf, \text, atau membungkus angka dengan tanda dolar ($...$).
   - Gunakan teks biasa dan format Markdown standar.
"""

def build_realtime_context_block(daily_summary: dict) -> str:
    profile = daily_summary.get("profile", {})
    body = daily_summary.get("latest_body", {})
    deltas = daily_summary.get("body_deltas", {})
    targets = daily_summary.get("adaptive_targets", {})
    energy = daily_summary.get("energy", {})
    nutri = daily_summary.get("nutrition", {})
    work = daily_summary.get("workout", {})

    cal_in = nutri.get("calories_in", 0)
    prot_in = nutri.get("protein_g", 0)
    fat_in = nutri.get("fat_g", 0)
    carb_in = nutri.get("carbs_g", 0)

    cal_target = targets.get("calories_target", 2050)
    prot_target = targets.get("protein_g", 170)
    fat_target = targets.get("fat_g", 65)
    carb_target = targets.get("carbs_g", 190)

    nl = "\n"
    meals_list = [
        f"  - [{m.get('time')}] {m.get('meal_name')}: {m.get('calories')} kcal (P: {m.get('protein_g')}g, F: {m.get('fat_g')}g, C: {m.get('carbs_g')}g)"
        for m in nutri.get("logs", [])
    ]
    meals_str = nl.join(meals_list) if meals_list else "  - Belum ada makanan tercatat hari ini."

    workouts_list = [
        f"  - {w.get('workout_type')} ({w.get('duration_min')} mnt): Aktif {w.get('active_kcal')} kcal | Max HR {w.get('max_hr')} bpm"
        for w in work.get("logs", [])
    ]
    workouts_str = nl.join(workouts_list) if workouts_list else "  - Belum ada sesi latihan tercatat hari ini."

    return f"""
=== DATA RESMI DASHBOARD HARI INI (SINGLE SOURCE OF TRUTH) ===
- Waktu Server Saat Ini: {daily_summary.get('date')} Pukul {energy.get('current_time_wib', '')} WIB
- Mode Puasa Hari Ini: {profile.get('current_fasting_mode', 'IF (Buka 13.00 WIB)')}

[1. KOMPOSISI TUBUH TERBARU (BIA HYD-1801)]
- Berat Badan: {body.get('weight_kg', 91.8)} kg | Visceral Fat: {body.get('visceral_fat', 15.0)} | Body Fat: {body.get('body_fat_pct', 27.0)}%
- Lean Body Mass (LBM): {targets.get('lbm_kg', 67.0)} kg | BMR 24 Jam: {energy.get('bmr_24h', 1937)} kcal

[2. DUAL-METRIC PEMBAKARAN KALORI]
- 🔥 LIVE BURN s.d JAM {energy.get('current_time_wib', '')} WIB: {energy.get('live_tdee_kcal', 0)} kcal (Defisit Berjalan: {energy.get('live_deficit_kcal', 0)} kcal)
- 🎯 PROYEKSI TDEE 24 JAM: {energy.get('projected_tdee_24h_kcal', 0)} kcal (Proyeksi Defisit Harian: -{energy.get('projected_deficit_24h_kcal', 0)} kcal)

[3. KUOTA MAKRO ADAPTIF & ASUPAN HARI INI]
- Kalori Masuk: {cal_in} / {cal_target} kcal | Protein: {prot_in} / {prot_target} g | Lemak: {fat_in} / {fat_target} g | Karbo: {carb_in} / {carb_target} g

[4. LOG HARI INI]
- Sesi Workout:
{workouts_str}
- Makanan:
{meals_str}
==============================================================
"""

SCAN_JSON_SCHEMA = r"""
Kembalikan HANYA JSON valid (tanpa markdown block ```json) dengan struktur persis berikut:
{
  "scan_type": "nutrition" | "workout" | "garmin_daily_summary" | "body_composition",
  "coach_evaluation": "Evaluasi kritis, tajam, dan taktis ala Bro PT dalam format Markdown rapi.",
  "nutrition_data": { "meal_name": "...", "calories": 0, "protein_g": 0.0, "fat_g": 0.0, "carbs_g": 0.0, "ai_notes": "..." },
  "workout_data": { "workout_type": "...", "duration_min": 0, "active_kcal": 0, "total_kcal": 0, "avg_hr": 0, "max_hr": 0, "sweat_ml": 0, "ai_notes": "..." },
  "garmin_summary_data": { "active_kcal": 0, "resting_kcal": 0, "total_kcal": 0 },
  "body_data": { "weight_kg": 0.0, "bmi": 0.0, "body_fat_pct": 0.0, "visceral_fat": 0.0, "skeletal_muscle_pct": 0.0, "muscle_kg": 0.0, "muscle_pct": 0.0, "water_pct": 0.0, "bmr_kcal": 1937 }
}
"""

def _parse_json_response(raw_text: str) -> dict:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    data = json.loads(cleaned)
    if "coach_evaluation" in data and data["coach_evaluation"]:
        data["coach_evaluation"] = clean_latex_artifacts(data["coach_evaluation"])
    return data

def analyze_image_and_extract(image_bytes: bytes, mime_type: str, user_note: str, daily_summary: dict) -> dict:
    context_block = build_realtime_context_block(daily_summary)
    prompt = f"""
{context_block}
Catatan dari Bro Derry: "{user_note or 'Tidak ada catatan khusus'}"
Tugasmu: Identifikasi gambar, ekstrak data, dan berikan `coach_evaluation`.
{SCAN_JSON_SCHEMA}
"""
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    config = types.GenerateContentConfig(
        system_instruction=BASE_SYSTEM_PROMPT,
        temperature=0.25,
        response_mime_type="application/json"
    )
    response = generate_with_smart_failover(contents=[image_part, prompt], config=config)
    return _parse_json_response(response.text)

def analyze_text_log_and_extract(user_text: str, daily_summary: dict) -> dict:
    context_block = build_realtime_context_block(daily_summary)
    prompt = f"""
{context_block}
Laporan Teks: "{user_text}"
Tugasmu: Tentukan jenis laporan, ekstrak metrik, berikan `coach_evaluation`.
{SCAN_JSON_SCHEMA}
"""
    config = types.GenerateContentConfig(
        system_instruction=BASE_SYSTEM_PROMPT,
        temperature=0.25,
        response_mime_type="application/json"
    )
    response = generate_with_smart_failover(contents=prompt, config=config)
    return _parse_json_response(response.text)

def chat_with_bro_pt(user_message: str, daily_summary: dict, chat_history: list[dict], image_bytes: Optional[bytes] = None, mime_type: Optional[str] = "image/jpeg") -> str:
    context_block = build_realtime_context_block(daily_summary)
    nl = "\n"
    chat_lines = [f"{'Bro Derry' if c.get('role') == 'user' else 'Bro PT'}: {c.get('message')}" for c in chat_history[-10:]]
    recent_chats_str = nl.join(chat_lines) if chat_lines else "Belum ada riwayat obrolan."

    full_prompt = f"""
{context_block}
=== RIWAYAT OBROLAN ===
{recent_chats_str}
=== PESAN BARU ===
"{user_message or 'Tolong analisis gambar ini, Bro!'}"
"""
    contents = [full_prompt]
    if image_bytes:
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        contents.insert(0, image_part)

    config = types.GenerateContentConfig(
        system_instruction=BASE_SYSTEM_PROMPT,
        temperature=0.35,
    )
    response = generate_with_smart_failover(contents=contents, config=config)
    return clean_latex_artifacts(response.text)