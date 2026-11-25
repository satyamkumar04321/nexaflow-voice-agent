import os
import tempfile
import pytest
from fastapi.testclient import TestClient

# Point tests to an isolated temporary SQLite database before importing app.main
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ["GEMINI_API_KEY"] = ""

from app.main import app  # noqa: E402
from app.nlu import extract_email, is_valid_email  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_and_kb(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["kb_chunks"] >= 4


def test_end_to_end_sales_workflow(client):
    # 1. Start call
    start = client.post("/api/calls", json={"prospect_name": "Ananya Rao", "company": "ScaleOps"}).json()
    call_id = start["call_id"]
    assert call_id.startswith("call-")

    # 2. Discovery turn
    t1 = client.post(
        f"/api/calls/{call_id}/turn",
        json={"text": "We have 60 sales reps and want to automate lead qualification and CRM updates this quarter."},
    ).json()
    assert t1["qualification_score"] >= 50
    assert t1["bant"]["team_size"] == "60 seats"

    # 3. Pricing objection + RAG grounding
    t2 = client.post(
        f"/api/calls/{call_id}/turn",
        json={"text": "The Growth plan seems expensive. Do you offer any volume discount or trial?"},
    ).json()
    assert "Pricing / Budget" in t2["objections"]
    assert len(t2["rag_chunks"]) >= 1
    assert any("Pricing" in c["title"] for c in t2["rag_chunks"])

    # 4. Multilingual Hinglish turn
    t3 = client.post(
        f"/api/calls/{call_id}/turn",
        json={"text": "Namaste, kya aapka platform HubSpot CRM aur security compliance ke saath kaam karta hai?"},
    ).json()
    assert t3["language"] == "hi"
    assert len(t3["rag_chunks"]) >= 1

    # 5. Automated demo booking
    t4 = client.post(
        f"/api/calls/{call_id}/turn",
        json={"text": "Sounds good. Book a demo tomorrow at 3 pm using ananya@scaleops.io."},
    ).json()
    assert t4["appointment"] is not None
    assert t4["appointment"]["prospect_email"] == "ananya@scaleops.io"
    assert t4["crm_synced"] is True

    # 6. End call & generate summary
    summary = client.post(f"/api/calls/{call_id}/end").json()
    assert "ScaleOps" in summary["summary"]
    assert summary["appointment"] is not None
    assert "Subject:" in summary["followup_email"]

    # 7. Verify CRM & Insights
    leads = client.get("/api/crm/leads").json()["leads"]
    assert any(l["email"] == "ananya@scaleops.io" and l["stage"] == "Demo Booked" for l in leads)

    insights = client.get("/api/insights").json()
    assert insights["total_calls"] >= 1
    assert insights["demos_booked"] >= 1

    # 8. Returning lead recognition
    repeat = client.post(
        "/api/calls",
        json={"prospect_email": "ananya@scaleops.io"},
    ).json()
    assert repeat["returning_lead"] is True
    assert "Welcome back" in repeat["greeting"]


def test_websocket_turn(client):
    start = client.post("/api/calls", json={"prospect_name": "Karan"}).json()
    call_id = start["call_id"]

    with client.websocket_connect(f"/ws/call/{call_id}") as ws:
        ws.send_json({"type": "transcript", "text": "What is the Starter plan price?", "language": "auto"})
        status_msg = ws.receive_json()
        assert status_msg["type"] == "status"
        resp_msg = ws.receive_json()
        assert resp_msg["type"] == "response"
        assert "$49" in resp_msg["data"]["reply"] or len(resp_msg["data"]["rag_chunks"]) > 0


def test_email_extraction_with_trailing_punctuation_and_validation(client):
    assert extract_email("Send invite to priya.sharma@acme-corp.co.in.") == "priya.sharma@acme-corp.co.in"
    assert extract_email("Use vikram@startup.io, please") == "vikram@startup.io"
    assert extract_email("Can you send it to sara+sales@example.org?") == "sara+sales@example.org"
    assert extract_email("Email is dev@company.com!") == "dev@company.com"
    assert is_valid_email("invalid-email@") is False
    assert is_valid_email("user@domain.com.") is False

    slots = client.get("/api/calendar/slots?days=2").json()["slots"]
    bad = client.post(
        "/api/calendar/book",
        json={
            "prospect_name": "Bad Email",
            "prospect_email": "not-an-email.",
            "slot_date": slots[0]["slot_date"],
            "slot_time": slots[0]["slot_time"],
        },
    )
    assert bad.status_code == 400
