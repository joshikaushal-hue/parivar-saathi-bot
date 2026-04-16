"""
One-time TTS generator. Pre-creates every static MP3 used by the voice bot.
Run once at deploy time (or whenever a prompt changes). At runtime the
FastAPI app NEVER calls Sarvam — it only serves these files.

Requirements:
  pip install requests
  ffmpeg on PATH (for WAV → MP3 conversion)

Usage:
  export SARVAM_API_KEY=sk_xxx
  python scripts/generate_tts.py
"""
from __future__ import annotations
import base64
import os
import subprocess
import sys
from pathlib import Path

import requests


SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_URL = "https://api.sarvam.ai/text-to-speech"

OUT_DIR = Path(__file__).resolve().parent.parent / "static" / "tts"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------
# Script — simple, short Hindi (in Roman for Sarvam's hi-IN model)
# Tone: warm, concise, 1 sentence each.
# ---------------------------------------------------------------
PROMPTS = {
    # Instant acknowledgement ping (100–300 ms). Plays the moment the
    # user stops speaking — kills dead-air.
    "ack.mp3": "Theek hai.",

    # Main flow
    "greeting.mp3": (
        "Namaste, main Parivar Saathi se bol rahi hoon. "
        "IVF aur fertility ke baare mein do-teen sawaal poochhungi. "
        "Bas ek minute lagega."
    ),
    "ask_age.mp3": "Aapki umar kitni hai?",
    "ask_duration.mp3": "Aap kitne saal se baccha plan kar rahe hain?",
    "ask_treatment.mp3": (
        "Kya aap pehle kabhi IVF ya IUI treatment karwaa chuke hain? "
        "Haan ya nahi?"
    ),

    # Retry prompts — shorter, clearer
    "retry_age.mp3": "Kripya umar sirf numbers mein batayein. Jaise, tees.",
    "retry_duration.mp3": "Kitne saal ya mahine se plan kar rahe hain?",
    "retry_treatment.mp3": "IVF ya IUI pehle karvaaya hai? Haan ya nahi.",

    # Close — category specific
    "close_high.mp3": (
        "Dhanyavaad. Aapki jaankari ke hisaab se, hamari senior counsellor "
        "aapko kal subah call karengi. Shubh din."
    ),
    "close_medium.mp3": (
        "Dhanyavaad. Aapki detail hum note kar liye hain. "
        "Hamari team aapko jald contact karegi. Shubh din."
    ),
    "close_low.mp3": (
        "Dhanyavaad aapke samay ke liye. Aur jaankari ke liye "
        "hum WhatsApp par bhej denge. Shubh din."
    ),

    "goodbye.mp3": "Shubh din.",
    "error.mp3": (
        "Maaf kijiye, kuch takneeki samasya aa gayi hai. "
        "Hum aapko thodi der mein dobara call karenge."
    ),
}


def synthesize(text: str, out_path: Path) -> bool:
    if not SARVAM_API_KEY:
        print("ERROR: SARVAM_API_KEY env var is not set")
        return False

    payload = {
        "inputs": [text],
        "target_language_code": "hi-IN",
        "speaker": "anushka",
        "model": "bulbul:v2",
        "pitch": 0,
        "pace": 0.95,
        "loudness": 1.1,
        "speech_sample_rate": 22050,
        "enable_preprocessing": True,
    }
    headers = {
        "Content-Type": "application/json",
        "api-subscription-key": SARVAM_API_KEY,
    }

    r = requests.post(SARVAM_URL, json=payload, headers=headers, timeout=30)
    if r.status_code != 200:
        print(f"FAIL {out_path.name}: HTTP {r.status_code}: {r.text[:200]}")
        return False

    data = r.json()
    audio_b64 = (data.get("audios") or [None])[0]
    if not audio_b64:
        print(f"FAIL {out_path.name}: no audio in response {data}")
        return False

    # Sarvam returns WAV (base64). Write WAV, then convert to MP3 via ffmpeg.
    wav_path = out_path.with_suffix(".wav")
    wav_path.write_bytes(base64.b64decode(audio_b64))

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(wav_path),
                "-codec:a", "libmp3lame", "-b:a", "64k",
                str(out_path),
            ],
            check=True,
            capture_output=True,
        )
        wav_path.unlink(missing_ok=True)
        print(f"OK   {out_path.name}")
        return True
    except FileNotFoundError:
        print(f"WARN {out_path.name}: ffmpeg not on PATH — kept .wav. "
              f"Install ffmpeg and re-run, or update tts/cache.py to use .wav URLs.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"FAIL {out_path.name}: ffmpeg error {e.stderr.decode()[:200]}")
        return False


def main():
    if not SARVAM_API_KEY:
        print("ERROR: export SARVAM_API_KEY=... before running.")
        sys.exit(1)

    for fname, text in PROMPTS.items():
        synthesize(text, OUT_DIR / fname)

    print(f"\nDone. {len(list(OUT_DIR.glob('*.mp3')))} MP3 files in {OUT_DIR}")


if __name__ == "__main__":
    main()
