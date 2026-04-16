# IVF Voice Engine v4 — Low-Latency Rebuild

Deterministic, state-machine driven IVF qualification bot.
**No GPT. No runtime TTS. Sub-second turn latency.**

## Why this is fast

Old flow (3–8s per turn):
```
user speech → Twilio STT → FastAPI → GPT-4o-mini → Sarvam TTS → serve audio → Twilio fetch → play
                                     └─ 0.5–2s ─┘  └─ 1–3s ─┘   └── 0.5–1s ──┘
```

New flow (≈300 ms per turn, dominated by Twilio's own processing):
```
user speech → Twilio STT → FastAPI regex parser → pre-generated MP3 URL → play
                           └────── ~5 ms ──────┘
```

Every standard prompt is pre-generated ONCE via Sarvam and cached as MP3. The
FastAPI app never calls Sarvam or GPT during a live call.

## Folder structure

```
v4-lowlatency/
├── app/
│   ├── main.py                  # FastAPI app + lifespan + /health
│   ├── config.py                # env vars + thresholds
│   ├── routes/
│   │   └── voice.py             # /voice/incoming, /voice/respond, /voice/status
│   ├── services/
│   │   ├── session_manager.py   # thread-safe in-memory session store
│   │   ├── scoring.py           # deterministic lead scorer
│   │   └── nlu.py               # Twilio ASR hints per state
│   ├── state_machine/
│   │   ├── states.py            # State enum + forward order
│   │   ├── validators.py        # parse_age, parse_duration_months, parse_treatment
│   │   └── machine.py           # process_input() + force_advance()
│   ├── tts/
│   │   └── cache.py             # State → MP3 URL mapping
│   ├── models/
│   │   └── session.py           # Session + LeadData dataclasses
│   └── utils/
│       └── twiml_builder.py     # build_gather() + build_play_and_hangup()
├── scripts/
│   ├── generate_tts.py          # One-time: builds every static MP3 via Sarvam
│   └── place_outbound_call.py   # Helper to trigger an outbound test call
├── static/
│   └── tts/                     # Pre-generated MP3s land here
├── tests/
│   ├── test_validators.py
│   └── test_scoring.py
├── requirements.txt
├── .env.example
└── README.md
```

## States

```
GREETING → ASK_AGE → ASK_DURATION → ASK_TREATMENT → QUALIFY → CLOSE → END
```

Retry budget: 2 attempts per state (configurable via `MAX_RETRIES_PER_STATE`).
Exhausted retry → drop that field, advance. Worst case we reach CLOSE with
partial data and still score + route.

## Lead scoring

| Signal                  | Points |
|-------------------------|--------|
| Age ≥ 30                | +2     |
| Trying ≥ 2 years        | +3     |
| Prior IVF               | +3     |

| Category | Score range |
|----------|-------------|
| LOW      | 0–2         |
| MEDIUM   | 3–5         |
| HIGH     | 6–8         |

Category drives which `close_*.mp3` plays (senior counsellor callback for HIGH,
WhatsApp follow-up for LOW).

## Quick start (local)

```bash
# 1. install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. generate static audio ONCE (needs Sarvam key + ffmpeg)
cp .env.example .env
export SARVAM_API_KEY=sk_xxx
python scripts/generate_tts.py
# → populates static/tts/*.mp3

# 3. run the app
export PUBLIC_BASE_URL=https://<your-ngrok>.ngrok.app
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 4. expose
ngrok http 8000
```

## Twilio webhook setup

In the Twilio console for your phone number:

| Event                | URL                                        | Method |
|----------------------|--------------------------------------------|--------|
| **A CALL COMES IN**  | `{PUBLIC_BASE_URL}/voice/incoming`         | POST   |
| **CALL STATUS CHANGES** | `{PUBLIC_BASE_URL}/voice/status`        | POST   |

For outbound test calls:
```bash
export TWILIO_ACCOUNT_SID=...
export TWILIO_AUTH_TOKEN=...
export TWILIO_NUMBER=+1...
export PUBLIC_BASE_URL=https://<your-app>.onrender.com
python scripts/place_outbound_call.py +919831844401
```

## Debug endpoints

- `GET /health` — `{status, active_sessions}`
- `GET /voice/sessions` — all in-memory sessions
- `GET /voice/sessions/{call_sid}` — one session with full turn history

## Tests

```bash
pip install pytest
python -m pytest -q
```

## Production hardening checklist

- [ ] Replace `InMemorySessionStore` with Redis (needed once you scale to >1 worker)
- [ ] Add `TwilioRequestValidator` middleware (verify webhook signatures)
- [ ] Protect `/voice/sessions*` with auth
- [ ] Persist each completed session to SQL/Postgres for CRM + compliance
- [ ] Pin ASR `speechTimeout` per state (age = 2s, treatment = 3s)
- [ ] CDN-host the MP3s (Cloudflare R2 / S3) so Twilio fetches are always fast
- [ ] Add a `/voice/transfer` route for HUMAN_ESCALATION (`<Dial>` counsellor)

## What this does NOT do (yet)

- No LLM acknowledgements — tone is fixed/canned
- No free-form objections handling — user going off-script hits retry then force-advance
- No barge-in mid-question on the **ack** (only on the question itself)
- No multi-worker safety (sessions live in process memory)

Those are intentional trade-offs for latency. Add them back once you see real
call logs where they're actually needed.
