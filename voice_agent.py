"""
voice_agent.py
AI Voice Call Agent — Sarvam TTS + Twilio Voice Integration

STRICT CALL FLOW (state machine):
  opening → permission → language → q1 → q2 → q3 → q4 → soft_close → ended

OpenAI is ONLY used for short empathetic fillers (e.g. "samajh gaya", "theek hai").
OpenAI does NOT generate questions or change sequence.

Architecture:
  1. Twilio makes outbound call → /voice webhook answers
  2. Opening line → Sarvam TTS → audio played
  3. Caller speaks → Twilio <Gather speech> transcribes
  4. State machine decides EXACT next line → Sarvam TTS → audio played
  5. Loop until soft_close or exit → outcome recorded
"""

import os
import base64
import logging
import tempfile
import hashlib
from typing import Optional, Tuple
from dataclasses import dataclass, field

import httpx

from call_logic import detect_objection, OBJECTION_NOT_INTERESTED

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


# ── STRICT CALL FLOW DEFINITION ─────────────────────────────────────────────
# Each stage has a FIXED line. No OpenAI decides what to say.
# Order: opening → permission → language → q1 → q2 → q3 → q4 → soft_close

CALL_FLOW = [
    "opening",
    "permission",
    "language",
    "q1_duration",
    "q2_treatment",
    "q3_age",
    "q4_location",
    "soft_close",
]

# Fixed script lines for each stage
SCRIPT = {
    "opening": (
        "नमस्ते, मैं परिवार साथी से बोल रही हूँ। "
        "आपने फर्टिलिटी के सम्बन्ध में इंक्वायरी की थी।"
    ),
    "permission": "क्या अभी बात करने का समय ठीक है?",
    "language": "आप हिंदी में बात करना पसंद करेंगे या इंग्लिश में?",
    "q1_duration": "आप कितने समय से conceive करने की कोशिश कर रहे हैं?",
    "q2_treatment": "क्या आपने पहले कोई ट्रीटमेंट लिया है? जैसे IUI या IVF?",
    "q3_age": "आपकी उम्र क्या है?",
    "q4_location": "आप किस शहर से बात कर रहे हैं?",
    "soft_close": (
        "ठीक है, आपके केस के हिसाब से डॉक्टर से कंसल्ट करना helpful रहेगा। "
        "क्या आप एक consultation schedule करना चाहेंगे?"
    ),
}

# Goodbye / exit lines
GOODBYE_BUSY = "कोई बात नहीं। हम आपको बाद में कॉल करेंगे। अपना ख़्याल रखिए।"
GOODBYE_NOT_INTERESTED = (
    "जी बिल्कुल, मैं आपकी बात का सम्मान करती हूँ। "
    "जब भी ज़रूरत हो, हमारा वॉट्सऐप हमेशा उपलब्ध है। अपना ख़्याल रखिए।"
)
GOODBYE_POSITIVE_CLOSE = (
    "बहुत अच्छा। हमारे काउंसलर जल्द ही आपसे संपर्क करेंगे और अपॉइंटमेंट तय करेंगे। "
    "आपके समय के लिए धन्यवाद। अपना ख़्याल रखिए।"
)
GOODBYE_NEGATIVE_CLOSE = (
    "कोई बात नहीं। जब भी आप तैयार हों, हम यहाँ हैं। "
    "आप कभी भी वॉट्सऐप पर संपर्क कर सकते हैं। अपना ख़्याल रखिए।"
)
GOODBYE_DEFAULT = "आपके समय के लिए धन्यवाद। अपना ख़्याल रखिए।"
REPROMPT = "मुझे सुनाई नहीं दिया। क्या आप दोबारा बोल सकते हैं?"


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

    # Call flow tracking — strict state machine
    stage: str = "opening"
    turn_count: int = 0

    # Collected data from caller
    collected_duration: str = ""
    collected_treatment: str = ""
    collected_age: str = ""
    collected_city: str = ""
    collected_language: str = "hindi"  # default hindi

    def next_stage(self) -> Optional[str]:
        """Returns the next stage in the STRICT call flow, or None if done."""
        try:
            idx = CALL_FLOW.index(self.stage)
            if idx + 1 < len(CALL_FLOW):
                return CALL_FLOW[idx + 1]
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
    Returns path to generated WAV file, or None on failure.
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
    """Initialize a voice call state. Opening is played by /voice/answer."""
    state = VoiceCallState(
        session_id=session_id,
        call_sid=call_sid,
        phone=phone,
        lead_score=lead_score,
        treatment_history=treatment_history,
        duration_months=duration_months,
        age=age,
        stage="opening",
    )
    save_voice_state(state)

    log.info(
        f"VOICE INIT | sid={call_sid} | session={session_id} | "
        f"score={lead_score} | treatment={treatment_history}"
    )
    return state


