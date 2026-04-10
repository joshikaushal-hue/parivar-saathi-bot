"""
app.py
FastAPI backend for the IVF AI Call Conversation Engine.

Endpoints
─────────
POST /chat          – JSON API (web / testing)
POST /whatsapp      – Twilio WhatsApp webhook
GET  /leads         – Admin view (JSON); optional ?status= &date= filters
GET  /health        – Liveness check

Run
───
    uvicorn app:app --host 0.0.0.0 --port 8000 --reload

Environment variables (place in .env)
──────────────────────────────────────
    OPENAI_API_KEY=sk-...
"""

import os
import sys
import time
import uuid
import logging
from datetime import datetime
from typing import Optional

import openai
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse, Response

# ── Engine imports (existing, untouched) ──────────────────────────────────────
from main import IVFConversationEngine
from state_machine import (
    S1, S2, S3, S4, S5, S6,
    ACTION_END, ACTION_TRANSFER, ACTION_CONTINUE,
)
from database import init_db, upsert_lead, get_all_leads
from sessions import (
    load_state, save_state, delete_session, active_session_count
)
from counselor_brief import generate_brief
from outcome_tracker import (
    migrate_outcome_columns, record_outcome, store_counselor_brief,
    set_follow_up_time, get_conversion_metrics, VALID_OUTCOMES,
)
from lead_scorer import score_lead

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/app.log", mode="a", encoding="utf-8"),
    ],
)
log = logging.getLogger("ivf_engine")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="IVF Lead Engine",
    version="1.0.0",
    description="State-driven IVF lead qualification system",
)

FALLBACK_MESSAGE = (
    "We're facing a temporary issue. Our team will reach out shortly."
)


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    init_db()
    migrate_outcome_columns()   # safe idempotent migration for new columns
    log.info("IVF Lead Engine started — DB ready (v2.0 with Lead Intelligence)")


# ── Middleware: request logging + response timing ────────────────────────────

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            log.error(f"Unhandled middleware exception: {exc}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"response_text": FALLBACK_MESSAGE},
            )
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        log.info(
            f"{request.method} {request.url.path} "
            f"→ {response.status_code} ({elapsed_ms} ms)"
        )
        return response


app.add_middleware(RequestLoggingMiddleware)


# ── Duplicate-message guard (in-memory; bounded to 10 000 entries) ────────────

_seen_message_sids: set = set()

def _is_duplicate(message_sid: str) -> bool:
    if not message_sid:
        return False
    if message_sid in _seen_message_sids:
        return True
    _seen_message_sids.add(message_sid)
    if len(_seen_message_sids) > 10_000:
        _seen_message_sids.clear()   # simple bounded eviction
    return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_engine(session_id: str) -> IVFConversationEngine:
    """
    Create an IVFConversationEngine with state loaded from sessions.json.
    A fresh OpenAI client is created on each request (lightweight — just config).
    """
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    engine = IVFConversationEngine(client=client, session_id=session_id)
    engine.state = load_state(session_id)   # replaces brand-new state with persisted one
    return engine


def _lead_status(engine: IVFConversationEngine) -> str:
    """
    Map engine state → human-readable lead status for the database.

    complete             – S5/S6 fully closed (action = end or transfer)
    declined             – S1 refusal (action = end at S1)
    dropped_s2           – session ended while still in S1/S2
    dropped_s5           – session ended at S5 without confirming
    awaiting_confirmation– S5 closing shown, waiting for yes/no
    in_progress          – collecting data (S3/S4)
    active               – just started
    """
    cs     = engine.state.current_state
    action = engine.state.action

    if cs == S1 and action == ACTION_END:
        return "declined"
    if cs in (S1, S2):
        return "dropped_s2"
    if cs in (S3, S4):
        return "in_progress"
    if cs == S5:
        if action == ACTION_END:
            return "dropped_s5"
        if action == ACTION_TRANSFER:
            return "complete"
        return "awaiting_confirmation"
    if cs == S6:
        return "complete" if action == ACTION_END else "in_progress"
    return "active"


def _twiml(message: str) -> Response:
    """Wrap a reply in Twilio TwiML XML."""
    # Escape XML special characters in the message
    safe = (
        message
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f"    <Message>{safe}</Message>\n"
        "</Response>"
    )
    return Response(content=xml, media_type="application/xml")


