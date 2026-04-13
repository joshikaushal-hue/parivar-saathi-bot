"""
voice_agent.py
IVF AI Counsellor — Voice Call Agent (LOCKED PRODUCTION VERSION)

This is NOT a chatbot. This is an IVF counsellor on call.

STRICT CALL FLOW (NO DEVIATION):
  opening → permission → language → q1_duration → q2_treatment → q3_age → soft_close → ended

RULES:
  - Female voice ONLY (bol rahi hoon, NEVER bol raha hoon)
  - Language locked after selection (Hindi OR English, no mixing)
  - OpenAI ONLY for 1-word acknowledgements (achha, theek hai, ji)
  - OpenAI NEVER asks questions, changes sequence, or adds content
  - consultation → counselling everywhere
  - No step skipping
"""

import os
import base64
import logging
import tempfile
import hashlib
from typing import Optional, Tuple
from dataclasses import dataclass, field

import httpx

log = logging.getLogger("ivf_engine")

# ── Sarvam TTS Configuration ────────────────────────────────────────────────

SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "")

SARVAM_SPEAKER = os.environ.get("SARVAM_SPEAKER", "ritu")  # Female Hindi voice
SARVAM_LANGUAGE = os.environ.get("SARVAM_LANGUAGE", "hi-IN")
SARVAM_MODEL = "bulbul:v3"
SARVAM_PACE = 0.95
SARVAM_SAMPLE_RATE = 8000  # 8kHz for telephony

AUDIO_CACHE_DIR = os.path.join(tempfile.gettempdir(), "ivf_voice_cache")
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)


# ── STRICT CALL FLOW (6 steps, NO location question) ────────────────────────

CALL_FLOW = [
    "opening",
    "language",
    "q1_duration",
    "q2_treatment",
    "q3_age",
    "soft_close",
    # Phase 3: Booking stages
    "intent_check",
    "slot_offer",
    "slot_time",
    "booking_confirm",
]

# ── HINDI SCRIPT (EXACT — DO NOT MODIFY) ────────────────────────────────────

SCRIPT_HI = {
    "opening": (
        "नमस्ते, मैं परिवार साथी से बोल रही हूँ। "
        "आपने फर्टिलिटी के सम्बन्ध में इंक्वायरी की थी।"
    ),
    "permission": "क्या अभी बात करना ठीक है?",
    "language": "आप हिंदी में बात करना पसंद करेंगे या इंग्लिश में?",
    "q1_duration": "आप कितने समय से conceive करने की कोशिश कर रहे हैं?",
    "q2_treatment": "क्या आपने पहले कोई ट्रीटमेंट लिया है? जैसे IUI या IVF?",
    "q3_age": "आपकी age क्या है?",
    "soft_close": (
        "ठीक है, आपके केस के हिसाब से एक detailed बात करना useful रहेगा। "
        "आप चाहें तो मैं आपके लिए एक काउंसलिंग slot check कर सकती हूँ।"
    ),
    # Phase 3: Booking stages
    "intent_check": (
        "क्या आप seriously आगे बढ़ना चाहते हैं या सिर्फ़ information के लिए देख रहे हैं?"
    ),
    "slot_offer": "",  # dynamically generated based on priority
    "slot_time": "सुबह 11 बजे ठीक रहेगा या दोपहर 3 बजे?",
    "booking_confirm": (
        "बहुत अच्छा। आपकी काउंसलिंग {day} {time} बुक हो गई है। "
        "आपको WhatsApp पर details मिल जाएँगी।"
    ),
}

# ── ENGLISH SCRIPT (EXACT — DO NOT MODIFY) ──────────────────────────────────

