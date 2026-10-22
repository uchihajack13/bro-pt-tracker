import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

load_dotenv()

# Kunci zona waktu ke WIB agar latihan subuh & jam berjalan selalu presisi
WIB = ZoneInfo("Asia/Jakarta")

def get_now_wib() -> datetime:
    return datetime.now(WIB)

def get_today_str() -> str:
    return get_now_wib().strftime("%Y-%m-%d")

def get_time_str() -> str:
    return get_now_wib().strftime("%H:%M")

# ==============================================================================
# 1. INISIALISASI KONEKSI FIRESTORE (SINGLETON MURNI)
# ==============================================================================
_db_client = None

def get_db():
    """Inisialisasi koneksi Firebase Firestore (mendukung file lokal & Cloud Env)."""
    global _db_client
    if _db_client is not None:
        return _db_client

    if not firebase_admin._apps:
        firebase_json_str = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
        if firebase_json_str:
            cred_dict = json.loads(firebase_json_str)
            cred = credentials.Certificate(cred_dict)
        else:
            cred_path = os.getenv("FIREBASE_CRED_PATH", "firebase-key.json")
            cred = credentials.Certificate(cred_path)
            
        firebase_admin.initialize_app(cred)

    _db_client = firestore.client()
    return _db_client

# ==============================================================================
# 2. DATA MASTER & PROFIL PENGGUNA (user_profile)
# ==============================================================================
DEFAULT_MASTER_PROFILE = {
    "name": "Bro Derry",
    "gender": "Pria",
    "age": 31,
    "height_cm": 180,
    "waist_baseline_cm": 106.0,
    "waist_target_cm": 95.0,
    "targets": {
        "weight_min_kg": 80.0,
        "weight_max_kg": 82.0,
        "visceral_fat_max": 10.0,
        "calories_min": 2000,
        "calories_max": 2100,
        "protein_min_g": 160,
        "protein_max_g": 175,
        "fat_min_g": 55,
        "fat_max_g": 65,
        "carbs_min_g": 180,
        "carbs_max_g": 200,
        "diet_rules": "Anti-nasi putih; utamakan sumber serat, buah segar, atau umbi kukus. Jaga ketat kuota lemak dari gorengan/minyak."
    },
    "baseline_2026_10_22": {
        "date": "2026-10-22",
        "device": "BIA Hyundai HYD-1801",
        "condition": "Kamis Pagi, 22 Okt 2026 - Lambung Kosong",
        "weight_kg": 91.8,
        "bmi": 28.3,
        "body_fat_pct": 27.0,
        "body_fat_kg": 24.8,
        "visceral_fat": 15.0,
        "skeletal_muscle_pct": 38.7,
        "skeletal_muscle_kg": 35.5,
        "muscle_pct": 69.9,
        "muscle_kg": 64.1,
        "water_pct": 52.2,
        "water_kg": 47.9,
        "bone_mass_kg": 2.89,
        "protein_pct": 17.7,
        "bmr_kcal": 1937
    },
    "current_fasting_mode": "IF (Buka 13.00 WIB)"
}

def get_or_init_profile() -> dict:
    db = get_db()
    doc_ref = db.collection("user_profile").document("master_config")
    doc = doc_ref.get()
    if not doc.exists:
        doc_ref.set(DEFAULT_MASTER_PROFILE)
        seed_initial_body_composition()
        return DEFAULT_MASTER_PROFILE
    return doc.to_dict()

def update_fasting_mode(mode: str) -> dict:
    db = get_db()
    doc_ref = db.collection("user_profile").document("master_config")
    doc_ref.update({"current_fasting_mode": mode})
    return {"status": "updated", "current_fasting_mode": mode}

def seed_initial_body_composition():
    """Otomatis mengisi data baseline Kamis Pagi 22 Okt 2026 jika tabel masih kosong."""
    db = get_db()
    existing = list(db.collection("body_composition").limit(1).stream())
    if not existing:
        db.collection("body_composition").add({
            "date": "2026-10-22",
            "time_of_day": "Pagi (Lambung Kosong)",
            "weight_kg": 91.8,
            "bmi": 28.3,
            "body_fat_pct": 27.0,
            "visceral_fat": 15.0,
            "skeletal_muscle_pct": 38.7,
            "muscle_kg": 64.1,
            "muscle_pct": 69.9,
            "water_pct": 52.2,
            "bmr_kcal": 1937,
            "created_at": "2026-10-22T05:30:00+07:00"
        })

