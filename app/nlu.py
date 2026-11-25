import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from .schemas import BANTState

HINGLISH_MARKERS = {
    "namaste", "kaise", "kya", "kitna", "paisa", "kharcha", "chahiye",
    "hume", "humara", "hamari", "aap", "batao", "bataiye", "theek",
    "thik", "haan", "nahi", "karna", "milega", "samajh", "bhai", "kal",
    "aaj", "baje", "bhejo", "demo", "keemat", "kimat", "baat",
}

SPANISH_MARKERS = {
    "hola", "precio", "cuanto", "cuesta", "quiero", "necesito", "equipo",
    "seguridad", "reunion", "manana", "gracias", "buenos", "dias", "por",
    "favor", "integracion", "empresa", "presupuesto",
}

POSITIVE_WORDS = {
    "great", "good", "awesome", "love", "interested", "yes", "sure", "perfect",
    "sounds good", "helpful", "fast", "works", "book", "schedule", "proceed",
    "excited", "nice", "badiya", "badhiya", "accha", "achha", "haan", "genial",
    "excelente", "perfecto", "interesado",
}

NEGATIVE_WORDS = {
    "expensive", "costly", "too high", "slow", "worried", "concern", "doubt",
    "not sure", "maybe later", "busy", "complicated", "no", "hate", "bad",
    "frustrated", "waste", "mehnga", "mehenga", "mushkil", "nahi", "caro",
    "complicado", "duda",
}


def detect_language(text: str, hint: str = "auto") -> str:
    if hint and hint != "auto":
        return hint.split("-")[0].lower()

    if any("\u0900" <= ch <= "\u097f" for ch in text):
        return "hi"

    words = set(re.findall(r"[a-zA-Z]+", text.lower()))
    if len(words & HINGLISH_MARKERS) >= 2 or (
        len(words & HINGLISH_MARKERS) == 1 and any(w in words for w in {"kya", "kitna", "batao", "baje", "chahiye", "namaste"})
    ):
        return "hi"
    if len(words & SPANISH_MARKERS) >= 2:
        return "es"
    return "en"


def analyze_sentiment(text: str) -> Tuple[float, str]:
    lower = text.lower()
    pos_hits = sum(1 for w in POSITIVE_WORDS if w in lower)
    neg_hits = sum(1 for w in NEGATIVE_WORDS if w in lower)

    raw = (pos_hits - neg_hits) * 0.35
    if "?" in text and pos_hits == 0 and neg_hits == 0:
        raw = 0.05
    score = round(max(-1.0, min(1.0, raw)), 2)

    if score >= 0.25:
        label = "Positive"
    elif score <= -0.35:
        label = "Frustrated"
    elif score < 0:
        label = "Hesitant"
    else:
        label = "Neutral"
    return score, label


def detect_objections(text: str) -> List[str]:
    lower = text.lower()
    found = []
    if any(k in lower for k in ("expensive", "costly", "too much", "budget", "cheaper", "discount", "mehnga", "caro")):
        found.append("Pricing / Budget")
    if any(k in lower for k in ("security", "privacy", "gdpr", "soc2", "soc 2", "dpdp", "data safe", "suraksha")):
        found.append("Data Security & Compliance")
    if any(k in lower for k in ("already use", "migration", "integrate", "salesforce", "hubspot", "zoho", "setup time")):
        found.append("CRM Integration & Onboarding")
    if any(k in lower for k in ("not now", "next quarter", "too busy", "later", "no time")):
        found.append("Timing / Bandwidth")
    return found


def detect_intent(text: str) -> str:
    lower = text.lower().strip()
    if any(k in lower for k in ("book", "schedule", "appointment", "calendar", "slot", "demo", "meeting", "reunion", "baje")):
        if any(k in lower for k in ("am", "pm", "baje", "tomorrow", "today", "monday", "tuesday", "wednesday", "thursday", "friday", "kal", "@")):
            return "confirm_booking"
        return "booking_request"
    if any(k in lower for k in ("bye", "goodbye", "thanks that's all", "wrap up", "end call", "dhanyawad", "gracias")):
        return "wrap_up"
    if any(k in lower for k in ("price", "pricing", "cost", "plan", "discount", "kitna", "keemat", "precio")):
        return "pricing_inquiry"
    if any(k in lower for k in ("security", "soc", "gdpr", "integrat", "api", "crm", "hubspot", "salesforce", "roi", "case study")):
        return "product_question"
    if detect_objections(lower):
        return "objection"
    if any(k in lower for k in ("hi", "hello", "hey", "namaste", "hola", "good morning", "good afternoon")) and len(lower.split()) <= 5:
        return "greeting"
    return "provide_info"


EMAIL_VALIDATION_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
EMAIL_SEARCH_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")


def is_valid_email(email: Optional[str]) -> bool:
    return bool(email and EMAIL_VALIDATION_RE.fullmatch(email.strip()))


def extract_email(text: str) -> Optional[str]:
    match = EMAIL_SEARCH_RE.search(text)
    if not match:
        return None
    candidate = match.group(0).strip().rstrip(".,!?;:")
    return candidate if is_valid_email(candidate) else None