SCRIPT_EN = {
    "opening": (
        "Hello, I am calling from Parivar Saathi. "
        "You had enquired about fertility treatment."
    ),
    "permission": "Is this a good time to talk?",
    "language": "Would you prefer to speak in Hindi or English?",
    "q1_duration": "How long have you been trying to conceive?",
    "q2_treatment": "Have you taken any treatment before? Like IUI or IVF?",
    "q3_age": "What is your age?",
    "soft_close": (
        "Based on your case, a detailed discussion would be useful. "
        "I can check a counselling slot for you if you'd like."
    ),
    # Phase 3: Booking stages
    "intent_check": (
        "Would you like to go ahead with a counselling session, or are you just exploring options?"
    ),
    "slot_offer": "",  # dynamically generated based on priority
    "slot_time": "Would 11 AM work, or 3 PM?",
    "booking_confirm": (
        "Your counselling is booked for {day} at {time}. "
        "You'll receive details on WhatsApp."
    ),
}

# ── GOODBYE LINES (HINDI) ───────────────────────────────────────────────────

GOODBYE_BUSY_HI = "कोई बात नहीं। हम आपको बाद में कॉल करेंगे। अपना ख़्याल रखिए।"
GOODBYE_NOT_INTERESTED_HI = (
    "जी बिल्कुल, मैं आपकी बात का सम्मान करती हूँ। "
    "जब भी ज़रूरत हो, हमारा वॉट्सऐप हमेशा उपलब्ध है। अपना ख़्याल रखिए।"
)
GOODBYE_POSITIVE_HI = (
    "बहुत अच्छा। हमारे काउंसलर जल्द ही आपसे संपर्क करेंगे और काउंसलिंग कॉल तय करेंगे। "
    "आपके समय के लिए धन्यवाद। अपना ख़्याल रखिए।"
)
GOODBYE_NEGATIVE_HI = (
    "कोई बात नहीं। जब भी आप तैयार हों, हम यहाँ हैं। "
    "आप कभी भी वॉट्सऐप पर संपर्क कर सकते हैं। अपना ख़्याल रखिए।"
)
GOODBYE_DEFAULT_HI = "आपके समय के लिए धन्यवाद। अपना ख़्याल रखिए।"

# Phase 3: Booking confirmation goodbye
GOODBYE_BOOKED_HI = (
    "बहुत अच्छा। आपकी काउंसलिंग {day} {time} बुक हो गई है। "
    "आपको WhatsApp पर details मिल जाएँगी। अपना ख़्याल रखिए।"
)
GOODBYE_FOLLOW_UP_HI = (
    "कोई बात नहीं। मैं आपको WhatsApp पर पूरी जानकारी भेज देती हूँ। "
    "जब भी आप तैयार हों, बुक कर सकते हैं। अपना ख़्याल रखिए।"
)

# ── GOODBYE LINES (ENGLISH) ─────────────────────────────────────────────────

GOODBYE_BUSY_EN = "No problem. We will call you back later. Take care."
GOODBYE_NOT_INTERESTED_EN = (
    "Absolutely, I respect that. "
    "Whenever you need, our WhatsApp is always available. Take care."
)
GOODBYE_POSITIVE_EN = (
    "Great. Our counsellor will contact you shortly to arrange a counselling call. "
    "Thank you for your time. Take care."
)
GOODBYE_NEGATIVE_EN = (
    "No problem. Whenever you are ready, we are here. "
    "You can reach us anytime on WhatsApp. Take care."
)
GOODBYE_DEFAULT_EN = "Thank you for your time. Take care."

# Phase 3: Booking confirmation goodbye (English)
GOODBYE_BOOKED_EN = (
    "Your counselling is booked for {day} at {time}. "
    "You'll receive details on WhatsApp. Take care."
)
GOODBYE_FOLLOW_UP_EN = (
    "No problem. I will send you the details on WhatsApp. "
    "You can book whenever you are ready. Take care."
)

# ── INTENT RESPONSES (language-locked) ───────────────────────────────────────

INTENT_CALL_LATER_HI = (
    "ठीक है, मैं आपको बाद में कॉल करवा देती हूँ। "
    "आपके लिए कौनसा समय ठीक रहेगा?"
)
INTENT_CALL_LATER_EN = (
    "Sure, I can arrange a call later. "
    "What would be a convenient time for you?"
)

