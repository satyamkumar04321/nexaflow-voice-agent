# Project Report: NexaFlow Autonomous AI Sales Voice Agent

**Author:** Satyam Kumar | **Stack:** Python, FastAPI, WebSockets, SQLite, scikit-learn (RAG), Web Speech API, Google Gemini (optional)

---

## 1. Business Problem & Commercial Feasibility
Inside sales teams lose 40–60% of inbound leads due to slow response times (often hours), repetitive manual BANT discovery, inconsistent CRM logging, and language barriers across regional markets. Hiring round-the-clock multilingual SDRs increases CAC significantly.

**Solution:** An autonomous AI sales voice agent that answers or initiates discovery calls in under a second, communicates in English, Hindi/Hinglish, and Spanish, answers technical and pricing questions strictly from verified product documentation (RAG), scores lead intent in real time, and books qualified meetings directly into the sales team's calendar and CRM.

**Commercial Viability:** At an average B2B SaaS price of \$99–\$199/month per virtual SDR seat (or \$0.06–\$0.09/call-minute usage pricing), a single deployment replacing 40–60 hours/month of manual Level-1 qualification yields 70%+ gross margins and pays back within 2–3 months for SMB/mid-market sales teams.

## 2. System Architecture & End-to-End Workflow
1. **Voice & Transport Layer:** Browser Web Speech API (`SpeechRecognition` + `speechSynthesis` with barge-in) streams transcripts over `/ws/call/{call_id}` to FastAPI.
2. **NLU & Memory Layer (`app/nlu.py`):** Detects language (`en`, `hi`, `es`), computes turn sentiment (`-1.0` to `+1.0`), flags objections (`Pricing`, `Security`, `Integration`, `Timing`), and updates structured BANT slots (`Need`, `Team Size`, `Budget`, `Authority`, `Timeline`, `Email`).
3. **Grounded RAG (`app/rag.py`):** Chunks Markdown knowledge docs by section and retrieves top-k evidence via TF-IDF cosine similarity + cross-lingual query expansion, eliminating pricing hallucinations.
4. **Agent & Tool Execution (`app/agent.py`, `app/crm.py`):** Uses Gemini (`gemini-2.5-flash`) when configured—or a deterministic local dialogue policy with zero external API keys—to generate concise voice-ready replies, book conflict-free calendar slots, sync leads/activities to SQLite (and optional external CRM webhooks), and produce post-call summaries + follow-up email drafts.

## 3. Scalability Strategy (Up to 100,000 Users)
- **Stateless API & Media Tier:** Replace single-node FastAPI + browser Web Speech with horizontally autoscaled FastAPI/ASGI pods behind an L7 load balancer, plus **LiveKit / WebRTC SFU** media nodes for SIP/telephony audio streaming.
- **Distributed State & Vector Search:** Migrate SQLite to **PostgreSQL** (read replicas + PgBouncer connection pooling), store active call memory in **Redis Cluster** (sub-2ms turn state lookup), and move KB retrieval to **pgvector / Qdrant** with tenant-scoped namespaces.
- **Async Inference & Queues:** Run STT (Whisper/Deepgram) and TTS (Kokoro/ElevenLabs) on GPU worker pools with streaming chunk synthesis; offload CRM webhooks, call summarization, and analytics rollups to **Kafka / Celery** workers so voice latency stays under 500 ms.

## 4. Data Security, Deployment & Operational Cost
- **Security:** TLS 1.3 / SRTP in transit, AES-256 at rest, regex/NER PII masking (email, phone, PAN/card) before logging, per-tenant RBAC, SAML SSO, and zero-retention LLM endpoints aligned with SOC 2 Type II, GDPR, and India DPDP Act 2023.
- **Deployment:** Containerized Docker/Kubernetes deployment across regional clusters (e.g., `ap-south-1` Mumbai for India data residency) with Prometheus/OpenTelemetry latency monitoring.
- **Estimated Monthly Cost (at scale):**
  - *Pilot / MVP (1,000 calls/mo):* ~\$25–\$45/mo (1 small VM + managed DB + LLM tokens).
  - *Growth (100,000 users, ~500k call mins/mo):* Streaming STT (~\$2,150), fast LLM inference (~\$900), self-hosted/cached TTS (~\$1,800), Kubernetes + Redis + Postgres + LiveKit bandwidth (~\$1,400) = **~\$6,250/mo** (~$\$0.0125$/call-min, leaving >80% margin against \$0.07/min SaaS pricing).