# ── POST /chat ────────────────────────────────────────────────────────────────

@app.post("/chat")
async def chat_endpoint(request: Request):
    """
    JSON API for web / testing use.

    Request body:
        { "session_id": "optional-id", "message": "user text" }

    Response:
        { "session_id": "...", "next_state": "...", "response_text": "...",
          "lead_score": "...", "action": "..." }
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "Invalid JSON body"}, status_code=400
        )

    session_id  = (body.get("session_id") or str(uuid.uuid4())[:8]).strip()
    user_input  = (body.get("message") or "").strip()

    if not user_input:
        return JSONResponse({"error": "message is required"}, status_code=400)

    try:
        engine = _build_engine(session_id)
        result = engine.process_turn(user_input)
        save_state(session_id, engine.state)

        # ── Generate Lead Intelligence Report when S5 is first reached ────────
        brief      = None
        priority_r = None
        if engine.state.current_state in (S5, S6):
            cd = engine.state.collected_data()
            brief = generate_brief(
                duration_months  = cd.get("duration_months"),
                age              = cd.get("age"),
                treatment_history= cd.get("treatment_history"),
                phone            = None,
                session_id       = session_id,
            )
            priority_r = brief.get("priority_rank")
            # Set follow-up schedule
            set_follow_up_time(session_id, brief.get("follow_up_hours", 72))

        upsert_lead(
            session_id      = session_id,
            phone           = None,
            lead_score      = engine.state.lead_score,
            status          = _lead_status(engine),
            state_reached   = engine.state.current_state,
            source          = "api",
            collected_data  = engine.state.collected_data(),
            counselor_brief = brief,
            priority_rank   = priority_r,
        )

        if engine.is_complete():
            delete_session(session_id)

        # Include brief summary in response when available
        response_payload = {"session_id": session_id, **result}
        if brief:
            response_payload["lead_intelligence"] = {
                "priority_rank":    brief["priority_rank"],
                "severity_tag":     brief["severity_tag"],
                "ivf_probability":  brief["ivf_probability"],
                "priority_action":  brief["priority_action"],
                "follow_up_hours":  brief["follow_up_hours"],
            }
        return JSONResponse(response_payload)

    except Exception as exc:
        log.error(f"/chat [{session_id}] error: {exc}", exc_info=True)
        return JSONResponse(
            {"session_id": session_id, "response_text": FALLBACK_MESSAGE},
            status_code=500,
        )


# ── POST /whatsapp ────────────────────────────────────────────────────────────

@app.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Twilio WhatsApp webhook.
    Twilio sends a URL-encoded form body with fields: From, Body, MessageSid, etc.

    Hardening:
      1. Missing From → silent 200 (Twilio retry prevention)
      2. Empty Body   → polite re-prompt, no engine call
      3. Duplicate MessageSid → silent 200
      4. Any engine/DB error → safe fallback message, never 5xx to Twilio
    """
    try:
        form = await request.form()
    except Exception:
        log.warning("/whatsapp: could not parse form body")
        return Response(status_code=200)   # don't crash; Twilio would retry

    from_number = (form.get("From") or "").strip()
    body        = (form.get("Body") or "").strip()
    message_sid = (form.get("MessageSid") or "").strip()

    # ── Guard 1: missing sender ────────────────────────────────────────────────
    if not from_number:
        log.warning("/whatsapp: received message with no From field — ignoring")
        return Response(status_code=200)

    # ── Guard 2: empty message body ────────────────────────────────────────────
    if not body:
        log.info(f"/whatsapp: empty body from {from_number}")
        return _twiml("Please type a message and I'll be happy to help.")

    # ── Guard 3: duplicate MessageSid ─────────────────────────────────────────
    if _is_duplicate(message_sid):
        log.warning(f"/whatsapp: duplicate MessageSid={message_sid} from {from_number} — ignoring")
        return Response(status_code=200)

    # ── Incoming log ───────────────────────────────────────────────────────────
    log.info(
        f"WA IN  | from={from_number} | sid={message_sid} | msg={body[:100]!r}"
    )

    # ── Session key: derived from phone number (stable across restarts) ────────
    session_id = "wa_" + from_number.replace("+", "").replace(":", "_")

    try:
        engine = _build_engine(session_id)
        result = engine.process_turn(body)
        save_state(session_id, engine.state)

        # ── Generate Lead Intelligence Report when S5 is first reached ────────
        brief      = None
        priority_r = None
        if engine.state.current_state in (S5, S6):
            cd = engine.state.collected_data()
            brief = generate_brief(
                duration_months  = cd.get("duration_months"),
                age              = cd.get("age"),
                treatment_history= cd.get("treatment_history"),
                phone            = from_number,
                session_id       = session_id,
            )
            priority_r = brief.get("priority_rank")
            set_follow_up_time(session_id, brief.get("follow_up_hours", 72))
            log.info(
                f"WA BRIEF | {session_id} | rank={priority_r} | "
                f"tag={brief.get('severity_tag')} | action={brief.get('priority_action')}"
            )

        upsert_lead(
            session_id      = session_id,
            phone           = from_number,
            lead_score      = engine.state.lead_score,
            status          = _lead_status(engine),
            state_reached   = engine.state.current_state,
            source          = "whatsapp",
            collected_data  = engine.state.collected_data(),
            counselor_brief = brief,
            priority_rank   = priority_r,
        )

        if engine.is_complete():
            delete_session(session_id)

        reply = result.get("response_text") or FALLBACK_MESSAGE

    except Exception as exc:
        log.error(
            f"/whatsapp [{session_id}] engine error: {exc}", exc_info=True
        )
        reply = FALLBACK_MESSAGE

    log.info(
        f"WA OUT | to={from_number} | msg={reply[:100]!r}"
    )
    return _twiml(reply)