INTENT_SEND_DETAILS_HI = (
    "बिल्कुल, मैं आपको वॉट्सऐप पर details भेज देती हूँ। "
    "आपका यही नंबर सही है?"
)
INTENT_SEND_DETAILS_EN = (
    "Sure, I will send you the details on WhatsApp. "
    "Is this the correct number?"
)

INTENT_NOT_INTERESTED_HI = (
    "ठीक है, अगर आप future में कभी बात करना चाहें तो हम available हैं। "
    "धन्यवाद।"
)
INTENT_NOT_INTERESTED_EN = (
    "Alright, if you ever wish to discuss in future, we are available. "
    "Thank you."
)

# ── REPROMPT ─────────────────────────────────────────────────────────────────

REPROMPT_HI = "मुझे सुनाई नहीं दिया। क्या आप दोबारा बोल सकते हैं?"
REPROMPT_EN = "I didn't catch that. Could you say that again?"

# Exported for voice_routes.py (default Hindi)
REPROMPT = REPROMPT_HI


# ── FIXED FILLERS (no OpenAI needed for these) ──────────────────────────────

_FILLERS_HI = ["अच्छा।", "ठीक है।", "जी।"]
_FILLERS_EN = ["Okay.", "Alright.", "Sure."]
_filler_index = 0  # rotates through fillers


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

    # Call flow — strict state machine
    stage: str = "opening"
    turn_count: int = 0

    # Language lock: "hi" or "en" — set after language question, enforced everywhere
    # Default "en" because opening + language question are in English
    language: str = "en"

    # Collected data
    collected_duration: str = ""
    collected_treatment: str = ""
    collected_age: str = ""

    # Phase 3: Booking data
    lead_priority: str = ""        # high / medium / low
    intent_level: str = ""         # confirmed / exploring / vague
    collected_slot_day: str = ""   # YYYY-MM-DD
    collected_slot_time: str = ""  # HH:MM
    available_slots: list = field(default_factory=list)  # cached slots from booking engine
    booking_done: bool = False     # True after successful booking


# In-memory voice call states (keyed by call_sid)
_voice_states: dict = {}


def get_voice_state(call_sid: str) -> Optional[VoiceCallState]:
    return _voice_states.get(call_sid)


def save_voice_state(state: VoiceCallState) -> None:
    _voice_states[state.call_sid] = state


def delete_voice_state(call_sid: str) -> None:
    _voice_states.pop(call_sid, None)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_script(state: VoiceCallState) -> dict:
    """Return the correct script dict based on language lock."""
    return SCRIPT_EN if state.language == "en" else SCRIPT_HI


def get_tts_language(state: VoiceCallState) -> str:
    """Return Sarvam TTS language code based on state language lock."""
    return "en-IN" if state.language == "en" else "hi-IN"


def _get_goodbye(name: str, state: VoiceCallState) -> str:
    """Return the correct goodbye line based on language lock."""
    if state.language == "en":
        return {
            "busy": GOODBYE_BUSY_EN,
            "not_interested": GOODBYE_NOT_INTERESTED_EN,
            "positive": GOODBYE_POSITIVE_EN,
            "negative": GOODBYE_NEGATIVE_EN,
            "default": GOODBYE_DEFAULT_EN,
        }.get(name, GOODBYE_DEFAULT_EN)
    return {
        "busy": GOODBYE_BUSY_HI,
        "not_interested": GOODBYE_NOT_INTERESTED_HI,
        "positive": GOODBYE_POSITIVE_HI,
        "negative": GOODBYE_NEGATIVE_HI,
        "default": GOODBYE_DEFAULT_HI,
    }.get(name, GOODBYE_DEFAULT_HI)


