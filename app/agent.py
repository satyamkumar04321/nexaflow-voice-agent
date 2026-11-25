import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .config import settings
from .crm import book_appointment, find_existing_lead, get_available_slots, log_activity, upsert_lead
from .database import db_session
from .nlu import (
    analyze_sentiment,
    detect_intent,
    detect_language,
    detect_objections,
    extract_bant_updates,
    extract_booking_details,
    score_lead,
)
from .rag import KnowledgeBaseRAG
from .schemas import BANTState, RAGChunk, TurnResponse

try:
    from google import genai
except Exception:
    genai = None


GREETINGS = {
    "en": "Hi! I'm Maya from NexaFlow Cloud. Thanks for hopping on — what workflow or sales automation challenge are you looking to solve?",
    "hi": "Namaste! Main Maya hoon NexaFlow Cloud se. Batayein, aapki team customer support ya sales automation mein kis challenge ko solve karna chahti hai?",
    "es": "¡Hola! Soy Maya de NexaFlow Cloud. Gracias por conectarte — ¿qué proceso de soporte o ventas te gustaría automatizar?",
}


class SalesVoiceAgent:
    def __init__(self, rag: KnowledgeBaseRAG):
        self.rag = rag
        self._gemini_client = None
        if settings.gemini_api_key and genai is not None:
            try:
                self._gemini_client = genai.Client(api_key=settings.gemini_api_key)
            except Exception:
                self._gemini_client = None

    def start_call(
        self,
        prospect_name: Optional[str] = None,
        prospect_email: Optional[str] = None,
        company: Optional[str] = None,
        language: str = "auto",
    ) -> Dict[str, Any]:
        call_id = f"call-{uuid.uuid4().hex[:10]}"
        lang = "en" if language == "auto" else language.split("-")[0].lower()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        existing_lead = find_existing_lead(email=prospect_email, company=company)
        bant = BANTState(
            contact_name=prospect_name or (existing_lead["name"] if existing_lead else None),
            contact_email=prospect_email or (existing_lead["email"] if existing_lead else None),
            company=company or (existing_lead["company"] if existing_lead else None),
            team_size=existing_lead["team_size"] if existing_lead else None,
            budget=existing_lead["budget"] if existing_lead else None,
            authority=existing_lead["authority"] if existing_lead else None,
            need=existing_lead["need"] if existing_lead else None,
            timeline=existing_lead["timeline"] if existing_lead else None,
        )

        lead_id = existing_lead["id"] if existing_lead else None
        init_score, init_tier = score_lead(bant, 0.0, "greeting")

        if existing_lead and existing_lead.get("name"):
            greeting = (
                f"Welcome back {existing_lead['name']}! I see our earlier notes for {existing_lead.get('company') or 'your team'}. "
                "Would you like to continue where we left off or look at scheduling a live demo?"
            )
        else:
            greeting = GREETINGS.get(lang, GREETINGS["en"])

        with db_session() as conn:
            conn.execute(
                """
                INSERT INTO calls (
                    id, lead_id, language, status, bant_json,
                    qualification_score, qualification_tier,
                    sentiment_score, sentiment_label, objections_json, started_at
                )
                VALUES (?, ?, ?, 'active', ?, ?, ?, 0.0, 'Neutral', '[]', ?)
                """,
                (call_id, lead_id, lang, json.dumps(bant.model_dump()), init_score, init_tier, now),
            )
            conn.execute(
                """
                INSERT INTO turns (call_id, speaker, text, language, intent, sentiment_score, sentiment_label, created_at)
                VALUES (?, 'agent', ?, ?, 'greeting', 0.2, 'Positive', ?)
                """,
                (call_id, greeting, lang, now),
            )

        return {
            "call_id": call_id,
            "greeting": greeting,
            "language": lang,
            "bant": bant.model_dump(),
            "qualification_score": init_score,
            "qualification_tier": init_tier,
            "returning_lead": bool(existing_lead),
            "available_slots": get_available_slots(days=3)[:6],
        }

    def process_turn(self, call_id: str, user_text: str, language_hint: str = "auto") -> TurnResponse:
        t0 = time.perf_counter()

        with db_session() as conn:
            call = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
            if not call:
                raise ValueError(f"Unknown call_id: {call_id}")
            history_rows = conn.execute(
                "SELECT speaker, text, sentiment_score FROM turns WHERE call_id = ? ORDER BY id DESC LIMIT 8",
                (call_id,),
            ).fetchall()

        history = [dict(r) for r in reversed(history_rows)]
        bant = BANTState(**json.loads(call["bant_json"] or "{}"))
        existing_objections: List[str] = json.loads(call["objections_json"] or "[]")

        lang = detect_language(user_text, hint=language_hint)
        sentiment_score, sentiment_label = analyze_sentiment(user_text)
        intent = detect_intent(user_text)
        new_objections = detect_objections(user_text)
        merged_objections = list(dict.fromkeys(existing_objections + new_objections))

        bant = extract_bant_updates(user_text, bant)
        qual_score, qual_tier = score_lead(bant, sentiment_score, intent, text=user_text)

        rag_chunks = self.rag.retrieve(user_text, top_k=3)

        # Sync lead into CRM on every meaningful turn.
        prev_scores = [h["sentiment_score"] for h in history] + [sentiment_score]
        avg_sent = sum(prev_scores) / len(prev_scores)
        lead_id = upsert_lead(bant, lang, qual_score, avg_sent, call_id=call_id)

        appointment = None
        if intent == "confirm_booking" or (intent == "booking_request" and bant.contact_email):
            booking_bits = extract_booking_details(user_text)
            if booking_bits["slot_date"] or booking_bits["slot_time"] or bant.contact_email:
                appointment = book_appointment(
                    prospect_name=bant.contact_name or "Valued Prospect",
                    prospect_email=bant.contact_email or "prospect@company.example",
                    slot_date=booking_bits["slot_date"],
                    slot_time=booking_bits["slot_time"],
                    company=bant.company or "",
                    call_id=call_id,
                    lead_id=lead_id,
                )

        llm_mode = "local"
        reply = None
        if self._gemini_client is not None:
            reply = self._gemini_reply(
                user_text=user_text,
                lang=lang,
                history=history,
                bant=bant,
                qual_score=qual_score,
                rag_chunks=rag_chunks,
                appointment=appointment,
            )
            if reply:
                llm_mode = f"gemini:{settings.gemini_model}"

        if not reply:
            reply = self._local_reply(
                user_text=user_text,
                lang=lang,
                intent=intent,
                bant=bant,
                qual_score=qual_score,
                objections=new_objections,
                rag_chunks=rag_chunks,
                appointment=appointment,
            )

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        latency_ms = int((time.perf_counter() - t0) * 1000)

        with db_session() as conn:
            conn.execute(
                """
                INSERT INTO turns (call_id, speaker, text, language, intent, sentiment_score, sentiment_label, rag_sources_json, latency_ms, created_at)
                VALUES (?, 'user', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call_id,
                    user_text,
                    lang,
                    intent,
                    sentiment_score,
                    sentiment_label,
                    json.dumps([c.model_dump() for c in rag_chunks]),
                    latency_ms,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO turns (call_id, speaker, text, language, intent, sentiment_score, sentiment_label, created_at)
                VALUES (?, 'agent', ?, ?, 'agent_reply', 0.25, 'Positive', ?)
                """,
                (call_id, reply, lang, now),
            )
            conn.execute(
                """
                UPDATE calls
                SET lead_id = ?,
                    language = ?,
                    bant_json = ?,
                    qualification_score = ?,
                    qualification_tier = ?,
                    sentiment_score = ?,
                    sentiment_label = ?,
                    objections_json = ?
                WHERE id = ?
                """,
                (
                    lead_id,
                    lang,
                    json.dumps(bant.model_dump()),
                    qual_score,
                    qual_tier,
                    round(avg_sent, 2),
                    sentiment_label,
                    json.dumps(merged_objections),
                    call_id,
                ),
            )

        if new_objections:
            log_activity(lead_id, "objection_noted", f"Objection detected: {', '.join(new_objections)}", call_id=call_id)

        return TurnResponse(
            call_id=call_id,
            reply=reply,
            language=lang,
            intent=intent,
            sentiment_score=sentiment_score,
            sentiment_label=sentiment_label,
            qualification_score=qual_score,
            qualification_tier=qual_tier,
            bant=bant,
            objections=merged_objections,
            rag_chunks=rag_chunks,
            appointment=appointment,
            crm_synced=True,
            latency_ms=latency_ms,
            llm_mode=llm_mode,
        )

    def _gemini_reply(
        self,
        user_text: str,
        lang: str,
        history: List[Dict[str, Any]],
        bant: BANTState,
        qual_score: int,
        rag_chunks: List[RAGChunk],
        appointment: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        lang_name = {"hi": "Hindi (or natural Hinglish matching the user)", "es": "Spanish"}.get(lang, "English")
        context_block = "\n".join(f"- [{c.title} / {c.section}]: {c.content}" for c in rag_chunks) or "No specific KB snippet matched."
        history_block = "\n".join(f"{h['speaker'].upper()}: {h['text']}" for h in history[-6:])

        missing = [k for k in ("need", "team_size", "budget", "timeline") if not getattr(bant, k)]
        next_goal = (
            f"Confirm the booked demo on {appointment['slot_date']} at {appointment['slot_time']}."
            if appointment
            else (f"Politely ask about {missing[0].replace('_', ' ')}." if missing else "Propose booking a 15-minute live demo.")
        )

        prompt = (
            "You are Maya, a concise, helpful B2B AI sales voice specialist for NexaFlow Cloud.\n"
            f"Respond in {lang_name}. Keep the response natural for voice TTS (2 to 3 short sentences, no markdown bullets).\n"
            "Ground all pricing, security, and integration facts strictly in the Knowledge Base context below.\n\n"
            f"Knowledge Base:\n{context_block}\n\n"
            f"Known Lead BANT (Score {qual_score}/100): {json.dumps(bant.model_dump())}\n"
            f"Next conversational goal: {next_goal}\n\n"
            f"Recent dialogue:\n{history_block}\n"
            f"USER: {user_text}\n"
            "MAYA:"
        )
        try:
            resp = self._gemini_client.models.generate_content(model=settings.gemini_model, contents=prompt)
            text = (resp.text or "").strip()
            return text if text else None
        except Exception:
            return None

    def _local_reply(
        self,
        user_text: str,
        lang: str,
        intent: str,
        bant: BANTState,
        qual_score: int,
        objections: List[str],
        rag_chunks: List[RAGChunk],
        appointment: Optional[Dict[str, Any]],
    ) -> str:
        if appointment:
            date_s, time_s = appointment["slot_date"], appointment["slot_time"]
            if lang == "hi":
                return (
                    f"Done! Maine aapka demo {date_s} ko {time_s} par confirm kar diya hai aur CRM mein update kar diya hai. "
                    f"Calendar invite aur meeting link {appointment['prospect_email']} par bhej diya gaya hai."
                )
            if lang == "es":
                return (
                    f"¡Listo! Tu demo quedó confirmada para el {date_s} a las {time_s} y registrada en nuestro CRM. "
                    f"Enviamos el enlace de la reunión a {appointment['prospect_email']}."
                )
            return (
                f"You're all set — I've booked your demo for {date_s} at {time_s} and synced everything to our CRM. "
                f"Your invite and meeting link have been sent to {appointment['prospect_email']}."
            )

        if intent == "wrap_up":
            if lang == "hi":
                return "Dhanyawad baat karne ke liye! Main is call ka summary aur next steps aapko email par bhej rahi hoon."
            if lang == "es":
                return "¡Muchas gracias por tu tiempo! Te enviaré el resumen de la llamada y los próximos pasos por correo."
            return "Thanks for your time today! I'll wrap up the call summary and send our next steps straight to your inbox."

        # Pull concise grounded facts from top RAG chunk when available.
        fact = ""
        if rag_chunks:
            top = rag_chunks[0]
            first_bullets = [line.lstrip("-* ").replace("**", "") for line in top.content.splitlines() if line.strip()]
            if first_bullets:
                fact = " ".join(first_bullets[:2])

        if intent == "booking_request":
            slots = get_available_slots(days=3)[:2]
            slot_hint = " or ".join(s["label"] for s in slots) if slots else "tomorrow at 11:30"
            if lang == "hi":
                return f"Bilkul, hum ek 15-minute live demo rakh sakte hain. Mere paas {slot_hint} khali hai — kaunsa slot aur email ID use karein?"
            if lang == "es":
                return f"Con gusto agendamos una demo de 15 minutos. Tengo disponibilidad {slot_hint} — ¿qué horario y correo prefieres?"
            return f"I'd be happy to set up a 15-minute live demo. I have {slot_hint} open — which works best, and what email should I send the invite to?"

        if objections:
            if "Pricing / Budget" in objections:
                if lang == "hi":
                    return (
                        f"Main aapki budget concern samajhti hoon. {fact or 'Starter plan $49/seat se shuru hota hai aur 50+ seats par 15% annual discount milta hai.'} "
                        "Aapki team mein kitne users honge?"
                    )
                return (
                    f"Totally fair to watch budget closely. {fact or 'Our Starter plan starts at $49/seat, and Growth offers a 15% discount on 50+ annual seats plus a 14-day free trial.'} "
                    "Roughly how many seats would your team need?"
                )
            if "Data Security & Compliance" in objections:
                return (
                    f"Security is core to our architecture: {fact or 'we use TLS 1.3, AES-256 encryption, SOC 2 Type II, and zero-retention LLM inference with India/EU/US residency.'} "
                    "Would a security compliance pack help your IT review?"
                )

        if rag_chunks and intent in ("pricing_inquiry", "product_question"):
            follow_q = self._next_discovery_question(bant, lang)
            if lang == "hi":
                return f"Zaroor! Hamari knowledge base ke hisaab se: {fact} {follow_q}"
            if lang == "es":
                return f"Claro, según nuestra documentación: {fact} {follow_q}"
            return f"Sure — here is what we offer: {fact} {follow_q}"

        if intent == "greeting":
            return GREETINGS.get(lang, GREETINGS["en"])

        # Discovery / BANT progression
        follow_q = self._next_discovery_question(bant, lang)
        if qual_score >= 65 and not appointment:
            slots = get_available_slots(days=3)[:2]
            slot_hint = " or ".join(s["label"] for s in slots) if slots else "tomorrow at 10:00"
            if lang == "hi":
                return f"Bahut badhiya, aapki requirements Growth plan ke saath bilkul fit baith-ti hain. Kya hum {slot_hint} par ek quick demo book karein?"
            return f"Got it — based on your setup, NexaFlow Growth looks like a strong fit. Would you like to lock in a 15-minute demo for {slot_hint}?"

        if lang == "hi":
            return f"Samajh gayi, maine yeh note kar liya hai. {follow_q}"
        if lang == "es":
            return f"Entendido, lo tengo anotado. {follow_q}"
        return f"Got it, thanks for sharing that. {follow_q}"

    def _next_discovery_question(self, bant: BANTState, lang: str) -> str:
        if not bant.need:
            return {
                "hi": "Aap abhi kaunse manual tasks automate karna chahte hain?",
                "es": "¿Qué tareas manuales te gustaría automatizar primero?",
            }.get(lang, "What is the main bottleneck your team is trying to automate right now?")
        if not bant.team_size:
            return {
                "hi": "Aapki sales ya support team mein kitne members hain?",
                "es": "¿Cuántas personas hay en tu equipo actualmente?",
            }.get(lang, "How many team members or seats would be using the platform?")
        if not bant.timeline:
            return {
                "hi": "Aap is solution ko kab tak live karne ka plan kar rahe hain?",
                "es": "¿Para cuándo planean implementar esta solución?",
            }.get(lang, "What timeline are you targeting to go live?")
        if not bant.budget:
            return {
                "hi": "Kya aapne is quarter ke liye koi monthly budget range decide ki hai?",
                "es": "¿Tienen un presupuesto mensual estimado para este proyecto?",
            }.get(lang, "Do you have an estimated monthly budget range allocated for this?")
        if not bant.contact_email:
            return {
                "hi": "Demo invite bhejne ke liye aapka work email kya hoga?",
                "es": "¿Cuál es tu correo de trabajo para enviarte la invitación?",
            }.get(lang, "What's the best work email to send a tailored walkthrough and demo invite?")
        return "Would you like me to book a quick demo slot for you?"
