"""
voice_agent.py
AI Voice Call Agent — Sarvam TTS + Twilio Voice Integration

Provides:
  - Sarvam TTS (text-to-speech) for natural Hindi/English voice
  - Voice conversation engine that uses call_logic.py for scripts
  - OpenAI for dynamic response generation during calls
  - Call state management

Architecture:
  1. Twilio makes outbound call → /voice webhook answers
  2. Opening script from call_logic.py → Sarvam TTS → audio played
  3. Caller speaks → Twilio <Gather speech> transcribes
  4. Transcription → OpenAI generates response (with objection handling)
  5. Response → Sarvam TTS → audio played back
  6. Loop until call ends → outcome recorded
"""

import os
import base64
import logging
import tempfile
import hashlib
from typing import Optional, Tuple
from dataclasses import dataclass, field

import httpx

from call_logic import (
    get_call_script, detect_objection, handle_objection,
    OBJECTION_NOT_INTERESTED,
)
from lead_scorer import score_lead

log = logging.getLogger("ivf_engine")

# ── Sarvam TTS Configuration ────────────────────────────────────────────────

SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "")

# Default voice settings
SARVAM_SPEAKER = os.environ.get("SARVAM_SPEAKER", "ritu")  # Female Hindi voice
SARVAM_LANGUAGE = os.environ.get("SARVAM_LANGUAGE", "hi-IN")
SARVAM_MODEL = "bulbul:v3"
SARVAM_PACE = 0.95  # Slightly slower for clarity on phone
SARVAM_SAMPLE_RATE = 8000  # 8kHz for telephony (Twilio standard)

# Audio cache directory
AUDIO_CACHE_DIR = os.path.join(tempfile.gettempdir(), "ivf_voice_cache")
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)


# ── Voice Call State ─────────────────────────────────────────────────────────

@dataclass
class VoiceCallState:
    """Tracks the state of an active voice call."""
    session_id: str = ""
    call_sid: str = ""
    phone: str = ""
    lead_score: str = "Cold"
    treatment_history: Optional[str] = None
    duration_months: Optional[float] = None
    age: Optional[str] = None

    # Call flow tracking
    stage: str = "opening"  # opening → question_1 → question_2 → soft_close → objection → ended
    objection_count: int = 0
    max_objections: int = 2  # End call after 2 objections on same topic
    turn_count: int = 0
    last_objection: Optional[str] = None

    # Script cache (loaded from call_logic.py)
    script: dict = field(default_factory=dict)

    def next_stage(self) -> Optional[str]:
        """Returns the next stage in the call flow, or None if done."""
        flow = ["opening", "question_1", "question_2", "soft_close"]
        try:
            idx = flow.index(self.stage)
            if idx + 1 < len(flow):
                return flow[idx + 1]
        except ValueError:
            pass
        return None


# In-memory voice call states (keyed by call_sid)
_voice_states: dict = {}


def get_voice_state(call_sid: str) -> Optional[VoiceCallState]:
    return _voice_states.get(call_sid)


def save_voice_state(state: VoiceCallState) -> None:
    _voice_states[state.call_sid] = state


def delete_voice_state(call_sid: str) -> None:
    _voice_states.pop(call_sid, None)


# ── Sarvam TTS ───────────────────────────────────────────────────────────────

def _audio_cache_path(text: str) -> str:
    """Generate a cache file path based on text hash."""
    text_hash = hashlib.md5(text.encode()).hexdigest()
    return os.path.join(AUDIO_CACHE_DIR, f"{text_hash}.wav")


