"""
voice_routes.py
FastAPI Voice Call Endpoints — Twilio Voice Webhooks

Endpoints:
  POST /voice/answer      — Twilio calls this when outbound call connects
  POST /voice/gather      — Twilio calls this with speech transcription
  POST /voice/status      — Twilio calls this with call status updates
  POST /voice/initiate    — API to trigger an outbound call (counselor or auto)
  GET  /voice/audio/{id}  — Serve TTS audio files to Twilio

Auto-call flow:
  1. Lead completes WhatsApp → scored → if priority 1 → auto-trigger call
  2. POST /voice/initiate creates Twilio outbound call
  3. Twilio connects → POST /voice/answer → plays opening script
  4. Caller speaks → Twilio <Gather speech> → POST /voice/gather
  5. Loop gather/respond until call ends
  6. POST /voice/status records outcome
"""

import os
import uuid
import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response, JSONResponse, FileResponse

from voice_agent import (
    init_call, get_opening_text, process_caller_response,
    text_to_speech, get_voice_state, delete_voice_state,
    save_voice_state, REPROMPT,
)
from outcome_tracker import record_outcome, OUTCOME_NO_ANSWER
from database import get_all_leads

log = logging.getLogger("ivf_engine")

router = APIRouter(prefix="/voice", tags=["voice"])

# ── Configuration ────────────────────────────────────────────────────────────

BASE_URL = os.environ.get("BASE_URL", "https://parivar-saathi-bot.onrender.com")
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER", "")  # Your Twilio number

# Speech recognition settings
SPEECH_LANGUAGE = "hi-IN"  # Hindi (India) — also recognizes English
SPEECH_TIMEOUT = "auto"    # Auto-detect end of speech
GATHER_TIMEOUT = 5         # Seconds to wait for speech


# ── TwiML helpers ────────────────────────────────────────────────────────────

def _voice_twiml_say(text: str, gather: bool = True) -> str:
    """
    Generate TwiML that either plays Sarvam TTS audio or falls back to Twilio <Say>.

    If Sarvam TTS is available, generates audio and uses <Play>.
    Otherwise, uses Twilio's built-in <Say> with an Indian English voice.
    """
    # Try Sarvam TTS first
    audio_path = text_to_speech(text)

    if audio_path and os.path.exists(audio_path):
        # Serve audio via our /voice/audio endpoint
        audio_id = os.path.basename(audio_path).replace(".wav", "")
        audio_url = f"{BASE_URL}/voice/audio/{audio_id}"

        if gather:
            return (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<Response>\n"
                f'  <Gather input="speech" language="{SPEECH_LANGUAGE}" '
                f'speechTimeout="{SPEECH_TIMEOUT}" timeout="{GATHER_TIMEOUT}" '
                f'action="{BASE_URL}/voice/gather" method="POST">\n'
                f"    <Play>{audio_url}</Play>\n"
                "  </Gather>\n"
                f'  <Redirect method="POST">{BASE_URL}/voice/gather</Redirect>\n'
                "</Response>"
            )
        else:
            return (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<Response>\n"
                f"  <Play>{audio_url}</Play>\n"
                "  <Hangup/>\n"
                "</Response>"
            )

    # Fallback: use Twilio's built-in Say
    safe_text = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

    if gather:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            f'  <Gather input="speech" language="{SPEECH_LANGUAGE}" '
            f'speechTimeout="{SPEECH_TIMEOUT}" timeout="{GATHER_TIMEOUT}" '
            f'action="{BASE_URL}/voice/gather" method="POST">\n'
            f'    <Say voice="Polly.Aditi" language="hi-IN">{safe_text}</Say>\n'
            "  </Gather>\n"
            f'  <Redirect method="POST">{BASE_URL}/voice/gather</Redirect>\n'
            "</Response>"
        )
    else:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            f'  <Say voice="Polly.Aditi" language="hi-IN">{safe_text}</Say>\n'
            "  <Hangup/>\n"
            "</Response>"
        )


def _twiml_response(xml: str) -> Response:
    return Response(content=xml, media_type="application/xml")


# ── POST /voice/answer ───────────────────────────────────────────────────────

