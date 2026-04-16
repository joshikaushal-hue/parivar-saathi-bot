"""
Twilio voice endpoints.

Flow:
  Twilio dials →  POST /voice/incoming           → greeting + ASK_AGE
  User speaks  →  POST /voice/respond            → parse → next state audio
  Gather timeout →  POST /voice/respond?timeout=1 → replay same state prompt
  Call ends   →  POST /voice/status              → cleanup
"""
import logging
from fastapi import APIRouter, Request, Response
from app.services.session_manager import store
from app.state_machine.states import State
from app.state_machine.machine import process_input, force_advance
from app.tts import cache as tts
from app.services.nlu import hints_for
from app.utils.twiml_builder import build_gather, build_play_and_hangup
from app.config import MAX_RETRIES_PER_STATE, PUBLIC_BASE_URL

log = logging.getLogger("voice")
router = APIRouter()


RESPOND_PATH = "/voice/respond"


def _action_url() -> str:
    return f"{PUBLIC_BASE_URL}{RESPOND_PATH}"


def _build_for_state(session, target: State) -> str:
    """
    Build TwiML that prompts the user for the given target state.
    For CLOSE, we play category outcome + goodbye and hang up.
    """
    if target == State.CLOSE:
        category = session.category or "LOW"
        return build_play_and_hangup(
            [tts.close_url(category), tts.goodbye_url()],
            ack_url=tts.ack_url(),
        )

    url = tts.state_url(target)
    return build_gather(
        action_url=_action_url(),
        play_urls=[url],
        ack_url=tts.ack_url(),
        hints=hints_for(target),
    )


# ────────────────────────────────────────────────────────────────
# POST /voice/incoming  (Twilio initial webhook)
# ────────────────────────────────────────────────────────────────

@router.post("/voice/incoming")
async def voice_incoming(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "")
    # For outbound calls Twilio sends `To`; inbound sends `From`
    phone = form.get("From") or form.get("To") or ""

    session = store.get_or_create(call_sid, phone)
    # Roll GREETING → ASK_AGE so the opening + first question play back-to-back
    session.current_state = State.ASK_AGE.value
    store.save(session)

    twiml = build_gather(
        action_url=_action_url(),
        play_urls=[tts.state_url(State.GREETING), tts.state_url(State.ASK_AGE)],
        hints=hints_for(State.ASK_AGE),
    )
    log.info("[voice/incoming] call=%s phone=%s → ASK_AGE", call_sid, phone)
    return Response(content=twiml, media_type="application/xml")


# ────────────────────────────────────────────────────────────────
# POST /voice/respond  (every user turn)
# ────────────────────────────────────────────────────────────────

@router.post("/voice/respond")
async def voice_respond(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "")
    phone = form.get("From") or form.get("To") or ""
    speech = (form.get("SpeechResult") or "").strip()
    is_timeout = request.query_params.get("timeout") == "1"

    session = store.get_or_create(call_sid, phone)
    session.record("user", speech if speech else ("<timeout>" if is_timeout else "<empty>"))

    # ── Timeout: no speech captured — soft retry current state
    if is_timeout and not speech:
        current = State(session.current_state)
        session.retry_count += 1
        if session.retry_count > MAX_RETRIES_PER_STATE:
            # Give up: move on (or close if we're already near the end)
            next_state = force_advance(session)
            store.save(session)
            log.info(
                "[voice/respond] call=%s TIMEOUT_GIVEUP → %s",
                call_sid, next_state.value,
            )
            return Response(content=_build_for_state(session, next_state),
                            media_type="application/xml")
        store.save(session)
        log.info(
            "[voice/respond] call=%s TIMEOUT retry=%d state=%s",
            call_sid, session.retry_count, current.value,
        )
        twiml = build_gather(
            action_url=_action_url(),
            play_urls=[tts.retry_url(current) or tts.state_url(current)],
            ack_url=None,
            hints=hints_for(current),
        )
        return Response(content=twiml, media_type="application/xml")

    # ── Normal turn: parse input through state machine
    result = process_input(session, speech)

    # Parsed failed — retry (or force-advance if budget exhausted)
    if result["retry"]:
        current = State(session.current_state)
        if session.retry_count > MAX_RETRIES_PER_STATE:
            next_state = force_advance(session)
            store.save(session)
            log.info(
                "[voice/respond] call=%s GIVEUP state=%s → %s",
                call_sid, current.value, next_state.value,
            )
            return Response(content=_build_for_state(session, next_state),
                            media_type="application/xml")

        store.save(session)
        log.info(
            "[voice/respond] call=%s RETRY state=%s attempt=%d heard=%r",
            call_sid, current.value, session.retry_count, speech,
        )
        twiml = build_gather(
            action_url=_action_url(),
            play_urls=[tts.retry_url(current) or tts.state_url(current)],
            ack_url=None,
            hints=hints_for(current),
        )
        return Response(content=twiml, media_type="application/xml")

    # ── Parse succeeded — advance
    next_state = result["next_state"]
    store.save(session)
    log.info(
        "[voice/respond] call=%s OK → %s lead=%s",
        call_sid, next_state.value, session.lead.to_dict(),
    )

    # QUALIFY is internal — immediately fall through to CLOSE
    if next_state == State.QUALIFY:
        # process_input should have already set QUALIFY; re-run to produce CLOSE
        process_input(session, "")
        store.save(session)
        return Response(
            content=_build_for_state(session, State.CLOSE),
            media_type="application/xml",
        )

    return Response(
        content=_build_for_state(session, next_state),
        media_type="application/xml",
    )


# ────────────────────────────────────────────────────────────────
# POST /voice/status  (Twilio status callback)
# ────────────────────────────────────────────────────────────────

@router.post("/voice/status")
async def voice_status(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "")
    status = form.get("CallStatus", "")
    duration = form.get("CallDuration", "")

    s = store.get(call_sid)
    if s:
        log.info(
            "[voice/status] call=%s status=%s dur=%s state=%s score=%s cat=%s lead=%s",
            call_sid, status, duration,
            s.current_state, s.score, s.category, s.lead.to_dict(),
        )

    if status in ("completed", "failed", "busy", "no-answer", "canceled"):
        store.delete(call_sid)

    return Response(content="", media_type="text/plain")


# ────────────────────────────────────────────────────────────────
# Debug endpoints
# ────────────────────────────────────────────────────────────────

@router.get("/voice/sessions")
async def voice_sessions():
    return {
        "active": len(store.all()),
        "sessions": [s.to_dict() for s in store.all()],
    }


@router.get("/voice/sessions/{call_id}")
async def voice_session_detail(call_id: str):
    s = store.get(call_id)
    if not s:
        return Response(status_code=404, content="not_found")
    return {**s.to_dict(), "history": s.history}
