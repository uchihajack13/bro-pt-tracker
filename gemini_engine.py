import os
import re
import json
from typing import Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_gemini_client = None

def get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY belum diset di file .env!")
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client

def clean_latex_artifacts(text: str) -> str:
    r"""
    Membersihkan kebocoran sintaks LaTeX (seperti \mathbf{...}, \text{...}, atau $...$)
    agar tampilan Markdown di UI selalu bersih 100%.
    """
    if not text:
        return ""
    # Ubah \mathbf{...} menjadi **...**
    text = re.sub(r"\\mathbf\{([^}]*)\}", r"**\1**", text)
    # Ubah \text{...} atau \mathrm{...} menjadi teks biasa
    text = re.sub(r"\\(?:text|mathrm)\{([^}]*)\}", r"\1", text)
    # Hapus pembungkus math inline $...$ jika di dalamnya hanya angka/operasi sederhana
    text = re.sub(r"\$([^$\r\n]+)\$", r"\1", text)
    # Hapus sisa backslash LaTeX umum
    text = text.replace(r"\times", "x").replace(r"\approx", "~").replace(r"\cdot", "·")
    return text.strip()

BASE_SYSTEM_PROMPT = r"""
Kamu adalah "Bro PT", Personal Trainer, Ahli Fisiologi Olahraga, & Konsultan Nutrisi Pribadi tingkat tinggi untuk sahabatmu, Bro Derry (Pria, 31 tahun, tinggi 180 cm).

ATURAN EMAS INTERAKSI & KONSISTENSI DATA (WAJIB DIPATUHI):
1. GAYA BAHASA: Santai, akrab ("bro", "lu/gue" atau "kamu/aku" yang tegas dan suportif), tajam secara sains, objektif, dan TIDAK people-pleaser. Kalau pilihan makanan terlalu berlemak/gorengan atau melebihi kuota, tegur dengan dasar fisiologis yang jelas.
2. SINGLE SOURCE OF TRUTH (SATU SUARA DENGAN DASHBOARD):
   - Kamu DILARANG KERAS mengarang perhitungan BMR, NEAT, TDEE, atau Defisit sendiri di luar kepala!
   - Gunakan PERSIS angka dari blok [DATA RESMI DASHBOARD HARI INI (SINGLE SOURCE OF TRUTH)] yang disuplai oleh sistem Python:
     a) "Live Burn s.d Jam Ini" (BMR Berjalan + Workout + NEAT Berjalan) -> gunakan angka ini saat membahas pembakaran kalori sampai jam sekarang atau saat membandingkan dengan jam Garmin Forerunner 55.
     b) "Proyeksi TDEE 24 Jam & Defisit Harian" -> gunakan angka ini sebagai acuan anggaran makan harian dan proyeksi defisit akhir hari.
   - Jika Bro Derry mengirim screenshot Garmin Forerunner 55 (misal: Total 1.512 = Aktif 401 + Istirahat 1.111), jelaskan secara cerdas bahwa Garmin menghitung Kalori Istirahat dengan rumus RMR (sedentary) yang ~100 kcal lebih tinggi dari BMR murni sensor BIA HYD-1801, sedangkan Kalori Aktif Garmin (Olahraga + NEAT) sudah sinkron dengan Live Burn di Dashboard kita!
3. ATURAN MUTLAK ANTI-LATEX:
   - JANGAN PERNAH menulis rumus dengan format LaTeX seperti \mathbf, \text, atau membungkus angka dengan tanda dolar ($...$).
   - Gunakan teks biasa dan format Markdown standar (**tebal**, *miring*, bullet points, atau tabel Markdown).
4. PRINSIP DIET BRO DERRY:
   - Anti-nasi putih (utamakan karbohidrat kompleks berserat seperti umbi kukus, kentang, oat, sayur, buah segar).
   - Kejar target protein harian untuk menjaga massa otot (Lean Body Mass) sembari memangkas Visceral Fat dari 15.0 menuju <=10.0.
   - Jaga ketat kuota lemak harian (waspadai minyak gorengan, santan kental, saus berminyak).
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
- Berat Badan: {body.get('weight_kg', 91.8)} kg (Perubahan dari awal: {deltas.get('weight_diff_start', 0):+g} kg)
- Visceral Fat: {body.get('visceral_fat', 15.0)} (Perubahan: {deltas.get('vf_diff_start', 0):+g}) | Body Fat: {body.get('body_fat_pct', 27.0)}%
- Lean Body Mass (LBM): {targets.get('lbm_kg', 67.0)} kg | BMR 24 Jam: {energy.get('bmr_24h', 1937)} kcal

[2. DUAL-METRIC PEMBAKARAN KALORI (WAJIB DIGUNAKAN PERSIS OLEH AI)]
- 🔥 LIVE BURN s.d JAM {energy.get('current_time_wib', '')} WIB: {energy.get('live_tdee_kcal', 0)} kcal
  * Rincian Live Burn = BMR Berjalan ({energy.get('bmr_live', 0)} kcal) + Total Aktif Saat Ini ({energy.get('total_active_live_kcal', 0)} kcal [Sesi Workout: {energy.get('workout_active_kcal', 0)} kcal + NEAT/Gerak Harian: {energy.get('neat_live_kcal', 0)} kcal])
  * Saldo Kalori Live Saat Ini: {energy.get('live_deficit_kcal', 0)} kcal defisit berjalan
- 🎯 PROYEKSI TDEE 24 JAM PENUH (Sampai 24.00 WIB): {energy.get('projected_tdee_24h_kcal', 0)} kcal
  * Rincian Proyeksi 24 Jam = BMR 24 Jam ({energy.get('bmr_24h', 1937)} kcal) + Proyeksi Total Aktif 24 Jam ({energy.get('projected_active_24h_kcal', 0)} kcal)
  * Proyeksi Defisit Harian (Proyeksi TDEE 24 Jam - Kalori Masuk): -{energy.get('projected_deficit_24h_kcal', 0)} kcal

[3. KUOTA MAKRO ADAPTIF & ASUPAN HARI INI]
- Kalori Masuk: {cal_in} / {cal_target} kcal (Sisa Kuota Makan: {cal_target - cal_in} kcal)
- Protein: {prot_in} / {prot_target} g (Sisa Target: {round(prot_target - prot_in, 1)} g)
- Lemak: {fat_in} / {fat_target} g (Sisa Batas Maksimal: {round(fat_target - fat_in, 1)} g)
- Karbohidrat: {carb_in} / {carb_target} g

[4. LOG LATIHAN & MAKANAN HARI INI]
- Sesi Workout Today:
{workouts_str}
- Makanan Masuk:
{meals_str}
==============================================================
"""