# ==============================================================================
# 3. KOLEKSI 1: daily_nutrition (Log Makanan & Makro)
# ==============================================================================
def add_nutrition_log(data: dict) -> dict:
    db = get_db()
    payload = {
        "date": data.get("date") or get_today_str(),
        "time": data.get("time") or get_time_str(),
        "meal_name": data.get("meal_name", "Makanan"),
        "calories": int(round(float(data.get("calories", 0)))),
        "protein_g": round(float(data.get("protein_g", 0)), 1),
        "fat_g": round(float(data.get("fat_g", 0)), 1),
        "carbs_g": round(float(data.get("carbs_g", 0)), 1),
        "ai_notes": data.get("ai_notes", ""),
        "created_at": get_now_wib().isoformat()
    }
    _, doc_ref = db.collection("daily_nutrition").add(payload)
    payload["doc_id"] = doc_ref.id
    return payload

def get_nutrition_logs(date_str: str = None, limit: int = 100) -> list[dict]:
    db = get_db()
    col = db.collection("daily_nutrition")
    docs = col.where("date", "==", date_str).stream() if date_str else col.order_by("date", direction=firestore.Query.DESCENDING).limit(limit).stream()
    items = [{"doc_id": d.id, **d.to_dict()} for d in docs]
    return sorted(items, key=lambda x: (x.get("date", ""), x.get("time", ""), x.get("created_at", "")), reverse=True)

# ==============================================================================
# 4. KOLEKSI 2: workout_logs (Log Sesi Latihan Spesifik)
# ==============================================================================
def add_workout_log(data: dict) -> dict:
    db = get_db()
    payload = {
        "date": data.get("date") or get_today_str(),
        "workout_type": data.get("workout_type", "Workout Today"),
        "duration_min": int(round(float(data.get("duration_min", 0)))),
        "active_kcal": int(round(float(data.get("active_kcal", 0)))),
        "total_kcal": int(round(float(data.get("total_kcal", 0)))),
        "avg_hr": int(round(float(data.get("avg_hr", 0)))),
        "max_hr": int(round(float(data.get("max_hr", 0)))),
        "sweat_ml": int(round(float(data.get("sweat_ml", 0)))),
        "ai_notes": data.get("ai_notes", ""),
        "created_at": get_now_wib().isoformat()
    }
    _, doc_ref = db.collection("workout_logs").add(payload)
    payload["doc_id"] = doc_ref.id
    return payload

def get_workout_logs(date_str: str = None, limit: int = 60) -> list[dict]:
    db = get_db()
    col = db.collection("workout_logs")
    docs = col.where("date", "==", date_str).stream() if date_str else col.order_by("date", direction=firestore.Query.DESCENDING).limit(limit).stream()
    items = [{"doc_id": d.id, **d.to_dict()} for d in docs]
    return sorted(items, key=lambda x: (x.get("date", ""), x.get("created_at", "")), reverse=True)

# ==============================================================================
# 5. KOLEKSI BARU: daily_garmin_sync (Sinkronisasi Kalori Aktif Harian Forerunner 55)
#    Mencegah Double-Counting dengan Log Latihan!
# ==============================================================================
def sync_garmin_daily_active(
    active_kcal: int,
    resting_kcal: int = 0,
    total_kcal: int = 0,
    date_str: str = None
) -> dict:
    """
    Menyimpan total kalori aktif harian dari layar lingkaran Garmin Connect
    tanpa menduplikasi log latihan di workout_logs.
    """
    db = get_db()
    target_date = date_str or get_today_str()
    now_wib = get_now_wib()
    sync_hour = round(now_wib.hour + (now_wib.minute / 60.0), 2)

    # Hitung total workout yang sudah tercatat saat sinkronisasi dilakukan
    current_workouts = get_workout_logs(target_date)
    workout_kcal_at_sync = sum(int(w.get("active_kcal", 0)) for w in current_workouts)

    payload = {
        "date": target_date,
        "garmin_active_kcal": int(round(float(active_kcal or 0))),
        "garmin_resting_kcal": int(round(float(resting_kcal or 0))),
        "garmin_total_kcal": int(round(float(total_kcal or 0))),
        "workout_kcal_at_sync": workout_kcal_at_sync,
        "sync_hour": sync_hour,
        "sync_time": now_wib.strftime("%H:%M"),
        "updated_at": now_wib.isoformat()
    }
    db.collection("daily_garmin_sync").document(target_date).set(payload, merge=True)
    return payload