def text_to_speech(text: str, language: str = None) -> Optional[str]:
    """
    Convert text to speech using Sarvam AI TTS.

    Args:
        text: The text to convert to speech
        language: Language code (default: hi-IN for Hindi)

    Returns:
        Path to the generated WAV file, or None on failure
    """
    if not SARVAM_API_KEY:
        log.warning("SARVAM_API_KEY not set — TTS unavailable")
        return None

    # Check cache first
    cache_path = _audio_cache_path(text)
    if os.path.exists(cache_path):
        log.debug(f"TTS cache hit: {cache_path}")
        return cache_path

    lang = language or SARVAM_LANGUAGE

    try:
        response = httpx.post(
            SARVAM_TTS_URL,
            headers={
                "Content-Type": "application/json",
                "api-subscription-key": SARVAM_API_KEY,
            },
            json={
                "inputs": [text],
                "target_language_code": lang,
                "speaker": SARVAM_SPEAKER,
                "model": SARVAM_MODEL,
                "pace": SARVAM_PACE,
                "speech_sample_rate": SARVAM_SAMPLE_RATE,
                "enable_preprocessing": True,
            },
            timeout=15.0,
        )
        response.raise_for_status()
        data = response.json()

        audios = data.get("audios", [])
        if not audios:
            log.error("Sarvam TTS returned empty audios array")
            return None

        # Decode base64 audio and save to cache
        audio_bytes = base64.b64decode(audios[0])
        with open(cache_path, "wb") as f:
            f.write(audio_bytes)

        log.info(f"TTS generated: {len(audio_bytes)} bytes → {cache_path}")
        return cache_path

    except httpx.HTTPStatusError as e:
        log.error(f"Sarvam TTS HTTP error: {e.response.status_code} — {e.response.text}")
        return None
    except Exception as e:
        log.error(f"Sarvam TTS error: {e}", exc_info=True)
        return None


# ── Voice Conversation Logic ─────────────────────────────────────────────────

def init_call(
    call_sid: str,
    session_id: str,
    phone: str,
    lead_score: str,
    treatment_history: Optional[str] = None,
    duration_months: Optional[float] = None,
    age: Optional[str] = None,
) -> VoiceCallState:
    """
    Initialize a voice call state and load the appropriate script.

    Returns the VoiceCallState with the opening script ready.
    """
    script = get_call_script(lead_score=lead_score, treatment=treatment_history)

    state = VoiceCallState(
        session_id=session_id,
        call_sid=call_sid,
        phone=phone,
        lead_score=lead_score,
        treatment_history=treatment_history,
        duration_months=duration_months,
        age=age,
        stage="opening",
        script=script,
    )
    save_voice_state(state)

    log.info(
        f"VOICE INIT | sid={call_sid} | session={session_id} | "
        f"score={lead_score} | treatment={treatment_history}"
    )
    return state


def get_opening_text(state: VoiceCallState) -> str:
    """Get the opening script text for the call."""
    return state.script.get("opening", "Hello, this is Parivar Saathi calling. Is this a good time?")