@router.post("/answer")
async def voice_answer(request: Request):
    """
    Called by Twilio when an outbound call connects.
    Plays the opening script from call_logic.py.

    Twilio form fields: CallSid, From, To, CallStatus, etc.
    """
    try:
        form = await request.form()
    except Exception:
        log.warning("/voice/answer: could not parse form")
        return Response(status_code=200)

    call_sid = (form.get("CallSid") or "").strip()
    to_number = (form.get("To") or "").strip()
    call_status = (form.get("CallStatus") or "").strip()

    log.info(f"VOICE ANS | sid={call_sid} | to={to_number} | status={call_status}")

    # Retrieve voice state (set up by /voice/initiate)
    state = get_voice_state(call_sid)

    if not state:
        # Call might have been initiated externally — create minimal state
        log.warning(f"VOICE ANS | No state for {call_sid} — creating default")
        state = init_call(
            call_sid=call_sid,
            session_id=f"call_{call_sid[:8]}",
            phone=to_number,
            lead_score="Warm",
        )

    # Get opening text and respond
    opening = get_opening_text(state)
    twiml = _voice_twiml_say(opening, gather=True)

    log.info(f"VOICE OUT | sid={call_sid} | opening={opening[:80]!r}")
    return _twiml_response(twiml)


# ── POST /voice/gather ───────────────────────────────────────────────────────

@router.post("/gather")
async def voice_gather(request: Request):
    """
    Called by Twilio with speech transcription results.
    Processes the caller's speech and responds with next script.

    Twilio form fields: CallSid, SpeechResult, Confidence, etc.
    """
    try:
        form = await request.form()
    except Exception:
        log.warning("/voice/gather: could not parse form")
        return Response(status_code=200)

    call_sid = (form.get("CallSid") or "").strip()
    speech_result = (form.get("SpeechResult") or "").strip()
    confidence = form.get("Confidence", "")

    log.info(
        f"VOICE GAT | sid={call_sid} | speech={speech_result[:100]!r} | "
        f"confidence={confidence}"
    )

    # No speech detected — prompt again
    if not speech_result:
        twiml = _voice_twiml_say(REPROMPT, gather=True)
        return _twiml_response(twiml)

    # Process the caller's response (strict state machine, no OpenAI)
    response_text, should_end = process_caller_response(
        call_sid=call_sid,
        caller_text=speech_result,
    )

    log.info(
        f"VOICE OUT | sid={call_sid} | end={should_end} | "
        f"reply={response_text[:80]!r}"
    )

    twiml = _voice_twiml_say(response_text, gather=not should_end)
    return _twiml_response(twiml)


# ── POST /voice/status ───────────────────────────────────────────────────────

@router.post("/status")
async def voice_status(request: Request):
    """
    Twilio status callback — called when call status changes.
    Records call outcome based on final status.

    Key statuses: initiated, ringing, in-progress, completed,
                  busy, no-answer, failed, canceled
    """
    try:
        form = await request.form()
    except Exception:
        return Response(status_code=200)

    call_sid = (form.get("CallSid") or "").strip()
    call_status = (form.get("CallStatus") or "").strip()
    duration = form.get("CallDuration", "0")

    log.info(
        f"VOICE STS | sid={call_sid} | status={call_status} | "
        f"duration={duration}s"
    )

    state = get_voice_state(call_sid)

    # Record outcome for terminal statuses
    if call_status in ("completed", "busy", "no-answer", "failed", "canceled"):
        if state:
            outcome = _map_call_status_to_outcome(call_status, state)
            record_outcome(state.session_id, outcome, f"Voice call {call_status}")
            log.info(
                f"VOICE END | sid={call_sid} | session={state.session_id} | "
                f"outcome={outcome} | duration={duration}s"
            )
            delete_voice_state(call_sid)

    return Response(status_code=200)


def _map_call_status_to_outcome(call_status: str, state) -> str:
    """Map Twilio call status to our outcome tags."""
    if call_status == "completed":
        if state.stage == "ended":
            return "follow_up"
        return "follow_up"
    if call_status in ("no-answer", "busy"):
        return "no_answer"
    if call_status in ("failed", "canceled"):
        return "no_answer"
    return "follow_up"


# ── POST /voice/initiate ─────────────────────────────────────────────────────

