# IVF AI Call Conversation Engine (CLI Prototype)

A deterministic, state-driven AI conversation engine for IVF lead qualification.
Simulates a junior IVF counselor using structured state transitions and OpenAI.

---

## Architecture

```
main.py           — CLI entry point, interactive loop, test runner
state_machine.py  — State definitions, lead scoring, action logic
api_handler.py    — OpenAI API calls with retry + JSON validation
input_parser.py   — Deterministic duration/age/treatment extractors
logger.py         — JSON-lines conversation logging
logs/             — Auto-created log directory
```

## State Machine

```
S1 (Intro) → S2 (Duration) → S3 (Age) → S4 (Treatment) → S5 (Closing)
```

| State | Purpose |
|-------|---------|
| S1    | Greet and ask permission to continue |
| S2    | Extract how long trying to conceive |
| S3    | Extract age or age range |
| S4    | Extract prior treatment history |
| S5    | Score lead and decide action |

## Lead Classification

| Score | Criteria |
|-------|----------|
| Hot   | IVF done OR trying > 3 years |
| Warm  | Trying 1–3 years |
| Cold  | Trying < 1 year |

## Actions

| Action   | When |
|----------|------|
| transfer | Hot lead → connect with specialist |
| continue | Warm lead → send resources + follow-up |
| end      | Cold lead → thank and close |

---

## Setup

### 1. Prerequisites
- Python 3.9+
- OpenAI API key

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set API key

Option A — `.env` file (recommended):
```bash
echo "OPENAI_API_KEY=sk-..." > .env
```

Option B — environment variable:
```bash
export OPENAI_API_KEY=sk-...
```

### 4. Run interactive mode

```bash
python main.py
```

### 5. Run all test scenarios

```bash
python main.py --test
```

### 6. Run a specific test scenario (1–6)

```bash
python main.py --test --scenario 2
```

---

## JSON Output Format

Every AI turn produces a validated JSON object:

```json
{
  "next_state":     "S1 / S2 / S3 / S4 / S5",
  "response_text":  "Under 20 words",
  "lead_score":     "Hot / Warm / Cold",
  "action":         "continue / transfer / end"
}
```

---

## Test Scenarios

| # | Scenario | Expected Lead |
|---|----------|---------------|
| 1 | Ideal user — clear answers | Warm |
| 2 | High intent — IVF failure | Hot |
| 3 | Low intent — <1 year | Cold |
| 4 | Mixed Hindi-English | Warm |
| 5 | Vague answers | varies |
| 6 | Off-topic questions | Hot |

---

## Logging

All conversations are logged to `logs/conversations.jsonl`.

Each line is a JSON object:
```json
{
  "session_id": "a1b2c3d4",
  "timestamp":  "2026-03-31T10:00:00Z",
  "turn":       1,
  "state":      "S2",
  "user_input": "about 2 years",
  "response":   { ... },
  "lead_score": "Warm"
}
```

Session summaries are also appended with `"event": "SESSION_END"`.

---

## Rules Enforced

- Response text ≤ 20 words (truncated automatically)
- One question per turn
- No medical advice or clinical claims
- Always valid JSON output
- API failure: retry once, then fall back to deterministic response
- Invalid JSON from AI: regenerate with stricter prompt