def _get_filler(state: VoiceCallState) -> str:
    """
    Return a SHORT fixed filler. Rotates through 3 options.
    NO OpenAI call. NO long sentences. NO questions.
    Language-locked.
    """
    global _filler_index
    fillers = _FILLERS_EN if state.language == "en" else _FILLERS_HI
    filler = fillers[_filler_index % len(fillers)]
    _filler_index += 1
    return filler


# ── Sarvam TTS ───────────────────────────────────────────────────────────────

def _audio_cache_path(text: str, language: str = "hi-IN") -> str:
    # Include language in hash so hi-IN and en-IN don't collide
    cache_key = f"{language}:{text}"
    text_hash = hashlib.md5(cache_key.encode()).hexdigest()
    return os.path.join(AUDIO_CACHE_DIR, f"{text_hash}.wav")


def text_to_speech(text: str, language: str = None) -> Optional[str]:
    """Convert text to speech using Sarvam AI TTS.

    language: "en-IN" for English, "hi-IN" for Hindi.
              Defaults to hi-IN if not specified.
    """
    if not SARVAM_API_KEY:
        log.warning("SARVAM_API_KEY not set — TTS unavailable")
        return None

    lang = language or SARVAM_LANGUAGE

    cache_path = _audio_cache_path(text, lang)
    if os.path.exists(cache_path):
        log.debug(f"TTS cache hit: {cache_path}")
        return cache_path

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
    """Initialize voice call state. Opening played by /voice/answer."""
    state = VoiceCallState(
        session_id=session_id,
        call_sid=call_sid,
        phone=phone,
        lead_score=lead_score,
        treatment_history=treatment_history,
        duration_months=duration_months,
        age=age,
        stage="opening",
        language="en",  # default English; locked after language question
    )
    save_voice_state(state)
    log.info(
        f"VOICE INIT | sid={call_sid} | session={session_id} | "
        f"score={lead_score} | treatment={treatment_history}"
    )
    return state


def get_opening_text(state: VoiceCallState) -> str:
    """
    Opening = English introduction + permission in ONE TTS block.
    Always in English (language not yet selected).
    """
    return (
        "Hello, this is a call from Parivar Saathi. "
        "You had enquired about fertility treatment. "
        "Is this a good time to talk?"
    )