@router.post("/initiate")
async def initiate_call(request: Request):
    """
    API endpoint to trigger an outbound voice call.

    Used by:
      - Auto-call system (for priority 1 leads)
      - Counselor manual trigger

    Request body:
    {
        "session_id": "wa_91...",      — required
        "phone": "+919876543210",       — required (E.164 format)
        "lead_score": "Hot",            — optional (fetched from DB if missing)
        "treatment_history": "IVF failure",  — optional
        "duration_months": 36,          — optional
        "age": "35"                     — optional
    }

    Returns:
    {
        "status": "initiated",
        "call_sid": "CA...",
        "session_id": "...",
        "message": "Call initiated to +91..."
    }
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    session_id = (body.get("session_id") or "").strip()
    phone = (body.get("phone") or "").strip()
    lead_score = body.get("lead_score", "Warm")
    treatment_history = body.get("treatment_history")
    duration_months = body.get("duration_months")
    age = body.get("age")

    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=400)
    if not phone:
        return JSONResponse({"error": "phone is required (E.164 format)"}, status_code=400)

    # Validate Twilio credentials
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_PHONE_NUMBER:
        return JSONResponse({
            "error": "Twilio credentials not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_PHONE_NUMBER."
        }, status_code=500)

    try:
        # Import Twilio client
        from twilio.rest import Client as TwilioClient
        twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        # Create outbound call
        call = twilio_client.calls.create(
            to=phone,
            from_=TWILIO_PHONE_NUMBER,
            url=f"{BASE_URL}/voice/answer",
            status_callback=f"{BASE_URL}/voice/status",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
            status_callback_method="POST",
            method="POST",
            timeout=30,  # Ring for 30 seconds before giving up
        )

        # Initialize call state
        init_call(
            call_sid=call.sid,
            session_id=session_id,
            phone=phone,
            lead_score=lead_score,
            treatment_history=treatment_history,
            duration_months=duration_months,
            age=age,
        )

        log.info(
            f"VOICE CALL INITIATED | sid={call.sid} | to={phone} | "
            f"session={session_id} | score={lead_score}"
        )

        return JSONResponse({
            "status": "initiated",
            "call_sid": call.sid,
            "session_id": session_id,
            "message": f"Call initiated to {phone}",
        })

    except ImportError:
        return JSONResponse({
            "error": "twilio package not installed. Run: pip install twilio"
        }, status_code=500)
    except Exception as e:
        log.error(f"Failed to initiate call: {e}", exc_info=True)
        return JSONResponse({
            "error": f"Failed to initiate call: {str(e)}"
        }, status_code=500)


# ── GET /voice/audio/{audio_id} ──────────────────────────────────────────────

@router.get("/audio/{audio_id}")
async def serve_audio(audio_id: str):
    """
    Serve TTS audio files to Twilio.
    Audio files are cached WAV files generated by Sarvam TTS.
    """
    import tempfile
    cache_dir = os.path.join(tempfile.gettempdir(), "ivf_voice_cache")
    file_path = os.path.join(cache_dir, f"{audio_id}.wav")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Audio not found")

    return FileResponse(
        file_path,
        media_type="audio/wav",
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ── Auto-call trigger (called after WhatsApp lead completes) ─────────────────

async def auto_trigger_call_if_priority_1(
    session_id: str,
    phone: str,
    lead_score: str,
    priority_rank: int,
    treatment_history: Optional[str] = None,
    duration_months: Optional[float] = None,
    age: Optional[str] = None,
) -> Optional[str]:
    """
    Automatically triggers an outbound call for priority 1 leads.
    Called from app.py after WhatsApp conversation completes.

    Returns call_sid if triggered, None otherwise.
    """
    if priority_rank > 1:
        log.debug(f"Auto-call skip: {session_id} priority={priority_rank} (need 1)")
        return None

    if not phone or phone.startswith("wa_"):
        log.warning(f"Auto-call skip: {session_id} — no valid phone number")
        return None

    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_PHONE_NUMBER:
        log.warning(f"Auto-call skip: {session_id} — Twilio not configured")
        return None

    # Clean phone number (remove WhatsApp prefix if present)
    clean_phone = phone.replace("whatsapp:", "").strip()
    if not clean_phone.startswith("+"):
        clean_phone = f"+{clean_phone}"

    try:
        from twilio.rest import Client as TwilioClient
        twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        call = twilio_client.calls.create(
            to=clean_phone,
            from_=TWILIO_PHONE_NUMBER,
            url=f"{BASE_URL}/voice/answer",
            status_callback=f"{BASE_URL}/voice/status",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
            status_callback_method="POST",
            method="POST",
            timeout=30,
        )

        init_call(
            call_sid=call.sid,
            session_id=session_id,
            phone=clean_phone,
            lead_score=lead_score,
            treatment_history=treatment_history,
            duration_months=duration_months,
            age=age,
        )

        log.info(
            f"AUTO-CALL TRIGGERED | sid={call.sid} | to={clean_phone} | "
            f"session={session_id} | priority={priority_rank}"
        )
        return call.sid

    except ImportError:
        log.error("Auto-call failed: twilio package not installed")
        return None
    except Exception as e:
        log.error(f"Auto-call failed: {e}", exc_info=True)
        return None
