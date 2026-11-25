from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class StartCallRequest(BaseModel):
    prospect_name: Optional[str] = None
    prospect_email: Optional[str] = None
    company: Optional[str] = None
    language: str = "auto"


class TurnRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    language: str = "auto"


class RAGChunk(BaseModel):
    doc_id: str
    title: str
    section: str
    content: str
    score: float


class BANTState(BaseModel):
    budget: Optional[str] = None
    authority: Optional[str] = None
    need: Optional[str] = None
    timeline: Optional[str] = None
    team_size: Optional[str] = None
    company: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None


class TurnResponse(BaseModel):
    call_id: str
    reply: str
    language: str
    intent: str
    sentiment_score: float
    sentiment_label: str
    qualification_score: int
    qualification_tier: str
    bant: BANTState
    objections: List[str]
    rag_chunks: List[RAGChunk]
    appointment: Optional[Dict[str, Any]] = None
    crm_synced: bool = False
    latency_ms: int = 0
    llm_mode: str = "local"


class BookSlotRequest(BaseModel):
    call_id: Optional[str] = None
    prospect_name: str
    prospect_email: str
    company: str = ""
    slot_date: str
    slot_time: str
    topic: str = "NexaFlow Product Demo"


class KnowledgeDocRequest(BaseModel):
    filename: str
    content: str