def process_caller_response(
    call_sid: str,
    caller_text: str,
    openai_client=None,
) -> Tuple[str, bool]:
    """
    STRICT state machine. Returns EXACT next scripted line.
    OpenAI is NOT used here at all.
    Returns: (response_text, should_end_call)
    """
    state = get_voice_state(call_sid)
    if not state:
        log.warning(f"No voice state for call_sid={call_sid}")
        return (GOODBYE_DEFAULT_HI, True)

    state.turn_count += 1
    caller_text = caller_text.strip()

    log.info(
        f"VOICE IN  | sid={call_sid} | stage={state.stage} | "
        f"lang={state.language} | turn={state.turn_count} | "
        f"text={caller_text[:100]!r}"
    )

    script = _get_script(state)

    log.info(
        f"STATE DBG | sid={call_sid} | stage={state.stage} | "
        f"language={state.language} | tts={get_tts_language(state)}"
    )

    # ── INTENT DETECTION (runs BEFORE flow, at EVERY stage) ─────────────────
    # Priority: not_interested → send_details → call_later
    # Uses keyword matching ONLY. No OpenAI.

    if _is_not_interested(caller_text):
        log.info(f"INTENT | sid={call_sid} | not_interested")
        state.stage = "ended"
        save_voice_state(state)
        if state.language == "en":
            return (INTENT_NOT_INTERESTED_EN, True)
        return (INTENT_NOT_INTERESTED_HI, True)

    if _is_send_details(caller_text):
        log.info(f"INTENT | sid={call_sid} | send_details")
        state.stage = "ended"
        save_voice_state(state)
        if state.language == "en":
            return (INTENT_SEND_DETAILS_EN, True)
        return (INTENT_SEND_DETAILS_HI, True)

    if _is_call_later(caller_text):
        log.info(f"INTENT | sid={call_sid} | call_later")
        state.stage = "ended"
        save_voice_state(state)
        if state.language == "en":
            return (INTENT_CALL_LATER_EN, True)
        return (INTENT_CALL_LATER_HI, True)

    # ── STAGE: opening (caller responded to intro + permission) ─────────────
    if state.stage == "opening":
        if _is_negative_response(caller_text):
            state.stage = "ended"
            save_voice_state(state)
            # Opening is always English, so respond in English
            return (INTENT_CALL_LATER_EN, True)
        # Permission granted → ask language (in English — language not yet chosen)
        state.stage = "language"
        save_voice_state(state)
        return ("Would you prefer to speak in Hindi or English?", False)

    # ── STAGE: language (caller chose language) ─────────────────────────────
    if state.stage == "language":
        text_lower = caller_text.lower()
        # Twilio hi-IN transcribes "English" as "इंग्लिश" in Devanagari
        _ENGLISH_KEYWORDS = [
            "english", "angrezi", "inglish", "eng",
            "इंग्लिश", "इंगलिश", "अंग्रेज़ी", "अंग्रेजी", "इङ्ग्लिश",
        ]
        if any(w in text_lower for w in _ENGLISH_KEYWORDS) or any(w in caller_text for w in _ENGLISH_KEYWORDS):
            state.language = "en"
            log.info(f"LANG LOCK | sid={call_sid} | ENGLISH detected from: {caller_text!r}")
        else:
            state.language = "hi"
            log.info(f"LANG LOCK | sid={call_sid} | HINDI (default) from: {caller_text!r}")
        # Language is now LOCKED. All future lines use this language.
        script = _get_script(state)  # refresh script for new language
        state.stage = "q1_duration"
        save_voice_state(state)
        filler = _get_filler(state)
        return (f"{filler} {script['q1_duration']}", False)

    # ── STAGE: q1_duration ──────────────────────────────────────────────────
    if state.stage == "q1_duration":
        state.collected_duration = caller_text
        state.stage = "q2_treatment"
        save_voice_state(state)
        filler = _get_filler(state)
        return (f"{filler} {script['q2_treatment']}", False)

    # ── STAGE: q2_treatment ─────────────────────────────────────────────────
    if state.stage == "q2_treatment":
        state.collected_treatment = caller_text
        state.stage = "q3_age"
        save_voice_state(state)
        filler = _get_filler(state)
        return (f"{filler} {script['q3_age']}", False)

    # ── STAGE: q3_age ───────────────────────────────────────────────────────
    if state.stage == "q3_age":
        state.collected_age = caller_text
        state.stage = "soft_close"
        save_voice_state(state)
        filler = _get_filler(state)
        return (f"{filler} {script['soft_close']}", False)

    # ── STAGE: soft_close (counselling offer → leads to booking) ─────────
    if state.stage == "soft_close":
        if _is_negative_response(caller_text):
            # Clearly negative → WhatsApp follow-up, end call
            state.stage = "ended"
            save_voice_state(state)
            if state.language == "en":
                return (GOODBYE_FOLLOW_UP_EN.format(day="", time=""), True)
            return (GOODBYE_FOLLOW_UP_HI.format(day="", time=""), True)
        # Positive OR ambiguous → move to intent validation (benefit of the doubt)
        # This ensures "yes" / "ok" / any non-negative response proceeds to booking
        state.stage = "intent_check"
        save_voice_state(state)
        return (script["intent_check"], False)

    # ── STAGE: intent_check (filter serious vs casual) ────────────────────
    if state.stage == "intent_check":
        intent = _classify_intent(caller_text)
        state.intent_level = intent

        if intent == "vague":
            # Not serious → WhatsApp info, end call gracefully
            state.stage = "ended"
            save_voice_state(state)
            if state.language == "en":
                return (GOODBYE_FOLLOW_UP_EN.format(day="", time=""), True)
            return (GOODBYE_FOLLOW_UP_HI.format(day="", time=""), True)

        # confirmed or exploring → calculate priority and offer slot
        from booking import calculate_lead_priority, get_slot_offer_text

        state.lead_priority = calculate_lead_priority(
            age=state.collected_age or state.age,
            duration_months=_parse_duration_months(state.collected_duration) or state.duration_months,
            treatment_history=state.collected_treatment or state.treatment_history,
        )

        slot_text, slots = get_slot_offer_text(state.lead_priority, state.language)
        state.available_slots = slots
        state.stage = "slot_offer"
        save_voice_state(state)

        log.info(
            f"BOOKING FLOW | sid={call_sid} | intent={intent} | "
            f"priority={state.lead_priority} | slots={len(slots)}"
        )
        return (slot_text, False)

    # ── STAGE: slot_offer (caller picks day) ──────────────────────────────
    if state.stage == "slot_offer":
        if _is_negative_response(caller_text):
            # Don't want to book now → follow-up
            state.stage = "ended"
            save_voice_state(state)
            if state.language == "en":
                return (GOODBYE_FOLLOW_UP_EN.format(day="", time=""), True)
            return (GOODBYE_FOLLOW_UP_HI.format(day="", time=""), True)

        # Parse day preference
        chosen_day = _parse_slot_day(caller_text, state.available_slots)
        state.collected_slot_day = chosen_day

        # Also check if they mentioned a time in the same response
        chosen_time = ""
        t = caller_text.lower()
        if any(w in t for w in _TIME_MORNING_WORDS) or any(w in t for w in _TIME_AFTERNOON_WORDS):
            chosen_time = _parse_slot_time(caller_text)
            state.collected_slot_time = chosen_time

        if chosen_time:
            # They gave both day and time — skip to confirm
            state.stage = "booking_confirm"
            save_voice_state(state)
            return _do_booking_confirm(state, call_sid)

        # Ask for time preference
        state.stage = "slot_time"
        save_voice_state(state)
        return (script["slot_time"], False)

    # ── STAGE: slot_time (caller picks time) ──────────────────────────────
    if state.stage == "slot_time":
        state.collected_slot_time = _parse_slot_time(caller_text)
        state.stage = "booking_confirm"
        save_voice_state(state)
        return _do_booking_confirm(state, call_sid)

    # ── STAGE: booking_confirm (already handled by _do_booking_confirm) ───
    if state.stage == "booking_confirm":
        # If we somehow land here (shouldn't), end gracefully
        state.stage = "ended"
        save_voice_state(state)
        return (_get_goodbye("default", state), True)

    # Fallback
    state.stage = "ended"
    save_voice_state(state)
    return (_get_goodbye("default", state), True)


