import json
import os
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .agent import SalesVoiceAgent
from .config import settings
from .crm import (
    book_appointment,
    build_call_summary,
    get_available_slots,
    get_business_insights,
    list_appointments,
    list_leads,
    update_lead_stage,
)
from .database import db_session, init_db
from .rag import KnowledgeBaseRAG
from .schemas import BookSlotRequest, KnowledgeDocRequest, StartCallRequest, TurnRequest

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

init_db()
rag_engine = KnowledgeBaseRAG()
voice_agent = SalesVoiceAgent(rag=rag_engine)

app = FastAPI(title="NexaFlow Autonomous Sales Voice Agent", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def serve_ui():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "kb_chunks": len(rag_engine.chunks),
        "llm_provider": f"gemini:{settings.gemini_model}" if settings.gemini_api_key else "local-nlp",
    }


@app.post("/api/calls")
def start_call(req: StartCallRequest):
    return voice_agent.start_call(
        prospect_name=req.prospect_name,
        prospect_email=req.prospect_email,
        company=req.company,
        language=req.language,
    )


@app.get("/api/calls/{call_id}")
def get_call(call_id: str):
    with db_session() as conn:
        call = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
        if not call:
            raise HTTPException(status_code=404, detail="Call not found")
        turns = conn.execute("SELECT * FROM turns WHERE call_id = ? ORDER BY id ASC", (call_id,)).fetchall()

    call_dict = dict(call)
    call_dict["bant"] = json.loads(call_dict.pop("bant_json") or "{}")
    call_dict["objections"] = json.loads(call_dict.pop("objections_json") or "[]")
    call_dict["turns"] = [dict(t) for t in turns]
    return call_dict


@app.post("/api/calls/{call_id}/turn")
def post_turn(call_id: str, req: TurnRequest):
    try:
        return voice_agent.process_turn(call_id, req.text, language_hint=req.language)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/calls/{call_id}/end")
def end_call(call_id: str):
    try:
        return build_call_summary(call_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/calendar/slots")
def available_slots(days: int = 5):
    return {"slots": get_available_slots(days=days)}


@app.post("/api/calendar/book")
def create_booking(req: BookSlotRequest):
    try:
        return book_appointment(
            prospect_name=req.prospect_name,
            prospect_email=req.prospect_email,
            slot_date=req.slot_date,
            slot_time=req.slot_time,
            company=req.company,
            topic=req.topic,
            call_id=req.call_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/crm/leads")
def crm_leads():
    return {"leads": list_leads()}


@app.patch("/api/crm/leads/{lead_id}")
def patch_lead(lead_id: int, payload: dict):
    stage = payload.get("stage")
    if not stage:
        raise HTTPException(status_code=400, detail="Missing stage")
    updated = update_lead_stage(lead_id, stage, payload.get("notes"))
    if not updated:
        raise HTTPException(status_code=404, detail="Lead not found")
    return updated


@app.get("/api/crm/appointments")
def crm_appointments():
    return {"appointments": list_appointments()}


@app.get("/api/insights")
def insights():
    return get_business_insights()


@app.get("/api/kb")
def list_kb_chunks():
    return {"chunks": [c.model_dump() for c in rag_engine.chunks]}


@app.post("/api/kb")
def add_kb_doc(req: KnowledgeDocRequest):
    count = rag_engine.add_document(req.filename, req.content)
    return {"status": "indexed", "total_chunks": count}


@app.websocket("/ws/call/{call_id}")
async def voice_ws(websocket: WebSocket, call_id: str):
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type == "transcript":
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                language = msg.get("language", "auto")
                await websocket.send_json({"type": "status", "state": "thinking"})
                result = voice_agent.process_turn(call_id, text, language_hint=language)
                await websocket.send_json({"type": "response", "data": result.model_dump()})
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