def get_opening_text(state: VoiceCallState) -> str:
    """
    Get the opening text. This plays TWO lines back-to-back:
    Introduction + Permission question.
    """
    # Combine opening + permission into one TTS block
    # so the first thing caller hears is intro + "kya abhi baat kar sakte hain?"
    opening = SCRIPT["opening"]
    permission = SCRIPT["permission"]
    return f"{opening} {permission}"


def process_caller_response(
    call_sid: str,
    caller_text: str,
    openai_client=None,
) -> Tuple[str, bool]:
    """
    Process caller speech and return EXACT next scripted line.
    State machine controls flow — NO OpenAI question generation.

    Returns: (response_text, should_end_call)
    """
    state = get_voice_state(call_sid)
    if not state:
        log.warning(f"No voice state for call_sid={call_sid}")
        return (GOODBYE_DEFAULT, True)

    state.turn_count += 1
    caller_text = caller_text.strip()

    log.info(
        f"VOICE IN  | sid={call_sid} | stage={state.stage} | "
        f"turn={state.turn_count} | text={caller_text[:100]!r}"
    )

    # ── Check for hard exit signals ─────────────────────────────────────────
    if _is_not_interested(caller_text):
        log.info(f"VOICE EXIT | sid={call_sid} | not_interested")
        state.stage = "ended"
        save_voice_state(state)
        return (GOODBYE_NOT_INTERESTED, True)

    if _is_busy(caller_text):
        log.info(f"VOICE EXIT | sid={call_sid} | busy")
        state.stage = "ended"
        save_voice_state(state)
        return (GOODBYE_BUSY, True)

    # ── State machine: process current stage and advance ────────────────────

    # STAGE: opening (caller responded to intro + permission)
    if state.stage == "opening":
        if _is_negative_response(caller_text):
            state.stage = "ended"
            save_voice_state(state)
            return (GOODBYE_BUSY, True)
        # Permission granted → ask language
        state.stage = "language"
        save_voice_state(state)
        filler = _get_filler(openai_client, caller_text)
        return (f"{filler} {SCRIPT['language']}", False)

    # STAGE: language (caller chose language)
    if state.stage == "language":
        # Store language preference
        text_lower = caller_text.lower()
        if any(w in text_lower for w in ["english", "angrezi", "inglish"]):
            state.collected_language = "english"
        else:
            state.collected_language = "hindi"
        # → Move to Q1
        state.stage = "q1_duration"
        save_voice_state(state)
        filler = _get_filler(openai_client, caller_text)
        return (f"{filler} {SCRIPT['q1_duration']}", False)

    # STAGE: q1_duration
    if state.stage == "q1_duration":
        state.collected_duration = caller_text
        state.stage = "q2_treatment"
        save_voice_state(state)
        filler = _get_filler(openai_client, caller_text)
        return (f"{filler} {SCRIPT['q2_treatment']}", False)

    # STAGE: q2_treatment
    if state.stage == "q2_treatment":
        state.collected_treatment = caller_text
        state.stage = "q3_age"
        save_voice_state(state)
        filler = _get_filler(openai_client, caller_text)
        return (f"{filler} {SCRIPT['q3_age']}", False)

    # STAGE: q3_age
    if state.stage == "q3_age":
        state.collected_age = caller_text
        state.stage = "q4_location"
        save_voice_state(state)
        filler = _get_filler(openai_client, caller_text)
        return (f"{filler} {SCRIPT['q4_location']}", False)

    # STAGE: q4_location
    if state.stage == "q4_location":
        state.collected_city = caller_text
        state.stage = "soft_close"
        save_voice_state(state)
        filler = _get_filler(openai_client, caller_text)
        return (f"{filler} {SCRIPT['soft_close']}", False)

    # STAGE: soft_close (caller responds to consultation offer)
    if state.stage == "soft_close":
        if _is_positive_response(caller_text):
            state.stage = "ended"
            save_voice_state(state)
            return (GOODBYE_POSITIVE_CLOSE, True)
        else:
            state.stage = "ended"
            save_voice_state(state)
            return (GOODBYE_NEGATIVE_CLOSE, True)

    # Fallback — should never reach here
    state.stage = "ended"
    save_voice_state(state)
    return (GOODBYE_DEFAULT, True)