# ── Phase 3: Booking confirmation helper ─────────────────────────────────────

def _do_booking_confirm(state: VoiceCallState, call_sid: str) -> tuple:
    """
    Create the booking and return the confirmation text.
    Returns: (response_text, should_end_call=True)
    """
    from booking import create_booking, send_whatsapp_confirmation

    day = state.collected_slot_day
    time_slot = state.collected_slot_time

    # Create booking in DB
    booking_ok = create_booking(
        session_id=state.session_id,
        phone=state.phone,
        booking_date=day,
        booking_time=time_slot,
        lead_priority=state.lead_priority,
        intent_level=state.intent_level,
    )

    if booking_ok:
        state.booking_done = True
        save_voice_state(state)

        # Send WhatsApp confirmation to patient (non-blocking)
        try:
            send_whatsapp_confirmation(
                phone=state.phone,
                booking_date=day,
                booking_time=time_slot,
                language=state.language,
            )
        except Exception as e:
            log.warning(f"WA confirm failed (non-blocking): {e}")

        # Notify counselor about new booking (non-blocking)
        try:
            from booking import notify_counselor
            notify_counselor(
                session_id=state.session_id,
                phone=state.phone,
                booking_date=day,
                booking_time=time_slot,
                lead_priority=state.lead_priority,
                collected_data={
                    "age": state.collected_age or state.age,
                    "duration_months": _parse_duration_months(state.collected_duration) or state.duration_months,
                    "treatment_history": state.collected_treatment or state.treatment_history,
                },
            )
        except Exception as e:
            log.warning(f"Counselor notify failed (non-blocking): {e}")

    # Build day/time labels for speech
    if state.language == "en":
        from booking import _day_label_en, _time_label_en
        from datetime import datetime
        try:
            dt = datetime.strptime(day, "%Y-%m-%d")
            day_label = _day_label_en(datetime.now(), dt)
        except ValueError:
            day_label = day
        time_label = _time_label_en(time_slot)
        goodbye = GOODBYE_BOOKED_EN.format(day=day_label, time=time_label)
    else:
        from booking import _day_label_hi, _time_label_hi
        from datetime import datetime
        try:
            dt = datetime.strptime(day, "%Y-%m-%d")
            day_label = _day_label_hi(datetime.now(), dt)
        except ValueError:
            day_label = day
        time_label = _time_label_hi(time_slot)
        goodbye = GOODBYE_BOOKED_HI.format(day=day_label, time=time_label)

    log.info(
        f"BOOKING DONE | sid={call_sid} | session={state.session_id} | "
        f"date={day} | time={time_slot} | priority={state.lead_priority}"
    )

    state.stage = "ended"
    save_voice_state(state)
    return (goodbye, True)