def get_garmin_daily_sync(date_str: str = None) -> dict:
    db = get_db()
    target_date = date_str or get_today_str()
    doc = db.collection("daily_garmin_sync").document(target_date).get()
    if doc.exists:
        return doc.to_dict()
    return {}

# ==============================================================================
# 6. KOLEKSI 3: body_composition (Timbangan Hyundai HYD-1801)
# ==============================================================================
def add_body_composition(data: dict) -> dict:
    db = get_db()
    weight_kg = round(float(data.get("weight_kg", 91.8)), 2)
    bf_pct = round(float(data.get("body_fat_pct", 27.0)), 1)
    muscle_kg = round(float(data.get("muscle_kg", 0)), 2)
    muscle_pct = round(float(data.get("muscle_pct", 0)), 1)

    # Jika pengguna hanya menginput salah satu (muscle_kg atau muscle_pct), lengkapi otomatis
    if muscle_kg > 0 and muscle_pct == 0 and weight_kg > 0:
        muscle_pct = round((muscle_kg / weight_kg) * 100.0, 1)
    elif muscle_pct > 0 and muscle_kg == 0 and weight_kg > 0:
        muscle_kg = round((muscle_pct / 100.0) * weight_kg, 2)

    payload = {
        "date": data.get("date") or get_today_str(),
        "time_of_day": data.get("time_of_day", "Pagi (Lambung Kosong)"),
        "weight_kg": weight_kg,
        "bmi": round(float(data.get("bmi", round(weight_kg / (1.80 ** 2), 1))), 1),
        "body_fat_pct": bf_pct,
        "visceral_fat": round(float(data.get("visceral_fat", 15.0)), 1),
        "skeletal_muscle_pct": round(float(data.get("skeletal_muscle_pct", 38.7)), 1),
        "muscle_kg": muscle_kg or 64.1,
        "muscle_pct": muscle_pct or 69.9,
        "water_pct": round(float(data.get("water_pct", 52.2)), 1),
        "bmr_kcal": int(round(float(data.get("bmr_kcal", 1937)))),
        "created_at": get_now_wib().isoformat()
    }
    _, doc_ref = db.collection("body_composition").add(payload)
    payload["doc_id"] = doc_ref.id
    return payload

def get_body_composition_logs() -> list[dict]:
    db = get_db()
    docs = db.collection("body_composition").stream()
    items = [{"doc_id": d.id, **d.to_dict()} for d in docs]
    # Urutkan presisi berdasarkan tanggal DAN waktu pembuatan (created_at)
    return sorted(items, key=lambda x: (x.get("date", ""), x.get("created_at", "")))

# ==============================================================================
# 7. KOLEKSI 4: chat_sessions (Riwayat Tanya Bro PT)
# ==============================================================================
def add_chat_message(role: str, message: str) -> dict:
    db = get_db()
    payload = {
        "timestamp": get_now_wib().isoformat(),
        "date": get_today_str(),
        "role": role,
        "message": message
    }
    _, doc_ref = db.collection("chat_sessions").add(payload)
    payload["doc_id"] = doc_ref.id
    return payload

def get_chat_history(limit: int = 30) -> list[dict]:
    db = get_db()
    docs = db.collection("chat_sessions").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(limit).stream()
    items = [{"doc_id": d.id, **d.to_dict()} for d in docs]
    items.reverse()
    return items

# ==============================================================================
# 8. UPDATE & DELETE DOKUMEN
# ==============================================================================
def update_document(collection_name: str, doc_id: str, updated_fields: dict) -> dict:
    db = get_db()
    updated_fields.pop("doc_id", None)
    db.collection(collection_name).document(doc_id).update(updated_fields)
    return {"status": "updated", "doc_id": doc_id}

def delete_document(collection_name: str, doc_id: str) -> dict:
    db = get_db()
    db.collection(collection_name).document(doc_id).delete()
    return {"status": "deleted", "doc_id": doc_id}

