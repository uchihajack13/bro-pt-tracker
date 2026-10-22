import os
from typing import Optional
import uvicorn
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

import firestore_db as db
import gemini_engine as ai

app = FastAPI(title="Bro PT - Personal Trainer & Nutrition Tracker")

# Pastikan folder static tersedia
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ==============================================================================
# MODEL REQUEST BODY
# ==============================================================================
class FastingModeRequest(BaseModel):
    mode: str

class TextLogRequest(BaseModel):
    text: str

class GarminSyncRequest(BaseModel):
    active_kcal: int
    resting_kcal: Optional[int] = 0
    total_kcal: Optional[int] = 0

class UpdateDocRequest(BaseModel):
    fields: dict

# ==============================================================================
# ROUTING HALAMAN UTAMA & PWA MANIFEST
# ==============================================================================
@app.get("/")
async def serve_home():
    return FileResponse("static/index.html")

@app.get("/manifest.json")
async def serve_manifest():
    return FileResponse("static/manifest.json")

# ==============================================================================
# API TAB 1: MINI DASHBOARD HARIAN & QUICK SYNC GARMIN
# ==============================================================================
@app.get("/api/dashboard")
async def get_dashboard(date: Optional[str] = None):
    try:
        summary = db.get_daily_dashboard_summary(date)
        return {"status": "ok", "data": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/fasting-mode")
async def set_fasting_mode(req: FastingModeRequest):
    try:
        res = db.update_fasting_mode(req.mode)
        return {"status": "ok", "data": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/garmin-sync")
async def sync_garmin_active(req: GarminSyncRequest):
    """
    Sinkronisasi cepat angka 'Kalori Aktif' dari Garmin Forerunner 55
    tanpa menyebabkan double-counting dengan log latihan.
    """
    try:
        saved = db.sync_garmin_daily_active(
            active_kcal=req.active_kcal,
            resting_kcal=req.resting_kcal or 0,
            total_kcal=req.total_kcal or 0
        )
        summary = db.get_daily_dashboard_summary()
        return {"status": "ok", "synced": saved, "data": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==============================================================================
# API TAB 2: SMART VISION SCANNER & AUTO-LOGGER (4-IN-1)
# ==============================================================================
@app.post("/api/scan-image")
async def scan_image(
    file: UploadFile = File(...),
    note: str = Form("")
):
    try:
        image_bytes = await file.read()
        mime_type = file.content_type or "image/jpeg"
        daily_summary = db.get_daily_dashboard_summary()

        ai_result = ai.analyze_image_and_extract(
            image_bytes=image_bytes,
            mime_type=mime_type,
            user_note=note,
            daily_summary=daily_summary
        )

        saved_record = None
        scan_type = ai_result.get("scan_type")

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

        return {
            "status": "ok",
            "scan_type": scan_type,
            "coach_evaluation": ai_result.get("coach_evaluation", ""),
            "extracted_data": (
                ai_result.get("nutrition_data")
                or ai_result.get("workout_data")
                or ai_result.get("garmin_summary_data")
                or ai_result.get("body_data")
            ),
            "saved_record": saved_record
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/log-text")
async def log_by_text(req: TextLogRequest):
    try:
        daily_summary = db.get_daily_dashboard_summary()
        ai_result = ai.analyze_text_log_and_extract(req.text, daily_summary)

        saved_record = None
        scan_type = ai_result.get("scan_type")

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

        return {
            "status": "ok",
            "scan_type": scan_type,
            "coach_evaluation": ai_result.get("coach_evaluation", ""),
            "extracted_data": (
                ai_result.get("nutrition_data")
                or ai_result.get("workout_data")
                or ai_result.get("garmin_summary_data")
                or ai_result.get("body_data")
            ),
            "saved_record": saved_record
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==============================================================================
# API TAB 3: TANYA BRO PT (MULTIMODAL & SINGLE SOURCE OF TRUTH)
# ==============================================================================
@app.get("/api/chat")
async def get_chats():
    try:
        history = db.get_chat_history(limit=40)
        return {"status": "ok", "history": history}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def send_chat(
    message: str = Form(""),
    file: Optional[UploadFile] = File(None)
):
    try:
        daily_summary = db.get_daily_dashboard_summary()
        history = db.get_chat_history(limit=15)

        image_bytes = None
        mime_type = "image/jpeg"
        if file and file.filename:
            image_bytes = await file.read()
            mime_type = file.content_type or "image/jpeg"

        user_log_msg = f"[📷 Foto] {message}".strip() if image_bytes else message
        if not user_log_msg:
            user_log_msg = "[📷 Mengirim Foto untuk Dikritisi]"

        db.add_chat_message("user", user_log_msg)

        reply = ai.chat_with_bro_pt(
            user_message=message,
            daily_summary=daily_summary,
            chat_history=history,
            image_bytes=image_bytes,
            mime_type=mime_type
        )
        db.add_chat_message("model", reply)

        return {"status": "ok", "reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==============================================================================
# API TAB 4: ANALITIK TREN & DATA EDITOR INTERAKTIF
# ==============================================================================
@app.get("/api/analytics")
async def get_analytics_data():
    try:
        body_logs = db.get_body_composition_logs()
        nutri_logs = db.get_nutrition_logs(limit=100)
        workout_logs = db.get_workout_logs(limit=60)
        return {
            "status": "ok",
            "body_composition": body_logs,
            "daily_nutrition": nutri_logs,
            "workout_logs": workout_logs
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/document/{collection}/{doc_id}")
async def update_doc(collection: str, doc_id: str, req: UpdateDocRequest):
    allowed = {"daily_nutrition", "workout_logs", "body_composition"}
    if collection not in allowed:
        raise HTTPException(status_code=400, detail="Koleksi tidak valid.")
    try:
        res = db.update_document(collection, doc_id, req.fields)
        return {"status": "ok", "data": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/document/{collection}/{doc_id}")
async def delete_doc(collection: str, doc_id: str):
    allowed = {"daily_nutrition", "workout_logs", "body_composition"}
    if collection not in allowed:
        raise HTTPException(status_code=400, detail="Koleksi tidak valid.")
    try:
        res = db.delete_document(collection, doc_id)
        return {"status": "ok", "data": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==============================================================================
# JALANKAN SERVER LOKAL
# ==============================================================================
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
