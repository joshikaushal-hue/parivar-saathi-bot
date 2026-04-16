"""
TTS cache — returns URLs to pre-generated MP3 files served by FastAPI
under /static/tts/. No runtime TTS API calls. This is the whole point.

All audio is pre-generated ONCE via scripts/generate_tts.py.
"""
from typing import Optional
from app.state_machine.states import State
from app.config import PUBLIC_BASE_URL


# Main question prompts per state
_STATE_TO_FILE = {
    State.GREETING:      "greeting.wav",
    State.ASK_AGE:       "ask_age.wav",
    State.ASK_DURATION:  "ask_duration.wav",
    State.ASK_TREATMENT: "ask_treatment.wav",
    State.CLOSE:         None,  # CLOSE uses category-specific audio
}

# Retry prompts (shorter, clearer re-phrasings)
_RETRY_FILE = {
    State.ASK_AGE:       "retry_age.wav",
    State.ASK_DURATION:  "retry_duration.wav",
    State.ASK_TREATMENT: "retry_treatment.wav",
}

# Final close audio depending on lead score
_CATEGORY_FILE = {
    "HIGH":   "close_high.wav",
    "MEDIUM": "close_medium.wav",
    "LOW":    "close_low.wav",
}

ACK_FILE = "ack.wav"
GOODBYE_FILE = "goodbye.wav"
ERROR_FILE = "error.wav"


def _url(filename: str) -> str:
    return f"{PUBLIC_BASE_URL}/static/tts/{filename}"


def ack_url() -> str:
    """The 'instant acknowledgement' ping played the moment the user stops talking."""
    return _url(ACK_FILE)


def state_url(state: State) -> Optional[str]:
    f = _STATE_TO_FILE.get(state)
    return _url(f) if f else None


def retry_url(state: State) -> Optional[str]:
    f = _RETRY_FILE.get(state)
    return _url(f) if f else None


def close_url(category: str) -> str:
    f = _CATEGORY_FILE.get(category.upper(), _CATEGORY_FILE["MEDIUM"])
    return _url(f)


def goodbye_url() -> str:
    return _url(GOODBYE_FILE)


def error_url() -> str:
    return _url(ERROR_FILE)