# ==============================================================================
# 9. MESIN KALKULASI TUNGGAL (SINGLE SOURCE OF TRUTH: DASHBOARD & AI CHAT)
# ==============================================================================
def calculate_adaptive_targets(latest_body: dict) -> dict:
    """
    Menghitung target Kalori & Makro secara adaptif setiap kali ada data timbangan BIA baru.
    Pada baseline (BB 91.8 kg, BF 27.0%, BMR 1937 kcal):
    - Kalori Target = 2050 kcal
    - Protein Target = 170 g (~2.54g / kg Lean Body Mass)
    - Lemak Maksimal = 65 g (~0.71g / kg BB)
    - Karbohidrat = 190 g
    Saat BB dan BMR turun di minggu-minggu berikutnya, angka ini otomatis beradaptasi!
    """
    weight_kg = float(latest_body.get("weight_kg", 91.8))
    bf_pct = float(latest_body.get("body_fat_pct", 27.0))
    bmr_kcal = float(latest_body.get("bmr_kcal", 1937))

    lbm_kg = round(weight_kg * (1.0 - (bf_pct / 100.0)), 1)

    # Target kalori makan diset ~1.058 x BMR (agar tidak di bawah BMR, defisit murni diambil dari olahraga + NEAT)
    calories_target = int(round((bmr_kcal * 1.058) / 10.0) * 10)
    protein_g = int(round((lbm_kg * 2.54) / 5.0) * 5)
    fat_g = int(round((weight_kg * 0.71) / 5.0) * 5)

    # Sisa kalori dialokasikan ke karbohidrat kompleks/serat
    rem_kcal = max(400, calories_target - (protein_g * 4) - (fat_g * 9))
    carbs_g = int(round((rem_kcal / 4.0) / 5.0) * 5) - 5

    return {
        "lbm_kg": lbm_kg,
        "calories_target": calories_target,
        "protein_g": protein_g,
        "fat_g": fat_g,
        "carbs_g": carbs_g
    }