SCAN_JSON_SCHEMA = r"""
Kembalikan HANYA JSON valid (tanpa markdown block ```json) dengan struktur persis berikut:
{
  "scan_type": "nutrition" | "workout" | "garmin_daily_summary" | "body_composition",
  "coach_evaluation": "Evaluasi kritis, tajam, dan taktis ala Bro PT dalam format Markdown rapi (DILARANG pakai LaTeX/backslash!). Sertakan Mini Dashboard ringkasan status makro/defisit berdasarkan DATA RESMI DASHBOARD.",
  "nutrition_data": {
    "meal_name": "Nama makanan lengkap",
    "calories": 0,
    "protein_g": 0.0,
    "fat_g": 0.0,
    "carbs_g": 0.0,
    "ai_notes": "Catatan singkat komposisi"
  },
  "workout_data": {
    "workout_type": "Nama latihan (contoh: HIIT Dumbbell / Lari / Strength)",
    "duration_min": 0,
    "active_kcal": 0,
    "total_kcal": 0,
    "avg_hr": 0,
    "max_hr": 0,
    "sweat_ml": 0,
    "ai_notes": "Catatan intensitas"
  },
  "garmin_summary_data": {
    "active_kcal": 0,
    "resting_kcal": 0,
    "total_kcal": 0
  },
  "body_data": {
    "weight_kg": 0.0,
    "bmi": 0.0,
    "body_fat_pct": 0.0,
    "visceral_fat": 0.0,
    "skeletal_muscle_pct": 0.0,
    "muscle_kg": 0.0,
    "muscle_pct": 0.0,
    "water_pct": 0.0,
    "bmr_kcal": 1937
  }
}

ATURAN PENTING MEMBEDAKAN SCREENSHOT GARMIN:
1. Jika gambar adalah layar LINGKARAN "Kalori Terbakar Hari Ini" yang bertuliskan "Aktif + Istirahat = Total Kalori" (tanpa durasi menit latihan dan tanpa detak jantung latihan), maka WAJIB pilih `"scan_type": "garmin_daily_summary"` dan isi `"garmin_summary_data"`. JANGAN masukkan ke `"workout"` agar tidak double-counting!
2. Jika gambar adalah rincian SESI OLAHRAGA spesifik (ada durasi menit/detik, detak jantung rata-rata/maks, keringat, kalori aktif latihan), pilih `"scan_type": "workout"` dan isi `"workout_data"`.
3. Isi `null` pada objek data yang tidak relevan dengan `scan_type` terpilih.
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

def analyze_image_and_extract(
    image_bytes: bytes,
    mime_type: str,
    user_note: str,
    daily_summary: dict
) -> dict:
    client = get_gemini_client()
    context_block = build_realtime_context_block(daily_summary)

    prompt = f"""
{context_block}