def extract_bant_updates(text: str, current: BANTState) -> BANTState:
    data = current.model_dump()
    lower = text.lower()

    extracted_email = extract_email(text)
    if extracted_email:
        data["contact_email"] = extracted_email

    name_match = re.search(r"(?:my name is|i am|i'm|this is|mera naam)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", text, re.IGNORECASE)
    if name_match:
        candidate = name_match.group(1).strip()
        if candidate.lower() not in {"looking", "calling", "interested", "from"}:
            data["contact_name"] = candidate.title()

    comp_match = re.search(r"(?:from|at|company is|work at|company)\s+([A-Z][A-Za-z0-9&.\- ]{2,28})", text)
    if comp_match and not data.get("company"):
        data["company"] = comp_match.group(1).strip().rstrip(".,")

    size_match = re.search(
        r"\b(\d{1,4})\s*(?:[a-z]+\s+){0,2}(?:people|person|seats|users|agents|reps|employees|members|staff|log|team)\b",
        lower,
    )
    if not size_match:
        size_match = re.search(r"\bteam\s+of\s+(\d{1,4})\b", lower)
    if size_match:
        data["team_size"] = f"{size_match.group(1)} seats"

    budget_match = re.search(r"(\$\s?\d[\d,]*(?:\s?k|\s?/\s?mo|\s?per month)?|\d+\s?(?:lakh|lakhs|inr|rs|usd))", lower)
    if budget_match:
        data["budget"] = budget_match.group(1).strip()
    elif any(k in lower for k in ("budget approved", "have budget", "budget ready", "around 2000", "2k")):
        data["budget"] = "Confirmed budget"

    if any(k in lower for k in ("vp", "head of", "director", "founder", "ceo", "cto", "manager", "decision maker", "i decide", "my team")):
        data["authority"] = "Decision maker / Influencer"

    if any(
        k in lower
        for k in (
            "automate", "support", "lead", "crm", "follow up", "follow-up",
            "slow response", "tickets", "voice", "sales", "workflow",
            "qualification", "qualify", "pipeline", "booking", "scheduling",
            "onboarding", "conversion", "reduce", "scale",
        )
    ):
        if not data.get("need"):
            data["need"] = text.strip()[:140]

    timeline_phrases = (
        "this week", "next week", "this month", "next month", "this quarter",
        "within 2 weeks", "within 30 days", "by end of month", "right away",
        "asap", "immediately", "urgent", "soon", "this year",
        "q1", "q2", "q3", "q4", "jaldi", "abhi",
    )
    if any(phrase in lower for phrase in timeline_phrases):
        for phrase in timeline_phrases:
            if phrase in lower:
                data["timeline"] = phrase.upper() if phrase.startswith("q") else phrase.title()
                break

    return BANTState(**data)


def extract_booking_details(text: str) -> Dict[str, Optional[str]]:
    lower = text.lower()
    today = datetime.now().date()
    slot_date: Optional[str] = None
    slot_time: Optional[str] = None

    date_iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if date_iso:
        slot_date = date_iso.group(1)
    elif "tomorrow" in lower or "kal" in lower or "manana" in lower:
        d = today + timedelta(days=1)
        if d.weekday() >= 5:
            d += timedelta(days=(7 - d.weekday()))
        slot_date = d.isoformat()
    elif "today" in lower or "aaj" in lower:
        slot_date = today.isoformat()
    else:
        weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday"]
        for i, day_name in enumerate(weekdays):
            if day_name in lower:
                delta = (i - today.weekday()) % 7
                if delta == 0:
                    delta = 7
                slot_date = (today + timedelta(days=delta)).isoformat()
                break

    time_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|baje)\b", lower)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or "00")
        meridiem = time_match.group(3)
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        elif meridiem == "baje" and hour <= 7:
            hour += 12
        slot_time = f"{hour:02d}:{minute:02d}"

    return {"slot_date": slot_date, "slot_time": slot_time}


def score_lead(bant: BANTState, sentiment_score: float, intent: str, text: str = "") -> Tuple[int, str]:
    score = 10
    if bant.need:
        score += 20
    if bant.team_size:
        m = re.search(r"\d+", bant.team_size)
        seats = int(m.group(0)) if m else 0
        if seats >= 50:
            score += 20
        elif seats >= 15:
            score += 15
        else:
            score += 10
    if bant.budget:
        score += 15
    if bant.authority:
        score += 15
    if bant.timeline:
        score += 15
    if bant.company:
        score += 5
    if bant.contact_email:
        score += 10

    if intent in ("booking_request", "confirm_booking"):
        score += 15
    elif intent in ("pricing_inquiry", "product_question"):
        score += 5

    lower = text.lower()
    if any(p in lower for p in ("want to", "need to", "looking to", "looking for", "planning to", "evaluating", "ready to")):
        score += 5

    if sentiment_score > 0.2:
        score += 5
    elif sentiment_score < -0.3:
        score -= 10

    score = max(0, min(100, score))
    if score >= 70:
        tier = "Hot (SQL)"
    elif score >= 40:
        tier = "Warm"
    else:
        tier = "Cold"
    return score, tier
