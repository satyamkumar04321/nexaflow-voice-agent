import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import urllib.request

from .config import settings
from .database import db_session
from .nlu import is_valid_email
from .schemas import BANTState


DEFAULT_TIME_SLOTS = ["10:00", "11:30", "14:00", "15:30", "17:00"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def find_existing_lead(email: Optional[str] = None, company: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not email and not company:
        return None
    with db_session() as conn:
        if email:
            row = conn.execute("SELECT * FROM leads WHERE lower(email) = lower(?) LIMIT 1", (email,)).fetchone()
            if row:
                return dict(row)
        if company:
            row = conn.execute("SELECT * FROM leads WHERE lower(company) = lower(?) LIMIT 1", (company,)).fetchone()
            if row:
                return dict(row)
    return None


def upsert_lead(
    bant: BANTState,
    language: str,
    qualification_score: int,
    sentiment_avg: float,
    call_id: Optional[str] = None,
    stage: Optional[str] = None,
) -> int:
    now = _now_iso()
    existing = find_existing_lead(email=bant.contact_email, company=bant.company)

    if not stage:
        if qualification_score >= 70:
            stage = "Qualified"
        elif qualification_score >= 40:
            stage = "Discovery"
        else:
            stage = "New"

    with db_session() as conn:
        if existing:
            lead_id = existing["id"]
            conn.execute(
                """
                UPDATE leads
                SET name = COALESCE(?, name),
                    email = COALESCE(?, email),
                    company = COALESCE(?, company),
                    team_size = COALESCE(?, team_size),
                    language = ?,
                    budget = COALESCE(?, budget),
                    authority = COALESCE(?, authority),
                    need = COALESCE(?, need),
                    timeline = COALESCE(?, timeline),
                    qualification_score = MAX(qualification_score, ?),
                    stage = ?,
                    sentiment_avg = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    bant.contact_name,
                    bant.contact_email,
                    bant.company,
                    bant.team_size,
                    language,
                    bant.budget,
                    bant.authority,
                    bant.need,
                    bant.timeline,
                    qualification_score,
                    stage,
                    round(sentiment_avg, 2),
                    now,
                    lead_id,
                ),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO leads (
                    name, email, company, team_size, language,
                    budget, authority, need, timeline,
                    qualification_score, stage, sentiment_avg,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bant.contact_name or "Unknown Prospect",
                    bant.contact_email,
                    bant.company,
                    bant.team_size,
                    language,
                    bant.budget,
                    bant.authority,
                    bant.need,
                    bant.timeline,
                    qualification_score,
                    stage,
                    round(sentiment_avg, 2),
                    now,
                    now,
                ),
            )
            lead_id = cur.lastrowid

        if call_id:
            conn.execute("UPDATE calls SET lead_id = ? WHERE id = ?", (lead_id, call_id))

    return int(lead_id)


def log_activity(lead_id: int, activity_type: str, detail: str, call_id: Optional[str] = None) -> None:
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO crm_activities (lead_id, call_id, activity_type, detail, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (lead_id, call_id, activity_type, detail, _now_iso()),
        )


def get_available_slots(days: int = 5) -> List[Dict[str, str]]:
    with db_session() as conn:
        rows = conn.execute("SELECT slot_date, slot_time FROM appointments WHERE status = 'confirmed'").fetchall()
    booked = {(r["slot_date"], r["slot_time"]) for r in rows}

    slots: List[Dict[str, str]] = []
    cursor = datetime.now().date() + timedelta(days=1)
    added_days = 0
    while added_days < days:
        if cursor.weekday() < 5:
            date_str = cursor.isoformat()
            for t in DEFAULT_TIME_SLOTS:
                if (date_str, t) not in booked:
                    slots.append({"slot_date": date_str, "slot_time": t, "label": f"{date_str} at {t}"})
            added_days += 1
        cursor += timedelta(days=1)
    return slots


def _push_webhook(event: str, payload: Dict[str, Any]) -> bool:
    if not settings.crm_webhook_url:
        return False
    try:
        req = urllib.request.Request(
            settings.crm_webhook_url,
            data=json.dumps({"event": event, "data": payload}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3.0):
            return True
    except Exception:
        return False


def book_appointment(
    prospect_name: str,
    prospect_email: str,
    slot_date: Optional[str],
    slot_time: Optional[str],
    company: str = "",
    topic: str = "NexaFlow Product Demo",
    call_id: Optional[str] = None,
    lead_id: Optional[int] = None,
) -> Dict[str, Any]:
    prospect_email = (prospect_email or "").strip().rstrip(".,!?;:")
    if not is_valid_email(prospect_email):
        raise ValueError(f"Invalid prospect email address: {prospect_email}")

    available = get_available_slots(days=5)
    if not slot_date or not slot_time:
        if not available:
            raise ValueError("No open calendar slots available.")
        chosen = available[0]
        slot_date = slot_date or chosen["slot_date"]
        slot_time = slot_time or chosen["slot_time"]

    # Snap requested time to nearest valid slot if the exact time is already booked.
    available_pairs = {(s["slot_date"], s["slot_time"]) for s in available}
    if (slot_date, slot_time) not in available_pairs:
        same_day = [s for s in available if s["slot_date"] == slot_date]
        if same_day:
            slot_time = same_day[0]["slot_time"]
        elif available:
            slot_date = available[0]["slot_date"]
            slot_time = available[0]["slot_time"]

    meeting_link = f"https://meet.nexaflow.example/demo-{uuid.uuid4().hex[:8]}"
    now = _now_iso()

    with db_session() as conn:
        if lead_id is None:
            bant = BANTState(contact_name=prospect_name, contact_email=prospect_email, company=company or None)
            lead_id = upsert_lead(bant, "en", 75, 0.5, call_id=call_id, stage="Demo Booked")
        else:
            conn.execute(
                "UPDATE leads SET stage = 'Demo Booked', name = COALESCE(?, name), email = COALESCE(?, email), updated_at = ? WHERE id = ?",
                (prospect_name, prospect_email, now, lead_id),
            )

        cur = conn.execute(
            """
            INSERT INTO appointments (
                call_id, lead_id, prospect_name, prospect_email, company,
                slot_date, slot_time, topic, meeting_link, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?)
            """,
            (call_id, lead_id, prospect_name, prospect_email, company, slot_date, slot_time, topic, meeting_link, now),
        )
        appt_id = cur.lastrowid

    log_activity(lead_id, "appointment_booked", f"Demo scheduled for {slot_date} {slot_time} ({meeting_link})", call_id=call_id)

    record = {
        "id": appt_id,
        "lead_id": lead_id,
        "prospect_name": prospect_name,
        "prospect_email": prospect_email,
        "company": company,
        "slot_date": slot_date,
        "slot_time": slot_time,
        "topic": topic,
        "meeting_link": meeting_link,
        "status": "confirmed",
    }
    _push_webhook("appointment.booked", record)
    return record


def list_leads() -> List[Dict[str, Any]]:
    with db_session() as conn:
        rows = conn.execute("SELECT * FROM leads ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]


def update_lead_stage(lead_id: int, stage: str, notes: Optional[str] = None) -> Optional[Dict[str, Any]]:
    now = _now_iso()
    with db_session() as conn:
        if notes is not None:
            conn.execute("UPDATE leads SET stage = ?, notes = ?, updated_at = ? WHERE id = ?", (stage, notes, now, lead_id))
        else:
            conn.execute("UPDATE leads SET stage = ?, updated_at = ? WHERE id = ?", (stage, now, lead_id))
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return dict(row) if row else None


def list_appointments() -> List[Dict[str, Any]]:
    with db_session() as conn:
        rows = conn.execute("SELECT * FROM appointments ORDER BY slot_date ASC, slot_time ASC").fetchall()
        return [dict(r) for r in rows]


def build_call_summary(call_id: str) -> Dict[str, Any]:
    with db_session() as conn:
        call = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
        if not call:
            raise ValueError("Call not found")
        turns = conn.execute("SELECT * FROM turns WHERE call_id = ? ORDER BY id ASC", (call_id,)).fetchall()
        appt = conn.execute("SELECT * FROM appointments WHERE call_id = ? LIMIT 1", (call_id,)).fetchone()

    bant = json.loads(call["bant_json"] or "{}")
    objections = json.loads(call["objections_json"] or "[]")
    user_turns = [t["text"] for t in turns if t["speaker"] == "user"]
    sentiments = [t["sentiment_score"] for t in turns if t["speaker"] == "user"]
    avg_sentiment = round(sum(sentiments) / len(sentiments), 2) if sentiments else 0.0

    name = bant.get("contact_name") or "the prospect"
    company = bant.get("company") or "their organization"
    need = bant.get("need") or "workflow and support automation"
    team = bant.get("team_size") or "unspecified team size"

    summary_parts = [
        f"Spoke with {name} from {company} ({team}) in {call['language'].upper()}.",
        f"Primary focus: {need}.",
        f"Qualification score reached {call['qualification_score']}/100 ({call['qualification_tier']}).",
    ]
    if objections:
        summary_parts.append(f"Raised concerns around: {', '.join(objections)}.")
    if appt:
        summary_parts.append(f"Demo booked for {appt['slot_date']} at {appt['slot_time']}.")

    summary_text = " ".join(summary_parts)

    if appt:
        next_action = f"Send calendar prep deck & architecture brief before {appt['slot_date']} {appt['slot_time']}."
    elif call["qualification_score"] >= 70:
        next_action = "High-intent SQL: follow up within 2 hours with Growth/Enterprise proposal and calendar link."
    elif call["qualification_score"] >= 40:
        next_action = "Send tailored ROI case study and follow up in 2 days to confirm timeline."
    else:
        next_action = "Add to nurture sequence with product overview."

    followup_email = (
        f"Subject: NexaFlow Cloud — Quick recap & next steps\n\n"
        f"Hi {bant.get('contact_name') or 'there'},\n\n"
        f"Thanks for speaking with us today about {need}. "
        + (f"Your demo is confirmed for {appt['slot_date']} at {appt['slot_time']} ({appt['meeting_link']}).\n\n" if appt else "I've attached our pricing and security brief for your review.\n\n")
        + f"Best regards,\nNexaFlow AI Sales Team"
    )

    now = _now_iso()
    with db_session() as conn:
        conn.execute(
            """
            UPDATE calls
            SET status = 'completed',
                sentiment_score = ?,
                summary = ?,
                next_action = ?,
                followup_email = ?,
                ended_at = ?
            WHERE id = ?
            """,
            (avg_sentiment, summary_text, next_action, followup_email, now, call_id),
        )
        if call["lead_id"]:
            conn.execute("UPDATE leads SET notes = ?, updated_at = ? WHERE id = ?", (summary_text, now, call["lead_id"]))

    if call["lead_id"]:
        log_activity(call["lead_id"], "call_completed", summary_text, call_id=call_id)

    _push_webhook("call.summarized", {"call_id": call_id, "summary": summary_text, "score": call["qualification_score"]})

    return {
        "call_id": call_id,
        "summary": summary_text,
        "next_action": next_action,
        "followup_email": followup_email,
        "qualification_score": call["qualification_score"],
        "qualification_tier": call["qualification_tier"],
        "avg_sentiment": avg_sentiment,
        "objections": objections,
        "turn_count": len(user_turns),
        "appointment": dict(appt) if appt else None,
    }


def get_business_insights() -> Dict[str, Any]:
    with db_session() as conn:
        calls = conn.execute("SELECT * FROM calls").fetchall()
        leads = conn.execute("SELECT * FROM leads").fetchall()
        appts = conn.execute("SELECT * FROM appointments").fetchall()

    total_calls = len(calls)
    total_leads = len(leads)
    total_appts = len(appts)
    sql_count = sum(1 for c in calls if c["qualification_score"] >= 70)
    avg_score = round(sum(c["qualification_score"] for c in calls) / total_calls, 1) if total_calls else 0.0
    avg_sentiment = round(sum(c["sentiment_score"] for c in calls) / total_calls, 2) if total_calls else 0.0

    lang_counts: Dict[str, int] = {}
    objection_counts: Dict[str, int] = {}
    for c in calls:
        lang = c["language"] or "en"
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
        for obj in json.loads(c["objections_json"] or "[]"):
            objection_counts[obj] = objection_counts.get(obj, 0) + 1

    stage_counts: Dict[str, int] = {}
    for l in leads:
        stage_counts[l["stage"]] = stage_counts.get(l["stage"], 0) + 1

    # Conservative ACV estimate: $1,200/yr per Qualified/Demo-booked lead.
    est_pipeline_usd = sum(
        3600 if l["stage"] == "Demo Booked" else (1800 if l["qualification_score"] >= 70 else 600)
        for l in leads
    )

    return {
        "total_calls": total_calls,
        "total_leads": total_leads,
        "demos_booked": total_appts,
        "sql_count": sql_count,
        "conversion_rate_pct": round((total_appts / total_calls) * 100, 1) if total_calls else 0.0,
        "avg_qualification_score": avg_score,
        "avg_sentiment": avg_sentiment,
        "estimated_pipeline_usd": est_pipeline_usd,
        "languages": lang_counts,
        "top_objections": objection_counts,
        "pipeline_stages": stage_counts,
    }