# ── OpenAI: ONLY for short empathetic fillers ───────────────────────────────

def _get_filler(openai_client, caller_text: str) -> str:
    """
    Generate a SHORT empathetic filler (max 8 words) using OpenAI.
    Examples: "समझ गया", "ठीक है", "बिल्कुल", "अच्छा"

    If OpenAI fails or is unavailable, returns a simple default filler.
    This NEVER generates questions or changes the call flow.
    """
    if not openai_client:
        return "अच्छा।"

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "तुम एक फ़ोन काउंसलर हो। कॉलर ने कुछ बोला है। "
                        "तुम्हें सिर्फ़ एक छोटा सा empathetic filler बोलना है। "
                        "जैसे: 'अच्छा', 'समझ गया', 'ठीक है', 'बिल्कुल', 'जी हाँ'। "
                        "सिर्फ़ 2-5 शब्द। कोई सवाल मत पूछो। कोई सलाह मत दो। "
                        "सिर्फ़ हिंदी में। कोई अंग्रेज़ी नहीं।"
                    ),
                },
                {"role": "user", "content": caller_text},
            ],
            max_tokens=20,
            temperature=0.5,
            timeout=5,
        )
        filler = response.choices[0].message.content.strip()
        # Safety: if filler is too long or contains a question mark, discard it
        if len(filler) > 60 or "?" in filler:
            return "अच्छा।"
        log.info(f"FILLER | {filler!r}")
        return filler

    except Exception as e:
        log.warning(f"Filler OpenAI error: {e}")
        return "अच्छा।"


# ── Response classifiers ─────────────────────────────────────────────────────

_POSITIVE_WORDS = {
    "yes", "yeah", "yep", "sure", "ok", "okay", "alright",
    "haan", "haa", "ji", "theek", "bilkul", "zaroor",
    "please", "go ahead", "sounds good", "that works",
    "morning", "evening", "afternoon", "chalo",
}

_NEGATIVE_WORDS = {
    "no", "nope", "nahi", "na", "not now", "later",
    "not today", "abhi nahi", "baad mein",
}

_BUSY_WORDS = {
    "busy", "busy hoon", "abhi nahi", "baad mein call karo",
    "not now", "bad time", "cant talk",
}

_NOT_INTERESTED_WORDS = {
    "not interested", "don't call", "hang up", "nahi chahiye",
    "no thanks", "remove my number", "mat karo call",
}


def _is_positive_response(text: str) -> bool:
    text_lower = text.lower()
    return any(w in text_lower for w in _POSITIVE_WORDS)


def _is_negative_response(text: str) -> bool:
    text_lower = text.lower()
    return any(w in text_lower for w in _NEGATIVE_WORDS)


def _is_busy(text: str) -> bool:
    text_lower = text.lower()
    return any(w in text_lower for w in _BUSY_WORDS)


def _is_not_interested(text: str) -> bool:
    text_lower = text.lower()
    return any(w in text_lower for w in _NOT_INTERESTED_WORDS)