def _parse_duration_months(duration_text: str) -> Optional[float]:
    """Parse duration text to months. E.g., '2 years' → 24, '6 months' → 6."""
    if not duration_text:
        return None
    import re
    t = duration_text.lower()

    # Try to find "X year" patterns
    year_match = re.search(r"(\d+)\s*(?:year|saal|sal|yr)", t)
    if year_match:
        return float(year_match.group(1)) * 12

    # Try "X month" patterns
    month_match = re.search(r"(\d+)\s*(?:month|mahine|mahina|mah)", t)
    if month_match:
        return float(month_match.group(1))

    # Just a number — assume months if < 10, years if >= 10
    num_match = re.search(r"(\d+)", t)
    if num_match:
        n = int(num_match.group(1))
        return n * 12 if n < 10 else float(n)

    return None


# ── Response classifiers ─────────────────────────────────────────────────────

_POSITIVE_WORDS = {
    "yes", "yeah", "yep", "sure", "ok", "okay", "alright",
    "haan", "haa", "ji", "theek", "bilkul", "zaroor",
    "please", "go ahead", "sounds good", "that works",
    "morning", "evening", "afternoon", "chalo", "kar do",
    # Hindi Devanagari (Twilio hi-IN ASR may transcribe in script)
    "हाँ", "हां", "हा", "जी", "ठीक", "बिल्कुल", "ज़रूर", "जरूर",
    "चलो", "कर दो", "हाँ जी", "जी हाँ", "ठीक है",
}

_NEGATIVE_WORDS = {
    "no", "nope", "nahi", "na", "not now", "later",
    "not today", "abhi nahi", "baad mein",
    # Hindi Devanagari
    "नहीं", "ना", "नही", "अभी नहीं", "बाद में",
}

_NOT_INTERESTED_WORDS = {
    "not interested", "don't call", "hang up", "nahi chahiye",
    "no thanks", "remove my number", "mat karo call",
    "interested nahi",
}

_CALL_LATER_WORDS = {
    "baad mein", "baad me call", "abhi busy", "call later",
    "later", "not now", "busy", "bad time", "cant talk",
    "busy hoon", "baad mein call karo",
}

_SEND_DETAILS_WORDS = {
    "details bhejo", "whatsapp karo", "info bhejo",
    "send details", "message me", "whatsapp par bhejo",
    "details send", "send info", "whatsapp bhejo",
}