# ── GET /leads ────────────────────────────────────────────────────────────────

@app.get("/leads")
async def leads_view(
    status: Optional[str] = None,
    date:   Optional[str] = None,
):
    """
    Admin endpoint. Returns all captured leads as JSON.

    Optional query params:
        ?status=complete          filter by status
        ?date=2025-01-15          filter by created date (YYYY-MM-DD)
        ?status=dropped_s2&date=2025-01-15  combined filter

    Valid statuses:
        active | in_progress | awaiting_confirmation |
        dropped_s2 | dropped_s5 | declined | complete
    """
    try:
        leads = get_all_leads(status=status, date=date)
        return JSONResponse({
            "total":   len(leads),
            "filters": {"status": status, "date": date},
            "leads":   leads,
        })
    except Exception as exc:
        log.error(f"/leads error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not fetch leads")


# ── POST /outcome ─────────────────────────────────────────────────────────────

@app.post("/outcome")
async def record_call_outcome(request: Request):
    """
    Tag a lead with a call outcome after a counselor or AI call.

    Request body:
        {
            "session_id": "...",
            "outcome": "booked" | "follow_up" | "not_interested" | "invalid" | "no_answer",
            "call_notes": "optional free text"
        }

    Valid outcomes:
        booked | follow_up | not_interested | invalid | no_answer | consultation_done
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    session_id = (body.get("session_id") or "").strip()
    outcome    = (body.get("outcome") or "").strip()
    call_notes = (body.get("call_notes") or "").strip() or None

    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=400)
    if outcome not in VALID_OUTCOMES:
        return JSONResponse({
            "error": f"Invalid outcome. Must be one of: {sorted(VALID_OUTCOMES)}"
        }, status_code=400)

    success = record_outcome(session_id, outcome, call_notes)
    if not success:
        return JSONResponse({"error": "session_id not found"}, status_code=404)

    log.info(f"OUTCOME | session={session_id} | outcome={outcome}")
    return JSONResponse({"status": "recorded", "session_id": session_id, "outcome": outcome})


# ── GET /metrics ───────────────────────────────────────────────────────────────

@app.get("/metrics")
async def conversion_metrics(date: Optional[str] = None):
    """
    Clinic conversion dashboard metrics.

    Optional query param:
        ?date=2025-01-15   — filter by created date (YYYY-MM-DD)

    Returns:
        total_leads, hot/warm/cold counts, contacted_pct, booked_pct,
        not_interested_pct, avg_priority_rank, leads_due_follow_up
    """
    try:
        metrics = get_conversion_metrics(date=date)
        return JSONResponse(metrics)
    except Exception as exc:
        log.error(f"/metrics error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not compute metrics")


# ── GET /health ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Liveness probe — returns 200 if the server is up."""
    return {
        "status":           "ok",
        "timestamp":        datetime.utcnow().isoformat() + "Z",
        "active_sessions":  active_session_count(),
    }