def get_daily_dashboard_summary(date_str: str = None) -> dict:
    target_date = date_str or get_today_str()
    now_wib = get_now_wib()
    profile = get_or_init_profile()

    nutri_logs = get_nutrition_logs(target_date)
    work_logs = get_workout_logs(target_date)
    body_logs = get_body_composition_logs()
    garmin_sync = get_garmin_daily_sync(target_date)

    # 1. Akumulasi Nutrisi Masuk
    cal_in = sum(int(item.get("calories", 0)) for item in nutri_logs)
    prot_g = round(sum(float(item.get("protein_g", 0.0)) for item in nutri_logs), 1)
    fat_g = round(sum(float(item.get("fat_g", 0.0)) for item in nutri_logs), 1)
    carbs_g = round(sum(float(item.get("carbs_g", 0.0)) for item in nutri_logs), 1)

    # 2. Akumulasi Sesi Olahraga Terstruktur (Workout Today)
    workout_active_kcal = sum(int(item.get("active_kcal", 0)) for item in work_logs)
    workout_total_kcal = sum(int(item.get("total_kcal", 0)) for item in work_logs)
    duration_min = sum(int(item.get("duration_min", 0)) for item in work_logs)

    # 3. Komposisi Tubuh & Indikator Delta Progres (▼ -kg)
    baseline_body = profile.get("baseline_2026_10_22", {})
    if body_logs:
        latest_body = body_logs[-1]
        first_body = body_logs[0]
        prev_body = body_logs[-2] if len(body_logs) >= 2 else first_body
    else:
        latest_body = baseline_body
        first_body = baseline_body
        prev_body = baseline_body

    body_deltas = {
        "weight_diff_start": round(float(latest_body.get("weight_kg", 91.8)) - float(first_body.get("weight_kg", 91.8)), 2),
        "weight_diff_prev": round(float(latest_body.get("weight_kg", 91.8)) - float(prev_body.get("weight_kg", 91.8)), 2),
        "vf_diff_start": round(float(latest_body.get("visceral_fat", 15.0)) - float(first_body.get("visceral_fat", 15.0)), 1),
        "bf_diff_start": round(float(latest_body.get("body_fat_pct", 27.0)) - float(first_body.get("body_fat_pct", 27.0)), 1),
        "total_weigh_ins": len(body_logs)
    }

    # 4. Target Makro Adaptif Otomatis
    adaptive_targets = calculate_adaptive_targets(latest_body)

    # 5. Perhitungan Dual-Metric Energy (Live Burn s.d Jam Ini vs Proyeksi 24 Jam)
    bmr_24h = int(latest_body.get("bmr_kcal", 1937))
    if target_date == get_today_str():
        elapsed_hours = round(now_wib.hour + (now_wib.minute / 60.0), 2)
    else:
        elapsed_hours = 24.0

    # BMR Berjalan s.d Jam Ini
    bmr_live = int(round((bmr_24h / 24.0) * elapsed_hours))

    # Estimasi NEAT Berjalan Otomatis (Jam bangun aktif 05:00 s.d 22:00 WIB = ~18 kcal/jam di luar durasi workout)
    HOURLY_NEAT_RATE = 18.0
    awake_elapsed = max(0.0, min(elapsed_hours, 22.0) - 5.0)
    workout_hours = duration_min / 60.0
    non_workout_awake_elapsed = max(0.0, awake_elapsed - workout_hours)
    auto_neat_live = int(round(non_workout_awake_elapsed * HOURLY_NEAT_RATE))

    # Cek apakah user melakukan Sync Kalori Aktif Harian dari Garmin Forerunner 55
    garmin_synced_active = int(garmin_sync.get("garmin_active_kcal", 0))
    if garmin_synced_active > 0:
        sync_hour = float(garmin_sync.get("sync_hour", elapsed_hours))
        workout_at_sync = int(garmin_sync.get("workout_kcal_at_sync", workout_active_kcal))
        # NEAT aktual Garmin saat jam sync dilakukan
        garmin_neat_at_sync = max(0, garmin_synced_active - workout_at_sync)
        # Tambahan NEAT setelah jam sync berjalan
        hours_after_sync = max(0.0, min(elapsed_hours, 22.0) - max(sync_hour, 5.0))
        post_sync_neat = int(round(hours_after_sync * HOURLY_NEAT_RATE))
        neat_live_kcal = max(auto_neat_live, garmin_neat_at_sync + post_sync_neat)
    else:
        neat_live_kcal = auto_neat_live

    total_active_live_kcal = workout_active_kcal + neat_live_kcal
    live_tdee_kcal = bmr_live + total_active_live_kcal
    live_deficit_kcal = live_tdee_kcal - cal_in

    # Proyeksi 24 Jam Penuh (Sampai 24:00 WIB)
    remaining_awake_hours = max(0.0, 22.0 - max(elapsed_hours, 5.0))
    projected_neat_24h_kcal = neat_live_kcal + int(round(remaining_awake_hours * HOURLY_NEAT_RATE))
    projected_active_24h_kcal = workout_active_kcal + projected_neat_24h_kcal
    projected_tdee_24h_kcal = bmr_24h + projected_active_24h_kcal
    projected_deficit_24h_kcal = projected_tdee_24h_kcal - cal_in

    energy_metrics = {
        "current_time_wib": now_wib.strftime("%H:%M"),
        "elapsed_hours": elapsed_hours,
        "bmr_24h": bmr_24h,
        "bmr_live": bmr_live,
        "workout_active_kcal": workout_active_kcal,
        "neat_live_kcal": neat_live_kcal,
        "total_active_live_kcal": total_active_live_kcal,
        "garmin_synced_active_kcal": garmin_synced_active,
        "garmin_sync_time": garmin_sync.get("sync_time", ""),
        "live_tdee_kcal": live_tdee_kcal,
        "live_deficit_kcal": live_deficit_kcal,
        "projected_neat_24h_kcal": projected_neat_24h_kcal,
        "projected_active_24h_kcal": projected_active_24h_kcal,
        "projected_tdee_24h_kcal": projected_tdee_24h_kcal,
        "projected_deficit_24h_kcal": projected_deficit_24h_kcal
    }

    return {
        "date": target_date,
        "profile": profile,
        "latest_body": latest_body,
        "baseline_body": first_body,
        "body_deltas": body_deltas,
        "adaptive_targets": adaptive_targets,
        "energy": energy_metrics,
        # Aliases untuk kompatibilitas penuh
        "real_tdee_today": live_tdee_kcal,
        "net_deficit": projected_deficit_24h_kcal,
        "nutrition": {
            "calories_in": cal_in,
            "protein_g": prot_g,
            "fat_g": fat_g,
            "carbs_g": carbs_g,
            "logs": nutri_logs
        },
        "workout": {
            "active_kcal": workout_active_kcal,
            "total_kcal": workout_total_kcal,
            "duration_min": duration_min,
            "logs": work_logs
        }
    }