Catatan Tambahan dari Bro Derry saat upload foto ini: "{user_note or 'Tidak ada catatan khusus'}"

Tugasmu:
1. Identifikasi gambar ini secara presisi: apakah Foto Makanan (`nutrition`), Rincian Sesi Olahraga Garmin (`workout`), Lingkaran Total Kalori Harian Garmin (`garmin_daily_summary`), atau Timbangan BIA HYD-1801 (`body_composition`).
2. Ekstrak angkanya secara akurat dan berikan `coach_evaluation` yang mengacu langsung pada angka DATA RESMI DASHBOARD di atas.
{SCAN_JSON_SCHEMA}
"""
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[image_part, prompt],
        config=types.GenerateContentConfig(
            system_instruction=BASE_SYSTEM_PROMPT,
            temperature=0.25,
            response_mime_type="application/json"
        ),
    )
    return _parse_json_response(response.text)

def analyze_text_log_and_extract(user_text: str, daily_summary: dict) -> dict:
    client = get_gemini_client()
    context_block = build_realtime_context_block(daily_summary)

    prompt = f"""
{context_block}

Laporan Teks dari Bro Derry: "{user_text}"

Tugasmu:
1. Tentukan jenis laporan ini (`nutrition`, `workout`, `garmin_daily_summary`, atau `body_composition`).
2. Ekstrak estimasi makronutrisi atau metrik olahraganya secara objektif dan sains, lalu berikan `coach_evaluation` taktis.
{SCAN_JSON_SCHEMA}
"""
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=BASE_SYSTEM_PROMPT,
            temperature=0.25,
            response_mime_type="application/json"
        ),
    )
    return _parse_json_response(response.text)

def chat_with_bro_pt(
    user_message: str,
    daily_summary: dict,
    chat_history: list[dict],
    image_bytes: Optional[bytes] = None,
    mime_type: Optional[str] = "image/jpeg"
) -> str:
    """
    Menjawab konsultasi di Tab 3 dengan dukungan gambar (multimodal)
    dan 100% terkunci pada angka Single Source of Truth dari Python.
    """
    client = get_gemini_client()
    context_block = build_realtime_context_block(daily_summary)

    nl = "\n"
    chat_lines = [
        f"{'Bro Derry' if c.get('role') == 'user' else 'Bro PT'}: {c.get('message')}"
        for c in chat_history[-10:]
    ]
    recent_chats_str = nl.join(chat_lines) if chat_lines else "Belum ada riwayat obrolan sebelumnya."

    full_prompt = f"""
{context_block}

=== RIWAYAT OBROLAN TERAKHIR ===
{recent_chats_str}

=== PESAN BARU DARI BRO DERRY ===
"{user_message or 'Tolong analisis dan kritisi gambar yang gue kirim ini, Bro!'}"

INSTRUKSI JAWABAN:
- Jawab sebagai Bro PT dengan analisis tajam, praktis, dan 100% konsisten dengan angka [LIVE BURN s.d JAM INI] serta [PROYEKSI TDEE 24 JAM] yang tertera di DATA RESMI DASHBOARD di atas!
- Jika Bro Derry mengirim foto rencana makanan (misal kepiting, ayam, camilan), hitung estimasi kalorinya dan simulasi dampaknya terhadap Sisa Kuota Kalori, Protein, dan Batas Lemak hari ini (beritahu porsi amannya!).
- JANGAN PERNAH menggunakan sintaks LaTeX (seperti mathbf, text, atau tanda dolar). Gunakan Markdown biasa yang rapi dan nyaman dibaca di layar HP.
"""

    contents = [full_prompt]
    if image_bytes:
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        contents.insert(0, image_part)

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=BASE_SYSTEM_PROMPT,
            temperature=0.35,
        ),
    )
    return clean_latex_artifacts(response.text)