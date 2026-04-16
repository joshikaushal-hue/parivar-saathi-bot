"""Global configuration — all values come from env with safe defaults."""
import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
TTS_DIR = STATIC_DIR / "tts"

# Public URL (set via env on Render or ngrok locally)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

# Twilio ASR / Gather tuning
TWILIO_LANGUAGE = os.getenv("TWILIO_LANGUAGE", "hi-IN")
TWILIO_SPEECH_TIMEOUT = os.getenv("TWILIO_SPEECH_TIMEOUT", "2")  # string: "auto" or digits
TWILIO_GATHER_TIMEOUT = int(os.getenv("TWILIO_GATHER_TIMEOUT", "5"))

# Session
SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "30"))
MAX_RETRIES_PER_STATE = int(os.getenv("MAX_RETRIES_PER_STATE", "2"))

# Lead scoring thresholds
AGE_THRESHOLD = 30
AGE_BONUS = 2
DURATION_THRESHOLD_YEARS = 2
DURATION_BONUS = 3
PRIOR_IVF_BONUS = 3

# Category thresholds
CATEGORY_HIGH_MIN = 6
CATEGORY_MEDIUM_MIN = 3