# Phase 3: Intent classification keywords
_INTENT_CONFIRMED_WORDS = {
    "yes", "haan", "ji", "bilkul", "zaroor", "counselling", "counsellor",
    "seriously", "book", "appointment", "ready", "tayyar",
    "chahiye", "karna hai", "definitely", "sure",
    "please book", "book karo", "haan ji", "jaroor",
    # Hindi Devanagari
    "हाँ", "हां", "जी", "बिल्कुल", "ज़रूर", "जरूर", "तैयार",
    "चाहिए", "करना है", "हाँ जी", "जी हाँ", "बुक करो",
}
_INTENT_VAGUE_WORDS = {
    "dekhte hain", "sochenge", "baad mein", "maybe", "not sure",
    "info chahiye", "sirf info", "just information", "exploring",
    "just asking", "pata karna tha", "dekhna tha", "soochte hain",
    "abhi nahi", "pata nahi", "let me think",
}

# Phase 3: Slot day parsing keywords
_DAY_TOMORROW_WORDS = {
    "kal", "tomorrow", "next day", "agla din", "kal ka",
}
_DAY_AFTER_TOMORROW_WORDS = {
    "parson", "parso", "day after", "day after tomorrow",
    "uske baad", "agla",
}
_TIME_MORNING_WORDS = {
    "11", "morning", "subah", "gyarah", "eleven", "11 am",
    "subah ka", "morning time",
}
_TIME_AFTERNOON_WORDS = {
    "3", "afternoon", "dopahar", "teen", "three", "3 pm",
    "dopahar ka", "afternoon time", "15",
}


def _is_positive_response(text: str) -> bool:
    return any(w in text.lower() for w in _POSITIVE_WORDS)


def _is_negative_response(text: str) -> bool:
    return any(w in text.lower() for w in _NEGATIVE_WORDS)


def _is_call_later(text: str) -> bool:
    return any(w in text.lower() for w in _CALL_LATER_WORDS)


def _is_send_details(text: str) -> bool:
    return any(w in text.lower() for w in _SEND_DETAILS_WORDS)


def _is_not_interested(text: str) -> bool:
    return any(w in text.lower() for w in _NOT_INTERESTED_WORDS)


def _classify_intent(text: str) -> str:
    """
    Classify booking intent: 'confirmed', 'exploring', or 'vague'.
    IMPORTANT: Check vague FIRST — people who say "sirf info" or "dekhte hain"
    should NOT be booked even if other positive words match.
    """
    t = text.lower()
    # Check vague/exploring signals FIRST (higher priority)
    if any(w in t for w in _INTENT_VAGUE_WORDS):
        return "vague"
    if any(w in t for w in _INTENT_CONFIRMED_WORDS):
        return "confirmed"
    # If positive general response, treat as confirmed
    if _is_positive_response(text):
        return "confirmed"
    return "exploring"


def _parse_slot_day(text: str, available_slots: list) -> str:
    """Parse caller's day preference into a YYYY-MM-DD date."""
    t = text.lower()

    if any(w in t for w in _DAY_TOMORROW_WORDS):
        # Find first slot that is tomorrow
        from datetime import datetime, timedelta
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        for slot in available_slots:
            if slot["date"] == tomorrow:
                return tomorrow

    if any(w in t for w in _DAY_AFTER_TOMORROW_WORDS):
        from datetime import datetime, timedelta
        day_after = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        for slot in available_slots:
            if slot["date"] == day_after:
                return day_after

    # Default: return first available slot's date
    if available_slots:
        return available_slots[0]["date"]
    return ""


def _parse_slot_time(text: str) -> str:
    """Parse caller's time preference into HH:MM format."""
    t = text.lower()
    if any(w in t for w in _TIME_MORNING_WORDS):
        return "11:00"
    if any(w in t for w in _TIME_AFTERNOON_WORDS):
        return "15:00"
    # Default to morning
    return "11:00"