def process_caller_response(
    call_sid: str,
    caller_text: str,
    openai_client=None,
) -> Tuple[str, bool]:
    """
    Process what the caller said and generate the next response.

    Args:
        call_sid: Twilio call SID
        caller_text: Transcribed speech from caller
        openai_client: Optional OpenAI client for dynamic responses

    Returns:
        (response_text, should_end_call)
    """
    state = get_voice_state(call_sid)
    if not state:
        log.warning(f"No voice state for call_sid={call_sid}")
        return ("Thank you for your time. Goodbye.", True)

    state.turn_count += 1
    caller_text = caller_text.strip()

    log.info(
        f"VOICE IN  | sid={call_sid} | stage={state.stage} | "
        f"turn={state.turn_count} | text={caller_text[:100]!r}"
    )

    # ── Check for objections first ───────────────────────────────────────────
    objection = detect_objection(caller_text)

    if objection:
        log.info(f"VOICE OBJ | sid={call_sid} | type={objection}")

        # Not interested → end immediately
        if objection == OBJECTION_NOT_INTERESTED:
            response = handle_objection(objection, state.lead_score, state.treatment_history)
            goodbye = f"{response['acknowledge']} {response['reframe']} {response['next_step']}"
            state.stage = "ended"
            save_voice_state(state)
            return (goodbye, True)

        # Track repeated objections
        if objection == state.last_objection:
            state.objection_count += 1
        else:
            state.objection_count = 1
            state.last_objection = objection

        # Too many objections on same topic → graceful end
        if state.objection_count >= state.max_objections:
            response = handle_objection(objection, state.lead_score, state.treatment_history)
            goodbye = (
                f"{response['acknowledge']} I understand completely. "
                "We're here whenever you're ready. Thank you for your time."
            )
            state.stage = "ended"
            save_voice_state(state)
            return (goodbye, True)

        # Handle the objection and continue
        response = handle_objection(objection, state.lead_score, state.treatment_history)
        reply = f"{response['acknowledge']} {response['reframe']} {response['next_step']}"
        save_voice_state(state)
        return (reply, response.get("exit_if_repeated", False))

    # ── No objection — advance the call flow ─────────────────────────────────

    # Check for positive/negative signals
    is_positive = _is_positive_response(caller_text)
    is_negative = _is_negative_response(caller_text)

    # If caller says no to soft_close → graceful end
    if state.stage == "soft_close" and is_negative:
        goodbye = (
            "I completely understand. We're here whenever you're ready. "
            "You can reach us on WhatsApp anytime. Take care."
        )
        state.stage = "ended"
        save_voice_state(state)
        return (goodbye, True)

    # If caller says yes to soft_close → great, book it
    if state.stage == "soft_close" and is_positive:
        confirm = (
            "Wonderful. Our counselor will reach out to you shortly to schedule the consultation. "
            "Thank you for your time, and take care."
        )
        state.stage = "ended"
        save_voice_state(state)
        return (confirm, True)

    # ── Dynamic response with OpenAI (if available) ──────────────────────────
    if openai_client and state.stage not in ("opening", "ended"):
        dynamic_response = _generate_dynamic_response(
            openai_client, state, caller_text
        )
        if dynamic_response:
            # Advance to next stage
            next_stage = state.next_stage()
            if next_stage:
                state.stage = next_stage
                # Append the scripted question for the next stage
                scripted_q = state.script.get(next_stage, "")
                if scripted_q:
                    dynamic_response = f"{dynamic_response} {scripted_q}"
            save_voice_state(state)
            return (dynamic_response, False)

    # ── Fallback: advance through scripted flow ──────────────────────────────
    next_stage = state.next_stage()
    if next_stage:
        state.stage = next_stage
        response_text = state.script.get(next_stage, "")
        save_voice_state(state)
        return (response_text, False)

    # All stages exhausted → end call
    goodbye = "Thank you for speaking with us. Our team will follow up with you. Take care."
    state.stage = "ended"
    save_voice_state(state)
    return (goodbye, True)


def _generate_dynamic_response(
    openai_client,
    state: VoiceCallState,
    caller_text: str,
) -> Optional[str]:
    """
    Use OpenAI to generate a natural, empathetic response
    based on what the caller said.
    """
    try:
        system_prompt = (
            "You are a compassionate fertility clinic counselor on a phone call. "
            "The caller has been trying to conceive and you are doing a follow-up call. "
            f"Lead score: {state.lead_score}. "
            f"Treatment history: {state.treatment_history or 'unknown'}. "
            f"Duration trying: {state.duration_months or 'unknown'} months. "
            f"Current call stage: {state.stage}. "
            "\n"
            "RULES:\n"
            "- Be warm, empathetic, and professional\n"
            "- Keep responses under 40 words — this is a phone call, not a chat\n"
            "- Acknowledge what the caller said before moving on\n"
            "- Do NOT use medical jargon\n"
            "- Do NOT make promises or guarantees\n"
            "- Speak naturally as you would on a phone call\n"
            "- If the caller is emotional, prioritize empathy over information\n"
        )

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": caller_text},
            ],
            max_tokens=100,
            temperature=0.7,
        )

        reply = response.choices[0].message.content.strip()
        log.info(f"VOICE AI  | sid={state.call_sid} | reply={reply[:100]!r}")
        return reply

    except Exception as e:
        log.error(f"Voice OpenAI error: {e}", exc_info=True)
        return None


# ── Response classifiers ─────────────────────────────────────────────────────

_POSITIVE_WORDS = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "alright",
    "haan", "haa", "ji", "theek", "bilkul", "zaroor",
    "please", "go ahead", "sounds good", "that works",
    "morning", "evening", "afternoon",
}

_NEGATIVE_WORDS = {
    "no", "nope", "nahi", "na", "not now", "later", "busy",
    "not interested", "don't call", "hang up", "not today",
    "abhi nahi", "baad mein",
}


def _is_positive_response(text: str) -> bool:
    text_lower = text.lower()
    return any(w in text_lower for w in _POSITIVE_WORDS)


def _is_negative_response(text: str) -> bool:
    text_lower = text.lower()
    return any(w in text_lower for w in _NEGATIVE_WORDS)
